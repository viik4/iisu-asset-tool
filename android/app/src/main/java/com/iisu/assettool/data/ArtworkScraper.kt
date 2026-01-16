package com.iisu.assettool.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Simple artwork scraper for the standalone Icon/Cover generator tabs.
 * Searches artwork databases directly by game name.
 * Sources: SteamGridDB (if API key provided), TheGamesDB, Libretro thumbnails.
 */
class ArtworkScraper {

    companion object {
        private const val TAG = "ArtworkScraper"
        private const val LIBRETRO_BASE_URL = "https://thumbnails.libretro.com"
        private const val SGDB_BASE_URL = "https://www.steamgriddb.com/api/v2"
        private const val TGDB_BASE_URL = "https://api.thegamesdb.net/v1"
        private const val TIMEOUT = 15000
    }

    // Optional SteamGridDB API key
    private var sgdbApiKey: String? = null

    // Embedded TheGamesDB public API key
    private val tgdbApiKey: String by lazy {
        val p = listOf(0x65, 0x32, 0x36, 0x38, 0x30, 0x36, 0x36, 0x37)
        val q = listOf(0x30, 0x36, 0x39, 0x37, 0x61, 0x31, 0x65, 0x39)
        val r = listOf(0x64, 0x61, 0x39, 0x36, 0x39, 0x39, 0x36, 0x31)
        val s = listOf(0x62, 0x63, 0x66, 0x62, 0x62, 0x39, 0x61, 0x33)
        val t = listOf(0x64, 0x61, 0x34, 0x35, 0x33, 0x38, 0x32, 0x65)
        val u = listOf(0x65, 0x38, 0x30, 0x32, 0x61, 0x62, 0x31, 0x38)
        val v = listOf(0x62, 0x65, 0x66, 0x37, 0x33, 0x33, 0x35, 0x66)
        val w = listOf(0x35, 0x62, 0x39, 0x61, 0x31, 0x34, 0x39, 0x64)
        (p + q + r + s + t + u + v + w).map { it.toChar() }.joinToString("")
    }

    fun setSteamGridDBApiKey(key: String?) {
        sgdbApiKey = key
    }

    /**
     * Search for game icons from multiple sources.
     * Returns results from SteamGridDB (if API key set), TheGamesDB, and Libretro.
     */
    suspend fun searchIcons(query: String, platform: Platform): List<ArtworkResult> {
        return withContext(Dispatchers.IO) {
            val results = mutableListOf<ArtworkResult>()

            // Try SteamGridDB first (best quality, requires API key)
            if (!sgdbApiKey.isNullOrEmpty()) {
                try {
                    results.addAll(searchSteamGridDB(query, platform, ArtworkType.ICON))
                    Log.d(TAG, "SteamGridDB returned ${results.size} results for '$query'")
                } catch (e: Exception) {
                    Log.w(TAG, "SteamGridDB search failed: ${e.message}")
                }
            }

            // Try TheGamesDB
            try {
                val tgdbResults = searchTheGamesDB(query, platform, ArtworkType.ICON)
                results.addAll(tgdbResults)
                Log.d(TAG, "TheGamesDB returned ${tgdbResults.size} results for '$query'")
            } catch (e: Exception) {
                Log.w(TAG, "TheGamesDB search failed: ${e.message}")
            }

            // Try Libretro thumbnails as fallback
            try {
                val libretroResults = searchLibretro(query, platform, ArtworkType.ICON)
                results.addAll(libretroResults)
                Log.d(TAG, "Libretro returned ${libretroResults.size} results for '$query'")
            } catch (e: Exception) {
                Log.w(TAG, "Libretro search failed: ${e.message}")
            }

            Log.d(TAG, "Total ${results.size} icon results for '$query'")
            results
        }
    }

    /**
     * Search for game cover art from multiple sources.
     */
    suspend fun searchCovers(query: String, platform: Platform): List<ArtworkResult> {
        return withContext(Dispatchers.IO) {
            val results = mutableListOf<ArtworkResult>()

            // Try SteamGridDB first
            if (!sgdbApiKey.isNullOrEmpty()) {
                try {
                    results.addAll(searchSteamGridDB(query, platform, ArtworkType.COVER))
                } catch (e: Exception) {
                    Log.w(TAG, "SteamGridDB cover search failed: ${e.message}")
                }
            }

            // Try TheGamesDB
            try {
                results.addAll(searchTheGamesDB(query, platform, ArtworkType.COVER))
            } catch (e: Exception) {
                Log.w(TAG, "TheGamesDB cover search failed: ${e.message}")
            }

            // Try Libretro thumbnails
            try {
                results.addAll(searchLibretro(query, platform, ArtworkType.COVER))
            } catch (e: Exception) {
                Log.w(TAG, "Libretro cover search failed: ${e.message}")
            }

            results
        }
    }

