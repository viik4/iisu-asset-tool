package com.iisu.assettool.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Cache manager for game and platform data.
 * Provides fast loading by caching filesystem scan results in memory and on disk.
 *
 * Cache invalidation:
 * - Manual refresh via clearCache()
 * - Automatic refresh when cache is older than CACHE_EXPIRY_MS
 * - Per-platform refresh when games are modified
 */
object GameCache {
    private const val TAG = "GameCache"
    private const val PREFS_NAME = "game_cache_prefs"
    private const val PREF_CACHE_DATA = "cache_data"
    private const val PREF_CACHE_TIMESTAMP = "cache_timestamp"
    private const val CACHE_EXPIRY_MS = 5 * 60 * 1000L // 5 minutes

    // In-memory cache
    private var platformsCache: List<String>? = null
    private val gamesCache = mutableMapOf<String, List<GameInfo>>()
    private val platformInfoCache = mutableMapOf<String, CachedPlatformInfo>()
    private var cacheTimestamp: Long = 0

    // Mutex for thread-safe cache operations
    private val cacheMutex = Mutex()

    /**
     * Cached platform info including pre-computed stats.
     */
    data class CachedPlatformInfo(
        val name: String,
        val displayName: String,
        val gameCount: Int,
        val missingIcons: Int,
        val missingHeroes: Int,
        val missingLogos: Int,
        val iconPath: String?
    )

    /**
     * Check if cache is valid and not expired.
     */
    private fun isCacheValid(): Boolean {
        if (platformsCache == null) return false
        val age = System.currentTimeMillis() - cacheTimestamp
        return age < CACHE_EXPIRY_MS
    }

    /**
     * Get platforms with ROMs, using cache if available.
     */
    suspend fun getPlatformsWithRoms(forceRefresh: Boolean = false): List<String> {
        // Check cache first
        val cached = cacheMutex.withLock {
            if (!forceRefresh && isCacheValid() && platformsCache != null) {
                Log.d(TAG, "Returning cached platforms: ${platformsCache?.size}")
                return@withLock platformsCache
            }
            null
        }

        if (cached != null) {
            return cached
        }

        // Do IO outside lock
        Log.d(TAG, "Scanning platforms from filesystem...")
        val platforms = withContext(Dispatchers.IO) {
            IisuDirectoryManager.getPlatformsWithRoms()
        }

        // Update cache
        cacheMutex.withLock {
            platformsCache = platforms
            cacheTimestamp = System.currentTimeMillis()
            Log.d(TAG, "Cached ${platforms.size} platforms")
        }

        return platforms
    }

    /**
     * Get games for a platform, using cache if available.
     * @param platform The platform to get games for
     * @param forceRefresh If true, bypass cache and scan filesystem
     * @param deepSearch If true, scan subdirectories for games (e.g., Platform/Category/Game)
     */
    suspend fun getGamesForPlatform(platform: String, forceRefresh: Boolean = false,
                                    deepSearch: Boolean = false): List<GameInfo> {
        // Create a cache key that includes the deep search setting
        val cacheKey = if (deepSearch) "${platform}_deep" else platform

        // Check cache first
        val cached = cacheMutex.withLock {
            if (!forceRefresh && isCacheValid() && gamesCache.containsKey(cacheKey)) {
                Log.d(TAG, "Returning cached games for $cacheKey: ${gamesCache[cacheKey]?.size}")
                return@withLock gamesCache[cacheKey]!!
            }
            null
        }

        if (cached != null) {
            return cached
        }

        // Do IO outside lock
        Log.d(TAG, "Scanning games for $platform from filesystem (deepSearch=$deepSearch)...")
        val games = withContext(Dispatchers.IO) {
            IisuDirectoryManager.getGamesForPlatform(platform, deepSearch)
        }

        // Update cache
        cacheMutex.withLock {
            gamesCache[cacheKey] = games
            // Update platform info cache as well
            updatePlatformInfoCache(platform, games)
            Log.d(TAG, "Cached ${games.size} games for $cacheKey")
        }

        return games
    }