    /**
     * Search for hero images (wide banners) from SteamGridDB.
     */
    suspend fun searchHeroes(query: String, platform: Platform): List<ArtworkResult> {
        return withContext(Dispatchers.IO) {
            val results = mutableListOf<ArtworkResult>()

            if (!sgdbApiKey.isNullOrEmpty()) {
                try {
                    results.addAll(searchSteamGridDB(query, platform, ArtworkType.HERO))
                } catch (e: Exception) {
                    Log.w(TAG, "SteamGridDB hero search failed: ${e.message}")
                }
            }

            results
        }
    }

    /**
     * Search for logo images from SteamGridDB.
     */
    suspend fun searchLogos(query: String, platform: Platform): List<ArtworkResult> {
        return withContext(Dispatchers.IO) {
            val results = mutableListOf<ArtworkResult>()

            if (!sgdbApiKey.isNullOrEmpty()) {
                try {
                    results.addAll(searchSteamGridDB(query, platform, ArtworkType.LOGO))
                } catch (e: Exception) {
                    Log.w(TAG, "SteamGridDB logo search failed: ${e.message}")
                }
            }

            results
        }
    }

    // ==================== SteamGridDB ====================

    private fun searchSteamGridDB(query: String, platform: Platform, type: ArtworkType): List<ArtworkResult> {
        val apiKey = sgdbApiKey ?: return emptyList()
        val results = mutableListOf<ArtworkResult>()

        // Search for game
        val searchUrl = "$SGDB_BASE_URL/search/autocomplete/${URLEncoder.encode(query, "UTF-8")}"
        val searchResponse = httpGetWithAuth(searchUrl, apiKey) ?: return results

        val searchJson = JSONObject(searchResponse)
        if (!searchJson.optBoolean("success", false)) return results

        val data = searchJson.optJSONArray("data") ?: return results
        if (data.length() == 0) return results

        // Find best matching game from results
        val gameId = findBestMatchingGame(query, data)

        // Get artwork based on type
        val artworkUrl = when (type) {
            ArtworkType.ICON, ArtworkType.COVER -> "$SGDB_BASE_URL/grids/game/$gameId?dimensions=1024x1024,512x512&types=static&limit=20"
            ArtworkType.HERO -> "$SGDB_BASE_URL/heroes/game/$gameId?types=static&limit=20"
            ArtworkType.LOGO -> "$SGDB_BASE_URL/logos/game/$gameId?types=static&limit=20"
            else -> return results
        }

        val artworkResponse = httpGetWithAuth(artworkUrl, apiKey) ?: return results
        val artworkJson = JSONObject(artworkResponse)
        if (!artworkJson.optBoolean("success", false)) return results

        val artworks = artworkJson.optJSONArray("data") ?: return results

        for (i in 0 until artworks.length()) {
            val artwork = artworks.getJSONObject(i)
            val imageUrl = artwork.getString("url")
            val width = artwork.optInt("width", 0)
            val height = artwork.optInt("height", 0)
            val score = artwork.optInt("score", 0)

            results.add(ArtworkResult(
                url = imageUrl,
                title = "$query (SteamGridDB)",
                platform = platform,
                type = type,
                width = width,
                height = height,
                source = "SteamGridDB",
                score = score
            ))
        }

        // Sort by highest score first
        return results.sortedByDescending { it.score }
    }

    // ==================== TheGamesDB ====================

    private fun searchTheGamesDB(query: String, platform: Platform, type: ArtworkType): List<ArtworkResult> {
        val results = mutableListOf<ArtworkResult>()

        // Map platform to TGDB platform ID
        val platformId = getTGDBPlatformId(platform) ?: return results

        // Search for game
        val searchUrl = "$TGDB_BASE_URL/Games/ByGameName?apikey=$tgdbApiKey&name=${URLEncoder.encode(query, "UTF-8")}&filter[platform]=$platformId&include=boxart"
        val response = httpGet(searchUrl) ?: return results

        val json = JSONObject(response)
        val gamesData = json.optJSONObject("data") ?: return results
        val games = gamesData.optJSONArray("games") ?: return results

        if (games.length() == 0) return results

        // Get boxart images
        val imagesData = json.optJSONObject("include")?.optJSONObject("boxart") ?: return results
        val baseUrl = imagesData.optJSONObject("base_url")
        val originalBaseUrl = baseUrl?.optString("original", "") ?: ""

        val dataObj = imagesData.optJSONObject("data") ?: return results

        // Find best matching game from results
        val gameId = findBestMatchingGameTGDB(query, games)

        val gameImages = dataObj.optJSONArray(gameId) ?: return results

        for (i in 0 until gameImages.length()) {
            val img = gameImages.getJSONObject(i)
            val side = img.optString("side")
            if (side == "front") {
                val filename = img.getString("filename")
                val imageUrl = originalBaseUrl + filename

                results.add(ArtworkResult(
                    url = imageUrl,
                    title = "$query (TheGamesDB)",
                    platform = platform,
                    type = type,
                    source = "TheGamesDB"
                ))
            }
        }

        return results
    }

    private fun getTGDBPlatformId(platform: Platform): Int? {
        return when (platform) {
            Platform.NES -> 7
            Platform.SNES -> 6
            Platform.N64 -> 3
            Platform.GAMEBOY -> 4912
            Platform.GBA -> 12
            Platform.DS -> 8
            Platform.PS1 -> 10
            Platform.PS2 -> 11
            Platform.PSP -> 13
            Platform.GENESIS -> 18
            Platform.DREAMCAST -> 16
            Platform.ARCADE -> 23
            else -> null
        }
    }

    // ==================== Libretro Thumbnails ====================

    /**
     * Search Libretro thumbnail repository.
     */
    private fun searchLibretro(
        query: String,
        platform: Platform,
        type: ArtworkType
    ): List<ArtworkResult> {
        val results = mutableListOf<ArtworkResult>()

        // Map platform to Libretro naming convention
        val platformDir = when (platform) {
            Platform.NES -> "Nintendo - Nintendo Entertainment System"
            Platform.SNES -> "Nintendo - Super Nintendo Entertainment System"
            Platform.N64 -> "Nintendo - Nintendo 64"
            Platform.GAMEBOY -> "Nintendo - Game Boy"
            Platform.GBA -> "Nintendo - Game Boy Advance"
            Platform.DS -> "Nintendo - Nintendo DS"
            Platform.PS1 -> "Sony - PlayStation"
            Platform.PS2 -> "Sony - PlayStation 2"
            Platform.PSP -> "Sony - PlayStation Portable"
            Platform.GENESIS -> "Sega - Mega Drive - Genesis"
            Platform.DREAMCAST -> "Sega - Dreamcast"
            Platform.ARCADE -> "MAME"
            else -> return results
        }

        val artType = when (type) {
            ArtworkType.ICON -> "Named_Boxarts"
            ArtworkType.COVER -> "Named_Boxarts"
            else -> "Named_Snaps"
        }

        // Construct thumbnail URL
        val cleanQuery = query.replace(" ", "_")
            .replace(":", "")
            .replace("?", "")
            .replace("/", "_")
            .replace("\\", "_")

        val baseUrl = "$LIBRETRO_BASE_URL/${URLEncoder.encode(platformDir, "UTF-8")}/$artType/${URLEncoder.encode(cleanQuery, "UTF-8")}.png"

        // Check if the URL is valid by making a HEAD request
        if (isUrlReachable(baseUrl)) {
            results.add(
                ArtworkResult(
                    url = baseUrl,
                    title = "$query (Libretro)",
                    platform = platform,
                    type = type,
                    source = "Libretro"
                )
            )
        }

        // Also try some common variations
        val variations = listOf(
            "${cleanQuery}_(USA)",
            "${cleanQuery}_(Europe)",
            "${cleanQuery}_(Japan)",
            "${cleanQuery}_(World)"
        )

        for (variation in variations) {
            val varUrl = "$LIBRETRO_BASE_URL/${URLEncoder.encode(platformDir, "UTF-8")}/$artType/${URLEncoder.encode(variation, "UTF-8")}.png"
            if (isUrlReachable(varUrl)) {
                results.add(
                    ArtworkResult(
                        url = varUrl,
                        title = "$query ($variation) (Libretro)",
                        platform = platform,
                        type = type,
                        source = "Libretro"
                    )
                )
            }
        }

        return results
    }

    // ==================== HTTP Helpers ====================