    /**
     * Get cached platform info (stats, icon path, etc.) for all platforms.
     * This is the fast path for loading the platform grid.
     */
    suspend fun getCachedPlatformInfoList(context: Context, forceRefresh: Boolean = false): List<CachedPlatformInfo> {
        Log.d(TAG, "getCachedPlatformInfoList called (forceRefresh=$forceRefresh)")

        // First, check memory cache (quick, no IO)
        val memoryCached = cacheMutex.withLock {
            if (!forceRefresh && isCacheValid() && platformsCache != null) {
                val platforms = platformsCache!!
                val allCached = platforms.all { platformInfoCache.containsKey(it) }
                if (allCached) {
                    Log.d(TAG, "Returning cached platform info for ${platforms.size} platforms")
                    return@withLock platforms.mapNotNull { platformInfoCache[it] }
                }
            }
            null
        }

        if (memoryCached != null) {
            Log.d(TAG, "Returning memory cached result: ${memoryCached.size} platforms")
            return memoryCached
        }

        // Try disk cache (IO outside lock)
        if (!forceRefresh) {
            Log.d(TAG, "Checking disk cache...")
            val diskCache = withContext(Dispatchers.IO) {
                loadFromDiskCache(context)
            }
            if (diskCache != null && diskCache.isNotEmpty()) {
                Log.d(TAG, "Loaded ${diskCache.size} platforms from disk cache")
                cacheMutex.withLock {
                    diskCache.forEach { platformInfoCache[it.name] = it }
                    platformsCache = diskCache.map { it.name }
                    cacheTimestamp = System.currentTimeMillis()
                }
                return diskCache
            }
            Log.d(TAG, "Disk cache miss or empty")
        }

        // Do filesystem scan (IO outside lock)
        Log.d(TAG, "Scanning platforms from filesystem...")
        val scannedPlatforms = withContext(Dispatchers.IO) {
            val result = IisuDirectoryManager.getPlatformsWithRoms()
            Log.d(TAG, "IisuDirectoryManager.getPlatformsWithRoms returned: $result")
            result
        }

        if (scannedPlatforms.isEmpty()) {
            Log.w(TAG, "No platforms found! Root: ${IisuDirectoryManager.getIisuRoot().absolutePath}")
            return emptyList()
        }

        Log.d(TAG, "Building platform info cache for ${scannedPlatforms.size} platforms...")
        val platformInfoList = withContext(Dispatchers.IO) {
            scannedPlatforms.map { platformName ->
                Log.d(TAG, "Scanning games for platform: $platformName")
                val games = IisuDirectoryManager.getGamesForPlatform(platformName)
                Log.d(TAG, "Found ${games.size} games for $platformName")

                val iconFile = IisuDirectoryManager.getPlatformIcon(platformName)

                Pair(platformName, Triple(games, CachedPlatformInfo(
                    name = platformName,
                    displayName = formatPlatformName(platformName),
                    gameCount = games.size,
                    missingIcons = games.count { !it.hasIcon },
                    missingHeroes = games.count { !it.hasHero },
                    missingLogos = games.count { !it.hasLogo },
                    iconPath = if (iconFile.exists()) iconFile.absolutePath else null
                ), games))
            }
        }

        // Update memory cache with lock (quick, no IO)
        val infoList = cacheMutex.withLock {
            platformsCache = scannedPlatforms
            cacheTimestamp = System.currentTimeMillis()

            platformInfoList.map { (platformName, triple) ->
                val (games, info, _) = triple
                gamesCache[platformName] = games
                platformInfoCache[platformName] = info
                info
            }
        }

        // Save to disk cache (IO outside lock)
        withContext(Dispatchers.IO) {
            saveToDiskCache(context, infoList)
        }

        Log.d(TAG, "Built and cached info for ${infoList.size} platforms")
        return infoList
    }

    /**
     * Update platform info cache after games are modified.
     */
    private fun updatePlatformInfoCache(platform: String, games: List<GameInfo>) {
        val iconFile = IisuDirectoryManager.getPlatformIcon(platform)
        platformInfoCache[platform] = CachedPlatformInfo(
            name = platform,
            displayName = formatPlatformName(platform),
            gameCount = games.size,
            missingIcons = games.count { !it.hasIcon },
            missingHeroes = games.count { !it.hasHero },
            missingLogos = games.count { !it.hasLogo },
            iconPath = if (iconFile.exists()) iconFile.absolutePath else null
        )
    }

    /**
     * Invalidate cache for a specific platform.
     * Call this after modifying games in a platform.
     */
    suspend fun invalidatePlatform(platform: String) = cacheMutex.withLock {
        Log.d(TAG, "Invalidating cache for platform: $platform")
        gamesCache.remove(platform)
        platformInfoCache.remove(platform)
    }

    /**
     * Clear all caches.
     */
    suspend fun clearCache(context: Context? = null) = cacheMutex.withLock {
        Log.d(TAG, "Clearing all caches")
        platformsCache = null
        gamesCache.clear()
        platformInfoCache.clear()
        cacheTimestamp = 0

        // Clear disk cache
        context?.let {
            val prefs = it.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit()
                .remove(PREF_CACHE_DATA)
                .remove(PREF_CACHE_TIMESTAMP)
                .apply()
        }
    }