    private fun isUrlReachable(url: String): Boolean {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.requestMethod = "HEAD"
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")
            val reachable = connection.responseCode == HttpURLConnection.HTTP_OK
            connection.disconnect()
            reachable
        } catch (e: Exception) {
            false
        }
    }

    private fun httpGet(url: String): String? {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = TIMEOUT
            connection.readTimeout = TIMEOUT
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                connection.inputStream.bufferedReader().readText()
            } else null
        } catch (e: Exception) {
            Log.e(TAG, "HTTP GET failed: $url", e)
            null
        }
    }

    private fun httpGetWithAuth(url: String, apiKey: String): String? {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = TIMEOUT
            connection.readTimeout = TIMEOUT
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Authorization", "Bearer $apiKey")
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                connection.inputStream.bufferedReader().readText()
            } else null
        } catch (e: Exception) {
            Log.e(TAG, "HTTP GET with auth failed: $url", e)
            null
        }
    }

    // ==================== Search Matching Helpers ====================

    /**
     * Find the best matching game from TheGamesDB search results.
     */
    private fun findBestMatchingGameTGDB(query: String, games: JSONArray): String {
        val normalizedQuery = normalizeGameName(query)
        var bestMatchId = games.getJSONObject(0).getInt("id").toString()
        var bestScore = 0.0

        for (i in 0 until games.length()) {
            val game = games.getJSONObject(i)
            val gameName = game.optString("game_title", "")
            val gameId = game.getInt("id").toString()

            val normalizedName = normalizeGameName(gameName)
            val score = calculateMatchScore(normalizedQuery, normalizedName)

            if (score > bestScore) {
                bestScore = score
                bestMatchId = gameId
            }

            if (score >= 1.0) break
        }

        return bestMatchId
    }

    /**
     * Find the best matching game from SteamGridDB search results.
     * Uses string similarity to find the closest match to the query.
     */
    private fun findBestMatchingGame(query: String, searchResults: JSONArray): Int {
        val normalizedQuery = normalizeGameName(query)
        var bestMatchId = searchResults.getJSONObject(0).getInt("id")
        var bestScore = 0.0

        for (i in 0 until searchResults.length()) {
            val game = searchResults.getJSONObject(i)
            val gameName = game.optString("name", "")
            val gameId = game.getInt("id")

            val normalizedName = normalizeGameName(gameName)
            val score = calculateMatchScore(normalizedQuery, normalizedName)

            Log.d(TAG, "Match score for '$gameName': $score (normalized: '$normalizedName' vs '$normalizedQuery')")

            if (score > bestScore) {
                bestScore = score
                bestMatchId = gameId
            }

            // Perfect match - no need to continue
            if (score >= 1.0) break
        }

        return bestMatchId
    }

    /**
     * Normalize game name for comparison by removing common suffixes and cleaning up.
     * Handles accented characters by converting them to their ASCII equivalents.
     */
    private fun normalizeGameName(name: String): String {
        // First, normalize accented characters to ASCII equivalents
        val normalized = java.text.Normalizer.normalize(name, java.text.Normalizer.Form.NFD)
            .replace(Regex("[\\p{InCombiningDiacriticalMarks}]"), "")  // Remove diacritical marks

        return normalized.lowercase()
            .replace(Regex("\\s*[-–—:]\\s*"), " ")  // Normalize dashes and colons to spaces
            .replace(Regex("\\s+"), " ")  // Normalize multiple spaces
            .replace(Regex("['']"), "")  // Remove apostrophes
            .replace(Regex("[^a-z0-9 ]"), "")  // Remove remaining special characters
            .trim()
    }

    /**
     * Calculate match score between query and game name.
     * Returns a score from 0.0 to 1.0 where 1.0 is a perfect match.
     */
    private fun calculateMatchScore(query: String, gameName: String): Double {
        // Exact match
        if (query == gameName) return 1.0

        // Query is contained exactly in game name (e.g., "Pokemon Moon" in "Pokemon Moon")
        if (gameName == query) return 1.0

        // Game name starts with the query (high priority)
        if (gameName.startsWith(query)) {
            // Penalize longer names that just happen to start with the query
            val extraLength = gameName.length - query.length
            return 0.95 - (extraLength * 0.02).coerceAtMost(0.3)
        }

        // Query starts with the game name (game name is shorter version)
        if (query.startsWith(gameName)) {
            return 0.8
        }

        // Check word-by-word match
        val queryWords = query.split(" ").filter { it.isNotEmpty() }
        val nameWords = gameName.split(" ").filter { it.isNotEmpty() }

        // Count matching words
        val matchingWords = queryWords.count { qWord ->
            nameWords.any { nWord -> nWord == qWord || nWord.startsWith(qWord) || qWord.startsWith(nWord) }
        }

        // All query words match
        if (matchingWords == queryWords.size) {
            // Prefer shorter game names when all words match
            val lengthPenalty = (nameWords.size - queryWords.size) * 0.05
            return (0.85 - lengthPenalty).coerceAtLeast(0.5)
        }

        // Partial word match
        val wordMatchRatio = matchingWords.toDouble() / queryWords.size
        return wordMatchRatio * 0.6

    }
}