    /**
     * Save platform info to disk cache for faster startup.
     */
    private fun saveToDiskCache(context: Context, platforms: List<CachedPlatformInfo>) {
        try {
            val jsonArray = JSONArray()
            platforms.forEach { platform ->
                val obj = JSONObject().apply {
                    put("name", platform.name)
                    put("displayName", platform.displayName)
                    put("gameCount", platform.gameCount)
                    put("missingIcons", platform.missingIcons)
                    put("missingHeroes", platform.missingHeroes)
                    put("missingLogos", platform.missingLogos)
                    put("iconPath", platform.iconPath ?: "")
                }
                jsonArray.put(obj)
            }

            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit()
                .putString(PREF_CACHE_DATA, jsonArray.toString())
                .putLong(PREF_CACHE_TIMESTAMP, System.currentTimeMillis())
                .apply()

            Log.d(TAG, "Saved ${platforms.size} platforms to disk cache")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save disk cache", e)
        }
    }

    /**
     * Load platform info from disk cache.
     */
    private fun loadFromDiskCache(context: Context): List<CachedPlatformInfo>? {
        try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val timestamp = prefs.getLong(PREF_CACHE_TIMESTAMP, 0)

            // Check if disk cache is expired
            val age = System.currentTimeMillis() - timestamp
            if (age > CACHE_EXPIRY_MS) {
                Log.d(TAG, "Disk cache expired (age: ${age}ms)")
                return null
            }

            val json = prefs.getString(PREF_CACHE_DATA, null) ?: return null
            val jsonArray = JSONArray(json)

            val platforms = mutableListOf<CachedPlatformInfo>()
            for (i in 0 until jsonArray.length()) {
                val obj = jsonArray.getJSONObject(i)
                val iconPath = obj.getString("iconPath").ifEmpty { null }

                // Verify icon file still exists
                val validIconPath = iconPath?.let {
                    if (File(it).exists()) it else null
                }

                platforms.add(CachedPlatformInfo(
                    name = obj.getString("name"),
                    displayName = obj.getString("displayName"),
                    gameCount = obj.getInt("gameCount"),
                    missingIcons = obj.getInt("missingIcons"),
                    missingHeroes = obj.getInt("missingHeroes"),
                    missingLogos = obj.getInt("missingLogos"),
                    iconPath = validIconPath
                ))
            }

            Log.d(TAG, "Loaded ${platforms.size} platforms from disk cache")
            return platforms
        } catch (e: Exception) {
            Log.e(TAG, "Failed to load disk cache", e)
            return null
        }
    }

    /**
     * Format platform name for display.
     */
    private fun formatPlatformName(name: String): String {
        return when (name.lowercase()) {
            "nes" -> "NES"
            "snes", "sfc" -> "SNES"
            "n64" -> "N64"
            "gc" -> "GameCube"
            "wii" -> "Wii"
            "wiiu" -> "Wii U"
            "switch" -> "Switch"
            "gb" -> "Game Boy"
            "gbc" -> "Game Boy Color"
            "gba" -> "GBA"
            "nds" -> "Nintendo DS"
            "n3ds", "3ds" -> "3DS"
            "psx", "ps1" -> "PlayStation"
            "ps2" -> "PS2"
            "ps3" -> "PS3"
            "psp" -> "PSP"
            "psvita", "vita" -> "PS Vita"
            "megadrive", "genesis" -> "Genesis"
            "saturn" -> "Saturn"
            "dreamcast", "dc" -> "Dreamcast"
            "gamegear", "gg" -> "Game Gear"
            "mastersystem", "sms" -> "Master System"
            "arcade", "mame" -> "Arcade"
            "neogeo" -> "Neo Geo"
            else -> name.replaceFirstChar { it.uppercase() }
        }
    }

    /**
     * Load a platform icon bitmap with caching.
     */
    private val iconBitmapCache = mutableMapOf<String, Bitmap?>()

    fun getPlatformIconBitmap(iconPath: String?): Bitmap? {
        if (iconPath == null) return null

        return iconBitmapCache.getOrPut(iconPath) {
            try {
                BitmapFactory.decodeFile(iconPath)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to load icon: $iconPath", e)
                null
            }
        }
    }

    /**
     * Clear icon bitmap cache (call on low memory).
     */
    fun clearIconCache() {
        iconBitmapCache.clear()
    }
}
