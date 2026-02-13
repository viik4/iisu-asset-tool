package com.iisu.assettool.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import com.iisu.assettool.data.GameSearchResult
import com.iisu.assettool.ui.SettingsFragment
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Represents a single artwork option from a source.
 */
data class ArtworkOption(
    val url: String,
    val source: String,
    val thumbnail: Bitmap? = null,  // Low-res preview
    val width: Int = 0,
    val height: Int = 0
) {
    /**
     * Crop mode for hero images, selected interactively in the artwork picker.
     * NONE = use original, CROP_LEFT/CROP_CENTER/CROP_RIGHT = preset positions,
     * CROP_CUSTOM = user-chosen horizontal position via slider.
     */
    enum class CropMode {
        NONE,
        CROP_LEFT,
        CROP_CENTER,
        CROP_RIGHT,
        CROP_CUSTOM
    }

    /** Crop mode selected by user in the picker dialog. Default: NONE (use original). */
    var cropMode: CropMode = CropMode.NONE

    /** Custom horizontal position (0.0=left, 1.0=right). Used when cropMode is CROP_CUSTOM. */
    var customHorizontalPosition: Float = 0.5f
}

/**
 * Result of searching for artwork - contains multiple options.
 */
data class ArtworkSearchResult(
    val gameName: String,
    val options: List<ArtworkOption>,
    val currentImage: Bitmap? = null  // The existing image if any
)

/**
 * Artwork scraper for fetching game icons, covers, heroes, and logos from various sources.
 * Supports interactive mode where users can choose from multiple options.
 * Applies iiSU-style borders to icons.
 */
class ArtworkScraper(private val context: Context) {

    companion object {
        private const val TAG = "ArtworkScraper"

        // SteamGridDB API
        private const val SGDB_BASE_URL = "https://www.steamgriddb.com/api/v2"
        private const val SGDB_TIMEOUT = 40000 // 40 seconds

        // TheGamesDB API (has embedded public key)
        private const val TGDB_BASE_URL = "https://api.thegamesdb.net/v1"
        private const val TGDB_TIMEOUT = 30000

        // Libretro Thumbnails
        private const val LIBRETRO_BASE_URL = "https://thumbnails.libretro.com"

        // Image sizes
        const val ICON_SIZE = 256
        const val HIGH_RES_ICON_SIZE = 1024
        private const val THUMBNAIL_SIZE = 128
    }

    // Icon generator for applying iiSU-style borders
    private val iconGenerator = IconGenerator(context)

    // Embedded TheGamesDB public API key (same as desktop app)
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

    // SteamGridDB API key (user must provide)
    private var sgdbApiKey: String? = null

    // Platform ID mappings for TheGamesDB
    private val tgdbPlatformMap = mapOf(
        // Nintendo
        "nes" to 7, "snes" to 6, "n64" to 3, "n64dd" to 3,
        "gamecube" to 2, "gc" to 2, "wii" to 9, "wiiu" to 38, "switch" to 4971,
        "gb" to 4, "gbc" to 41, "gba" to 5,
        "nds" to 8, "3ds" to 4912, "n3ds" to 4912, "vb" to 4918,
        // Sony
        "psx" to 10, "ps1" to 10, "ps2" to 11, "ps3" to 12, "ps4" to 4919, "ps5" to 4980,
        "psp" to 13, "psvita" to 39, "vita" to 39,
        // Microsoft
        "xbox" to 14, "xbox360" to 15, "xboxone" to 4920, "xboxseries" to 4981,
        // Sega
        "mastersystem" to 35, "sms" to 35,
        "genesis" to 18, "megadrive" to 18,
        "segacd" to 21, "sega32x" to 33, "32x" to 33,
        "saturn" to 17, "dreamcast" to 16, "dc" to 16,
        "gamegear" to 20, "gg" to 20,
        // Neo Geo
        "neogeo" to 24, "ng" to 24, "neogeocd" to 24, "ngcd" to 24,
        "ngp" to 4922, "ngpc" to 4923,
        // Atari
        "atari2600" to 22, "atari5200" to 26, "atari7800" to 27,
        "jaguar" to 28, "lynx" to 29,
        // Other
        "arcade" to 23, "mame" to 23, "fba" to 23,
        "tg16" to 34, "pce" to 34, "tgcd" to 4955, "pcecd" to 4955,
        "ws" to 4925, "wsc" to 4926,
        "coleco" to 31, "intv" to 32,
        "pc" to 1, "dos" to 1, "scummvm" to 1
    )

    // Libretro playlist names
    private val libretroPlaylistMap = mapOf(
        // Nintendo
        "nes" to "Nintendo - Nintendo Entertainment System",
        "snes" to "Nintendo - Super Nintendo Entertainment System",
        "n64" to "Nintendo - Nintendo 64", "n64dd" to "Nintendo - Nintendo 64DD",
        "gamecube" to "Nintendo - GameCube", "gc" to "Nintendo - GameCube",
        "wii" to "Nintendo - Wii", "wiiu" to "Nintendo - Wii U",
        "switch" to "Nintendo - Nintendo Switch",
        "gb" to "Nintendo - Game Boy",
        "gbc" to "Nintendo - Game Boy Color",
        "gba" to "Nintendo - Game Boy Advance",
        "nds" to "Nintendo - Nintendo DS",
        "3ds" to "Nintendo - Nintendo 3DS", "n3ds" to "Nintendo - Nintendo 3DS",
        "vb" to "Nintendo - Virtual Boy",
        // Sony
        "psx" to "Sony - PlayStation", "ps1" to "Sony - PlayStation",
        "ps2" to "Sony - PlayStation 2",
        "ps3" to "Sony - PlayStation 3",
        "psp" to "Sony - PlayStation Portable",
        "psvita" to "Sony - PlayStation Vita", "vita" to "Sony - PlayStation Vita",
        // Microsoft
        "xbox" to "Microsoft - Xbox",
        "xbox360" to "Microsoft - Xbox 360",
        // Sega
        "mastersystem" to "Sega - Master System - Mark III", "sms" to "Sega - Master System - Mark III",
        "genesis" to "Sega - Mega Drive - Genesis", "megadrive" to "Sega - Mega Drive - Genesis",
        "segacd" to "Sega - Mega-CD - Sega CD",
        "sega32x" to "Sega - 32X", "32x" to "Sega - 32X",
        "saturn" to "Sega - Saturn",
        "dreamcast" to "Sega - Dreamcast", "dc" to "Sega - Dreamcast",
        "gamegear" to "Sega - Game Gear", "gg" to "Sega - Game Gear",
        // Neo Geo
        "neogeo" to "SNK - Neo Geo", "ng" to "SNK - Neo Geo",
        "neogeocd" to "SNK - Neo Geo CD", "ngcd" to "SNK - Neo Geo CD",
        "ngp" to "SNK - Neo Geo Pocket", "ngpc" to "SNK - Neo Geo Pocket Color",
        // Atari
        "atari2600" to "Atari - 2600",
        "atari5200" to "Atari - 5200",
        "atari7800" to "Atari - 7800",
        "jaguar" to "Atari - Jaguar",
        "lynx" to "Atari - Lynx",
        // Other
        "arcade" to "MAME", "mame" to "MAME", "fba" to "FBNeo - Arcade Games",
        "tg16" to "NEC - PC Engine - TurboGrafx 16", "pce" to "NEC - PC Engine - TurboGrafx 16",
        "tgcd" to "NEC - PC Engine CD - TurboGrafx-CD", "pcecd" to "NEC - PC Engine CD - TurboGrafx-CD",
        "ws" to "Bandai - WonderSwan",
        "wsc" to "Bandai - WonderSwan Color",
        "coleco" to "Coleco - ColecoVision",
        "intv" to "Mattel - Intellivision",
        "dos" to "DOS", "scummvm" to "ScummVM"
    )

    // Platform keywords for filtering SteamGridDB search results
    // Maps platform ID to keywords that should appear in the game's release_date or types
    private val platformKeywords = mapOf(
        // Nintendo
        "nes" to listOf("nes", "nintendo entertainment system", "famicom"),
        "snes" to listOf("snes", "super nintendo", "super famicom", "super nes"),
        "n64" to listOf("n64", "nintendo 64"), "n64dd" to listOf("n64", "nintendo 64", "64dd"),
        "gamecube" to listOf("gamecube", "gc"), "gc" to listOf("gamecube", "gc"),
        "wii" to listOf("wii"), "wiiu" to listOf("wii u", "wiiu"),
        "switch" to listOf("switch", "nintendo switch"),
        "gb" to listOf("game boy", "gameboy"),
        "gbc" to listOf("game boy color", "gbc"),
        "gba" to listOf("game boy advance", "gba"),
        "nds" to listOf("nintendo ds", "nds", "ds"),
        "3ds" to listOf("3ds", "nintendo 3ds"), "n3ds" to listOf("3ds", "nintendo 3ds"),
        "vb" to listOf("virtual boy", "virtualboy"),
        // Sony
        "psx" to listOf("playstation", "psx", "ps1"), "ps1" to listOf("playstation", "psx", "ps1"),
        "ps2" to listOf("playstation 2", "ps2"),
        "ps3" to listOf("playstation 3", "ps3"),
        "ps4" to listOf("playstation 4", "ps4"),
        "ps5" to listOf("playstation 5", "ps5"),
        "psp" to listOf("psp", "playstation portable"),
        "psvita" to listOf("vita", "playstation vita", "psvita"), "vita" to listOf("vita", "playstation vita", "psvita"),
        // Microsoft
        "xbox" to listOf("xbox"),
        "xbox360" to listOf("xbox 360", "360"),
        "xboxone" to listOf("xbox one", "xbone"),
        "xboxseries" to listOf("xbox series", "series x", "series s"),
        // Sega
        "mastersystem" to listOf("master system", "sms"), "sms" to listOf("master system", "sms"),
        "genesis" to listOf("genesis", "mega drive", "megadrive"), "megadrive" to listOf("genesis", "mega drive", "megadrive"),
        "segacd" to listOf("sega cd", "mega cd"),
        "sega32x" to listOf("32x", "sega 32x"), "32x" to listOf("32x", "sega 32x"),
        "saturn" to listOf("saturn", "sega saturn"),
        "dreamcast" to listOf("dreamcast"), "dc" to listOf("dreamcast"),
        "gamegear" to listOf("game gear", "gamegear"), "gg" to listOf("game gear", "gamegear"),
        // Neo Geo
        "neogeo" to listOf("neo geo", "neogeo", "aes", "mvs"), "ng" to listOf("neo geo", "neogeo"),
        "neogeocd" to listOf("neo geo cd", "neogeocd"), "ngcd" to listOf("neo geo cd", "neogeocd"),
        "ngp" to listOf("neo geo pocket", "ngp"),
        "ngpc" to listOf("neo geo pocket color", "ngpc"),
        // Atari
        "atari2600" to listOf("atari 2600", "2600", "vcs"),
        "atari5200" to listOf("atari 5200", "5200"),
        "atari7800" to listOf("atari 7800", "7800"),
        "jaguar" to listOf("jaguar", "atari jaguar"),
        "lynx" to listOf("lynx", "atari lynx"),
        // Other
        "arcade" to listOf("arcade"), "mame" to listOf("mame", "arcade"), "fba" to listOf("fba", "fbneo", "arcade"),
        "tg16" to listOf("turbografx", "pc engine", "tg16", "pce"),
        "pce" to listOf("turbografx", "pc engine", "tg16", "pce"),
        "tgcd" to listOf("turbografx cd", "pc engine cd", "tgcd"),
        "pcecd" to listOf("turbografx cd", "pc engine cd", "pcecd"),
        "ws" to listOf("wonderswan"),
        "wsc" to listOf("wonderswan color"),
        "coleco" to listOf("colecovision", "coleco"),
        "intv" to listOf("intellivision"),
        "pc" to listOf("pc", "windows"),
        "dos" to listOf("dos", "dosbox"),
        "scummvm" to listOf("scummvm")
    )

    fun setSteamGridDBApiKey(key: String) {
        sgdbApiKey = key
    }

    // ==================== Game Search (for manual game selection) ====================

    /**
     * Search for games by name using SteamGridDB autocomplete.
     * Returns a list of matching games that the user can select from.
     * This is used in the iiSU Browser to let users manually search and pick the correct game.
     */
    suspend fun searchGames(query: String): List<GameSearchResult> = withContext(Dispatchers.IO) {
        // Check if query is a SteamGridDB URL or ID
        val sgdbId = extractSteamGridDBId(query)
        if (sgdbId != null) {
            Log.d(TAG, "Query appears to be SteamGridDB ID: $sgdbId")
            val game = getGameById(sgdbId)
            return@withContext if (game != null) listOf(game) else emptyList()
        }

        // Otherwise, perform name search
        searchGamesByName(query)
    }

    /**
     * Extract SteamGridDB game ID from a URL or direct ID input.
     * Supports formats:
     * - https://www.steamgriddb.com/game/12345
     * - www.steamgriddb.com/game/12345
     * - steamgriddb.com/game/12345
     * - 12345 (direct ID)
     * Returns null if the input doesn't match any supported format.
     */
    private fun extractSteamGridDBId(input: String): Int? {
        val trimmed = input.trim()

        // Try to parse as direct number
        trimmed.toIntOrNull()?.let { return it }

        // Try to extract from URL patterns
        val urlPatterns = listOf(
            Regex("""(?:https?://)?(?:www\.)?steamgriddb\.com/game/(\d+)""", RegexOption.IGNORE_CASE),
            Regex("""sgdb[:/](\d+)""", RegexOption.IGNORE_CASE)  // shorthand like "sgdb:12345"
        )

        for (pattern in urlPatterns) {
            pattern.find(trimmed)?.let { match ->
                return match.groupValues[1].toIntOrNull()
            }
        }

        return null
    }

    /**
     * Get game info by SteamGridDB game ID.
     * Returns a GameSearchResult if found, null otherwise.
     */
    suspend fun getGameById(sgdbId: Int): GameSearchResult? = withContext(Dispatchers.IO) {
        val apiKey = sgdbApiKey ?: return@withContext null

        try {
            val url = "$SGDB_BASE_URL/games/id/$sgdbId"
            val response = httpGetWithAuth(url, apiKey, SGDB_TIMEOUT) ?: return@withContext null

            val json = JSONObject(response)
            if (!json.optBoolean("success", false)) return@withContext null

            val data = json.optJSONObject("data") ?: return@withContext null

            val id = data.getInt("id")
            val name = data.getString("name")

            // Parse release year from release_date (Unix timestamp)
            val releaseDate = data.optLong("release_date", 0)
            val releaseYear = if (releaseDate > 0) {
                try {
                    java.util.Calendar.getInstance().apply {
                        timeInMillis = releaseDate * 1000
                    }.get(java.util.Calendar.YEAR)
                } catch (e: Exception) {
                    null
                }
            } else null

            // Parse types array
            val typesArray = data.optJSONArray("types")
            val types = mutableListOf<String>()
            if (typesArray != null) {
                for (j in 0 until typesArray.length()) {
                    types.add(typesArray.getString(j))
                }
            }

            Log.d(TAG, "Found game by ID $sgdbId: $name")
            GameSearchResult(id, name, releaseYear, types)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to get game by ID $sgdbId: ${e.message}")
            null
        }
    }

    /**
     * Search for games by name using SteamGridDB autocomplete.
     */
    private suspend fun searchGamesByName(query: String): List<GameSearchResult> = withContext(Dispatchers.IO) {
        val results = mutableListOf<GameSearchResult>()
        val apiKey = sgdbApiKey ?: return@withContext results

        try {
            val searchUrl = "$SGDB_BASE_URL/search/autocomplete/${URLEncoder.encode(query, "UTF-8")}"
            val response = httpGetWithAuth(searchUrl, apiKey, SGDB_TIMEOUT) ?: return@withContext results

            val json = JSONObject(response)
            if (!json.optBoolean("success", false)) return@withContext results

            val data = json.optJSONArray("data") ?: return@withContext results

            for (i in 0 until data.length()) {
                val game = data.getJSONObject(i)
                val id = game.getInt("id")
                val name = game.getString("name")

                // Parse release year from release_date (Unix timestamp)
                val releaseDate = game.optLong("release_date", 0)
                val releaseYear = if (releaseDate > 0) {
                    try {
                        java.util.Calendar.getInstance().apply {
                            timeInMillis = releaseDate * 1000
                        }.get(java.util.Calendar.YEAR)
                    } catch (e: Exception) {
                        null
                    }
                } else null

                // Parse types array
                val typesArray = game.optJSONArray("types")
                val types = mutableListOf<String>()
                if (typesArray != null) {
                    for (j in 0 until typesArray.length()) {
                        types.add(typesArray.getString(j))
                    }
                }

                results.add(GameSearchResult(id, name, releaseYear, types))
            }

            Log.d(TAG, "Found ${results.size} games for '$query'")
        } catch (e: Exception) {
            Log.w(TAG, "Game search failed: ${e.message}")
        }

        results
    }

    // ==================== Search by SteamGridDB Game ID ====================

    /**
     * Search for icon options using a known SteamGridDB game ID.
     * Use this when user has manually selected a game from search results.
     * @param squareOnly When true, only returns square images. When false, returns all images
     *                   and non-square images should be cropped using ImageCropActivity.
     */
    @Suppress("UNUSED_PARAMETER")
    suspend fun searchIconOptionsByGameId(sgdbGameId: Int, game: GameInfo, platform: String, squareOnly: Boolean = true): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching icon options by SGDB ID $sgdbGameId for: ${game.displayName} (squareOnly: $squareOnly)")

        val options = mutableListOf<ArtworkOption>()

        // Load current icon if exists
        val currentImage = game.iconFile?.let { loadBitmapFromFile(it) }

        // Get icons from SteamGridDB using the specific game ID
        try {
            val sgdbOptions = getSteamGridDBIconOptionsByGameId(sgdbGameId, squareOnly)
            options.addAll(sgdbOptions)
            Log.d(TAG, "SteamGridDB returned ${sgdbOptions.size} icon options for game ID $sgdbGameId")
        } catch (e: Exception) {
            Log.w(TAG, "SteamGridDB icon search failed: ${e.message}")
        }

        Log.d(TAG, "Found ${options.size} icon options for ${game.displayName} (by ID)")

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Search for hero options using a known SteamGridDB game ID.
     */
    suspend fun searchHeroOptionsByGameId(sgdbGameId: Int, game: GameInfo): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching hero options by SGDB ID $sgdbGameId for: ${game.displayName}")

        val options = mutableListOf<ArtworkOption>()

        // Load current hero if exists
        val currentImage = (findAssetFile(game.folder, "hero")
            ?: findExternalHeroFile(game.folder))?.let { loadBitmapFromFile(it) }

        try {
            val heroOptions = getSteamGridDBHeroOptionsByGameId(sgdbGameId)
            options.addAll(heroOptions)
            Log.d(TAG, "SteamGridDB returned ${heroOptions.size} hero options for game ID $sgdbGameId")
        } catch (e: Exception) {
            Log.w(TAG, "SteamGridDB hero search failed: ${e.message}")
        }

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Search for logo options using a known SteamGridDB game ID.
     */
    suspend fun searchLogoOptionsByGameId(sgdbGameId: Int, game: GameInfo): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching logo options by SGDB ID $sgdbGameId for: ${game.displayName}")

        val options = mutableListOf<ArtworkOption>()

        // Load current logo if exists
        val currentImage = (findAssetFile(game.folder, "logo")
            ?: findAssetFile(game.folder, "title"))?.let { loadBitmapFromFile(it) }

        // Check if logo scraping is enabled
        if (!SettingsFragment.isScrapeLogosEnabled(context)) {
            Log.d(TAG, "Logo scraping disabled in settings")
            return@withContext ArtworkSearchResult(
                gameName = game.displayName,
                options = emptyList(),
                currentImage = currentImage
            )
        }

        try {
            val logoOptions = getSteamGridDBLogoOptionsByGameId(sgdbGameId)
            options.addAll(logoOptions)
            Log.d(TAG, "SteamGridDB returned ${logoOptions.size} logo options for game ID $sgdbGameId")
        } catch (e: Exception) {
            Log.w(TAG, "SteamGridDB logo search failed: ${e.message}")
        }

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Get icon options directly from SteamGridDB using a game ID.
     * @param squareOnly When true, only returns square (1024x1024, 512x512) images.
     *                   When false, returns all grid images including non-square.
     */
    private fun getSteamGridDBIconOptionsByGameId(gameId: Int, squareOnly: Boolean = true): List<ArtworkOption> {
        val apiKey = sgdbApiKey ?: return emptyList()

        // When squareOnly is true, filter to square dimensions. Otherwise get all dimensions.
        val dimensionsParam = if (squareOnly) {
            "dimensions=1024x1024,512x512"
        } else {
            "" // No dimension filter - get all available
        }

        val gridsUrl = if (dimensionsParam.isNotEmpty()) {
            "$SGDB_BASE_URL/grids/game/$gameId?$dimensionsParam&types=static&limit=20"
        } else {
            "$SGDB_BASE_URL/grids/game/$gameId?types=static&limit=20"
        }
        val gridsResponse = httpGetWithAuth(gridsUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val gridsJson = JSONObject(gridsResponse)
        if (!gridsJson.optBoolean("success", false)) return emptyList()

        val grids = gridsJson.optJSONArray("data") ?: return emptyList()
        val options = mutableListOf<ArtworkOption>()

        for (i in 0 until grids.length()) {
            val grid = grids.getJSONObject(i)
            val imageUrl = grid.getString("url")
            val thumbUrl = grid.optString("thumb", imageUrl)
            val width = grid.optInt("width", 0)
            val height = grid.optInt("height", 0)
            val thumbnail = if (squareOnly || (width > 0 && width == height)) {
                downloadThumbnail(thumbUrl)
            } else {
                downloadThumbnailPreserveAspect(thumbUrl)
            }

            options.add(ArtworkOption(
                url = imageUrl,
                source = "SteamGridDB",
                thumbnail = thumbnail,
                width = width,
                height = height
            ))
        }

        return options
    }

    /**
     * Get hero options directly from SteamGridDB using a game ID.
     */
    private fun getSteamGridDBHeroOptionsByGameId(gameId: Int): List<ArtworkOption> {
        val apiKey = sgdbApiKey ?: return emptyList()

        val heroesUrl = "$SGDB_BASE_URL/heroes/game/$gameId?types=static&limit=10"
        val heroesResponse = httpGetWithAuth(heroesUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val heroesJson = JSONObject(heroesResponse)
        if (!heroesJson.optBoolean("success", false)) return emptyList()

        val heroes = heroesJson.optJSONArray("data") ?: return emptyList()
        val options = mutableListOf<ArtworkOption>()

        for (i in 0 until heroes.length()) {
            val hero = heroes.getJSONObject(i)
            val imageUrl = hero.getString("url")
            val thumbUrl = hero.optString("thumb", imageUrl)
            val width = hero.optInt("width", 0)
            val height = hero.optInt("height", 0)
            val thumbnail = downloadThumbnailPreserveAspect(thumbUrl)

            options.add(ArtworkOption(
                url = imageUrl,
                source = "SteamGridDB",
                thumbnail = thumbnail,
                width = width,
                height = height
            ))
        }

        return options
    }

    /**
     * Get logo options directly from SteamGridDB using a game ID.
     */
    private fun getSteamGridDBLogoOptionsByGameId(gameId: Int): List<ArtworkOption> {
        val apiKey = sgdbApiKey ?: return emptyList()

        val logosUrl = "$SGDB_BASE_URL/logos/game/$gameId?types=static&limit=10"
        val logosResponse = httpGetWithAuth(logosUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val logosJson = JSONObject(logosResponse)
        if (!logosJson.optBoolean("success", false)) return emptyList()

        val logos = logosJson.optJSONArray("data") ?: return emptyList()
        val options = mutableListOf<ArtworkOption>()

        for (i in 0 until logos.length()) {
            val logo = logos.getJSONObject(i)
            val imageUrl = logo.getString("url")
            val thumbUrl = logo.optString("thumb", imageUrl)
            val width = logo.optInt("width", 0)
            val height = logo.optInt("height", 0)
            val thumbnail = downloadThumbnailPreserveAspect(thumbUrl)

            options.add(ArtworkOption(
                url = imageUrl,
                source = "SteamGridDB",
                thumbnail = thumbnail,
                width = width,
                height = height
            ))
        }

        return options
    }

    // ==================== Interactive Mode - Search for Options ====================

    /**
     * Search for icon options from all sources. Returns multiple options for user selection.
     * Respects source priority ordering from settings.
     * Uses search variants to improve matching when initial search fails.
     * @param squareOnly When true, only returns square images. When false, returns all images
     *                   and non-square images should be cropped using ImageCropActivity.
     */
    suspend fun searchIconOptions(game: GameInfo, platform: String, squareOnly: Boolean = true): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching icon options for: ${game.name} -> ${game.searchName} (platform: $platform, squareOnly: $squareOnly)")

        val options = mutableListOf<ArtworkOption>()

        // Load current icon if exists
        val currentImage = game.iconFile?.let { loadBitmapFromFile(it) }

        // Get search variants for better matching
        val searchVariants = TitleCleaner.getSearchVariants(game.searchName)
        Log.d(TAG, "Using search variants: $searchVariants")

        // Get enabled sources in priority order
        val enabledSources = SettingsFragment.getEnabledSources(context)
        Log.d(TAG, "Using ${enabledSources.size} enabled sources: ${enabledSources.map { it.id }}")

        // Try sources in priority order
        for (source in enabledSources) {
            try {
                var sourceOptions = emptyList<ArtworkOption>()

                // Try each search variant until we get results
                for (variant in searchVariants) {
                    sourceOptions = when (source.id) {
                        "steamgriddb" -> getSteamGridDBIconOptions(variant, platform, squareOnly)
                        "libretro" -> getLibretroIconOptions(variant, platform)
                        "thegamesdb" -> getTheGamesDBIconOptions(variant, platform)
                        "igdb" -> emptyList() // IGDB requires additional setup
                        else -> emptyList()
                    }
                    if (sourceOptions.isNotEmpty()) {
                        Log.d(TAG, "Source ${source.id} found ${sourceOptions.size} results with variant: $variant")
                        break
                    }
                }

                options.addAll(sourceOptions)
                Log.d(TAG, "Source ${source.id} returned ${sourceOptions.size} options")
            } catch (e: Exception) {
                Log.w(TAG, "${source.displayName} search failed: ${e.message}")
            }
        }

        Log.d(TAG, "Found ${options.size} icon options for ${game.displayName}")

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Download and save a selected artwork option as an icon with iiSU border.
     * Uses export format settings (PNG/JPEG) from preferences.
     * Supports custom border when enabled in settings.
     */
    suspend fun saveIconFromOption(option: ArtworkOption, game: GameInfo, platform: String = ""): Boolean = withContext(Dispatchers.IO) {
        try {
            val bitmap = downloadBitmap(option.url) ?: return@withContext false

            // Check for custom border setting
            val customBorderPath = SettingsFragment.getCustomBorderPath(context)

            // Apply iiSU border if platform is provided
            val finalBitmap = if (platform.isNotEmpty()) {
                iconGenerator.generateIconWithBorder(bitmap, platform, ICON_SIZE, Pair(0.5f, 0.5f), customBorderPath) ?: run {
                    Log.w(TAG, "Border generation failed, using plain icon")
                    resizeToSquare(bitmap, ICON_SIZE)
                }
            } else {
                // No platform specified, just resize
                resizeToSquare(bitmap, ICON_SIZE)
            }

            // Delete existing icon files (png and jpg) to avoid conflicts
            deleteExistingAsset(game.folder, "icon")

            // Get export format settings
            val exportFormat = SettingsFragment.getExportFormat(context)
            val jpegQuality = SettingsFragment.getJpegQuality(context)

            // Save in the configured format
            val (format, extension, quality) = if (exportFormat == "JPEG") {
                Triple(Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
            } else {
                Triple(Bitmap.CompressFormat.PNG, "png", 100)
            }

            val iconFile = File(game.folder, "icon.$extension")
            FileOutputStream(iconFile).use { out ->
                finalBitmap.compress(format, quality, out)
            }

            Log.d(TAG, "Saved icon with border to: ${iconFile.absolutePath} (format: $exportFormat)")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save icon", e)
            false
        }
    }

    // ==================== Hero Image (SteamGridDB) ====================

    /**
     * Search for hero image options from SteamGridDB.
     * Heroes are wide banner images typically 1920x620 or similar.
     * Uses search variants to improve matching when initial search fails.
     */
    suspend fun searchHeroOptions(game: GameInfo, platform: String): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching hero options for: ${game.name} -> ${game.searchName} (platform: $platform)")

        val options = mutableListOf<ArtworkOption>()

        // Load current hero if exists (check both hero.png and hero_1.jpg, etc.)
        val currentImage = (findAssetFile(game.folder, "hero")
            ?: findExternalHeroFile(game.folder))?.let { loadBitmapFromFile(it) }

        // Get search variants for better matching
        val searchVariants = TitleCleaner.getSearchVariants(game.searchName)

        try {
            // Try each search variant until we get results
            for (variant in searchVariants) {
                val heroOptions = getSteamGridDBHeroOptions(variant, platform)
                if (heroOptions.isNotEmpty()) {
                    options.addAll(heroOptions)
                    Log.d(TAG, "Found ${heroOptions.size} hero results with variant: $variant")
                    break
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "SteamGridDB hero search failed: ${e.message}")
        }

        Log.d(TAG, "Found ${options.size} hero options for ${game.displayName}")

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Download and save a selected hero image.
     * Saves as hero_1.png/jpg to match iiSU naming convention.
     * Uses export format settings from preferences.
     * Crops based on ArtworkOption.cropMode (set interactively in the picker dialog),
     * or falls back to settings-based crop if cropMode is NONE.
     */
    suspend fun saveHeroFromOption(option: ArtworkOption, game: GameInfo, heroIndex: Int = 1): Boolean = withContext(Dispatchers.IO) {
        try {
            var bitmap = downloadBitmap(option.url) ?: return@withContext false

            // Delete existing hero files only if this is hero_1 (first hero)
            if (heroIndex == 1) {
                deleteExistingAsset(game.folder, "hero")
            }

            // Apply crop based on the option's cropMode (set in the picker dialog)
            val verticalPosition = SettingsFragment.getHeroCropPosition(context)
            when (option.cropMode) {
                ArtworkOption.CropMode.CROP_LEFT -> {
                    bitmap = cropHeroToSize(bitmap, 1920, 1080, verticalPosition, 0.0f)
                    Log.d(TAG, "Cropped hero to 1920x1080 (Left)")
                }
                ArtworkOption.CropMode.CROP_CENTER -> {
                    bitmap = cropHeroToSize(bitmap, 1920, 1080, verticalPosition, 0.5f)
                    Log.d(TAG, "Cropped hero to 1920x1080 (Center)")
                }
                ArtworkOption.CropMode.CROP_RIGHT -> {
                    bitmap = cropHeroToSize(bitmap, 1920, 1080, verticalPosition, 1.0f)
                    Log.d(TAG, "Cropped hero to 1920x1080 (Right)")
                }
                ArtworkOption.CropMode.CROP_CUSTOM -> {
                    bitmap = cropHeroToSize(bitmap, 1920, 1080, verticalPosition, option.customHorizontalPosition)
                    Log.d(TAG, "Cropped hero to 1920x1080 (Custom: ${option.customHorizontalPosition})")
                }
                ArtworkOption.CropMode.NONE -> {
                    // No crop from picker — fall back to settings-based crop for non-interactive mode
                    if (SettingsFragment.isHeroCropEnabled(context)) {
                        bitmap = cropHeroToSize(bitmap, SettingsFragment.HERO_TARGET_WIDTH, SettingsFragment.HERO_TARGET_HEIGHT, verticalPosition, 0.5f)
                        Log.d(TAG, "Cropped hero to ${SettingsFragment.HERO_TARGET_WIDTH}x${SettingsFragment.HERO_TARGET_HEIGHT} (settings)")
                    }
                }
            }

            // Get export format settings
            val exportFormat = SettingsFragment.getExportFormat(context)
            val jpegQuality = SettingsFragment.getJpegQuality(context)

            val (format, extension, quality) = if (exportFormat == "JPEG") {
                Triple(Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
            } else {
                Triple(Bitmap.CompressFormat.PNG, "png", 100)
            }

            // Save as hero_N.png/jpg (iiSU naming convention)
            val heroFile = File(game.folder, "hero_$heroIndex.$extension")
            FileOutputStream(heroFile).use { out ->
                bitmap.compress(format, quality, out)
            }

            Log.d(TAG, "Saved hero to: ${heroFile.absolutePath} (format: $exportFormat)")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save hero", e)
            false
        }
    }

    /**
     * Crop a hero image to a specified target size with smart center-crop.
     * @param bitmap The source bitmap
     * @param targetWidth Target width (e.g. 1920)
     * @param targetHeight Target height (e.g. 620 for Steam hero, 1080 for Full HD)
     * @param verticalPosition 0.0 = crop from top, 0.5 = center, 1.0 = crop from bottom
     * @return Cropped and scaled bitmap at the target dimensions
     */
    private fun cropHeroToSize(bitmap: Bitmap, targetWidth: Int, targetHeight: Int, verticalPosition: Float, horizontalPosition: Float = 0.5f): Bitmap {
        val targetAspect = targetWidth.toFloat() / targetHeight

        val srcWidth = bitmap.width
        val srcHeight = bitmap.height
        val srcAspect = srcWidth.toFloat() / srcHeight

        val (cropWidth, cropHeight, cropX, cropY) = if (srcAspect > targetAspect) {
            // Source is wider than target - crop horizontally based on position
            val newWidth = (srcHeight * targetAspect).toInt()
            val maxX = srcWidth - newWidth
            val x = (maxX * horizontalPosition).toInt().coerceIn(0, maxX)
            arrayOf(newWidth, srcHeight, x, 0)
        } else {
            // Source is taller than target - crop vertically based on position
            val newHeight = (srcWidth / targetAspect).toInt()
            val maxY = srcHeight - newHeight
            val y = (maxY * verticalPosition).toInt().coerceIn(0, maxY)
            arrayOf(srcWidth, newHeight, 0, y)
        }

        // Crop the bitmap
        val cropped = Bitmap.createBitmap(bitmap, cropX, cropY, cropWidth, cropHeight)

        // Scale to exact target dimensions
        return Bitmap.createScaledBitmap(cropped, targetWidth, targetHeight, true)
    }

    /**
     * Download and save multiple hero images based on settings.
     * Uses hero count from preferences.
     */
    suspend fun saveMultipleHeroes(options: List<ArtworkOption>, game: GameInfo): Int = withContext(Dispatchers.IO) {
        val heroCount = SettingsFragment.getHeroCount(context)
        var saved = 0

        // Delete existing heroes first
        deleteExistingAsset(game.folder, "hero")

        for (i in 0 until minOf(heroCount, options.size)) {
            val success = saveHeroFromOption(options[i], game, i + 1)
            if (success) saved++
        }

        Log.d(TAG, "Saved $saved of $heroCount hero images for ${game.displayName}")
        saved
    }

    // ==================== Logo (SteamGridDB) ====================

    /**
     * Search for logo options from SteamGridDB.
     * Logos are transparent game title images.
     * If logo fallback is enabled and no logos found, falls back to boxart.
     * Uses search variants to improve matching when initial search fails.
     */
    suspend fun searchLogoOptions(game: GameInfo, platform: String): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching logo options for: ${game.name} -> ${game.searchName}")

        val options = mutableListOf<ArtworkOption>()

        // Load current logo if exists (check both logo.png and title.jpg)
        val currentImage = (findAssetFile(game.folder, "logo")
            ?: findAssetFile(game.folder, "title"))?.let { loadBitmapFromFile(it) }

        // Check if logo scraping is enabled
        if (!SettingsFragment.isScrapeLogosEnabled(context)) {
            Log.d(TAG, "Logo scraping disabled in settings")
            return@withContext ArtworkSearchResult(
                gameName = game.displayName,
                options = emptyList(),
                currentImage = currentImage
            )
        }

        // Get search variants for better matching
        val searchVariants = TitleCleaner.getSearchVariants(game.searchName)

        // Try SteamGridDB logos first (primary source for logos)
        try {
            // Try each search variant until we get results
            for (variant in searchVariants) {
                val logoOptions = getSteamGridDBLogoOptions(variant, platform)
                if (logoOptions.isNotEmpty()) {
                    options.addAll(logoOptions)
                    Log.d(TAG, "Found ${logoOptions.size} logo results with variant: $variant")
                    break
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "SteamGridDB logo search failed: ${e.message}")
        }

        // If no logos found and fallback is enabled, try boxart from other sources
        if (options.isEmpty() && SettingsFragment.isLogoFallbackBoxartEnabled(context)) {
            Log.d(TAG, "No logos found, falling back to boxart")

            // Get enabled sources for boxart fallback
            val enabledSources = SettingsFragment.getEnabledSources(context)
            for (source in enabledSources) {
                try {
                    var boxartOptions = emptyList<ArtworkOption>()
                    // Try each search variant until we get results
                    for (variant in searchVariants) {
                        boxartOptions = when (source.id) {
                            "libretro" -> getLibretroIconOptions(variant, platform)
                            "thegamesdb" -> getTheGamesDBIconOptions(variant, platform)
                            else -> emptyList()
                        }
                        if (boxartOptions.isNotEmpty()) break
                    }
                    // Mark these as boxart fallback
                    boxartOptions.forEach { option ->
                        options.add(option.copy(source = "${option.source} (Boxart)"))
                    }
                    if (options.isNotEmpty()) break // Stop after finding some options
                } catch (e: Exception) {
                    Log.w(TAG, "Boxart fallback from ${source.id} failed: ${e.message}")
                }
            }
        }

        Log.d(TAG, "Found ${options.size} logo options for ${game.displayName}")

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Download and save a selected logo image.
     * Saves as title.png/jpg to match iiSU naming convention.
     * Uses export format settings from preferences.
     */
    suspend fun saveLogoFromOption(option: ArtworkOption, game: GameInfo): Boolean = withContext(Dispatchers.IO) {
        try {
            val bitmap = downloadBitmap(option.url) ?: return@withContext false

            // Delete existing logo files (logo.png, title.jpg, title.png)
            deleteExistingAsset(game.folder, "logo")

            // Get export format settings
            val exportFormat = SettingsFragment.getExportFormat(context)
            val jpegQuality = SettingsFragment.getJpegQuality(context)

            val (format, extension, quality) = if (exportFormat == "JPEG") {
                Triple(Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
            } else {
                Triple(Bitmap.CompressFormat.PNG, "png", 100)
            }

            // Save as title.png/jpg (iiSU naming convention)
            val logoFile = File(game.folder, "title.$extension")
            FileOutputStream(logoFile).use { out ->
                bitmap.compress(format, quality, out)
            }

            Log.d(TAG, "Saved logo to: ${logoFile.absolutePath} (format: $exportFormat)")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save logo", e)
            false
        }
    }

    // ==================== Auto Mode - First Match ====================

    /**
     * Scrape icon automatically (uses first available option) with border.
     * Respects skip scraping and fallback settings.
     * Always overwrites existing icons when new artwork is found.
     */
    suspend fun scrapeIcon(game: GameInfo, platform: String): Boolean = withContext(Dispatchers.IO) {
        Log.d(TAG, "scrapeIcon called for ${game.displayName} (hasIcon: ${game.hasIcon})")

        // Check if scraping is disabled
        if (SettingsFragment.isSkipScrapingEnabled(context)) {
            Log.d(TAG, "Scraping disabled, checking fallback for ${game.displayName}")
            return@withContext if (SettingsFragment.isUseFallbackEnabled(context)) {
                usePlatformFallbackIcon(game, platform)
            } else {
                false
            }
        }

        val result = searchIconOptions(game, platform)
        Log.d(TAG, "Found ${result.options.size} icon options for ${game.displayName}")

        if (result.options.isNotEmpty()) {
            Log.d(TAG, "Saving icon from option for ${game.displayName} (will overwrite if exists)")
            saveIconFromOption(result.options.first(), game, platform)
        } else if (SettingsFragment.isUseFallbackEnabled(context)) {
            // No results found, try platform fallback
            Log.d(TAG, "No icon options found, using platform fallback for ${game.displayName}")
            usePlatformFallbackIcon(game, platform)
        } else {
            Log.d(TAG, "No icon options found and fallback disabled for ${game.displayName}")
            false
        }
    }

    /**
     * Scrape hero automatically (uses first available option).
     * Respects hero enabled setting and downloads multiple heroes based on hero count.
     * Always overwrites existing heroes when new artwork is found.
     */
    suspend fun scrapeHero(game: GameInfo, platform: String): Boolean = withContext(Dispatchers.IO) {
        Log.d(TAG, "scrapeHero called for ${game.displayName} (hasHero: ${game.hasHero})")

        // Check if hero download is enabled
        if (!SettingsFragment.isHeroEnabled(context)) {
            Log.d(TAG, "Hero download disabled in settings")
            return@withContext false
        }

        val result = searchHeroOptions(game, platform)
        Log.d(TAG, "Found ${result.options.size} hero options for ${game.displayName}")

        if (result.options.isNotEmpty()) {
            Log.d(TAG, "Saving heroes for ${game.displayName} (will overwrite if exists)")
            val saved = saveMultipleHeroes(result.options, game)
            saved > 0
        } else {
            Log.d(TAG, "No hero options found for ${game.displayName}")
            false
        }
    }

    /**
     * Scrape logo automatically (uses first available option).
     * Respects logo scraping and fallback settings.
     * Always overwrites existing logos when new artwork is found.
     */
    suspend fun scrapeLogo(game: GameInfo, platform: String): Boolean = withContext(Dispatchers.IO) {
        Log.d(TAG, "scrapeLogo called for ${game.displayName} (hasLogo: ${game.hasLogo})")

        // Check if logo scraping is enabled
        if (!SettingsFragment.isScrapeLogosEnabled(context)) {
            Log.d(TAG, "Logo scraping disabled in settings")
            return@withContext false
        }

        val result = searchLogoOptions(game, platform)
        Log.d(TAG, "Found ${result.options.size} logo options for ${game.displayName}")

        if (result.options.isNotEmpty()) {
            Log.d(TAG, "Saving logo for ${game.displayName} (will overwrite if exists)")
            saveLogoFromOption(result.options.first(), game)
        } else {
            Log.d(TAG, "No logo options found for ${game.displayName}")
            false
        }
    }

    /**
     * Use platform icon as fallback when no artwork is found.
     * Tries to find a platform icon in assets/platform_icons folder.
     */
    private suspend fun usePlatformFallbackIcon(game: GameInfo, platform: String): Boolean = withContext(Dispatchers.IO) {
        try {
            // Try multiple naming conventions for platform icons
            val platformVariants = listOf(
                platform.uppercase(),
                platform.lowercase(),
                platform.replace(" ", "_"),
                platform.replace("_", " ")
            )

            var bitmap: Bitmap? = null
            for (variant in platformVariants) {
                val fallbackAssetPath = "platform_icons/$variant.png"
                try {
                    val inputStream = context.assets.open(fallbackAssetPath)
                    bitmap = BitmapFactory.decodeStream(inputStream)
                    inputStream.close()
                    if (bitmap != null) {
                        Log.d(TAG, "Found fallback icon at: $fallbackAssetPath")
                        break
                    }
                } catch (e: Exception) {
                    // Try next variant
                }
            }

            if (bitmap == null) {
                Log.w(TAG, "No fallback icon found for platform: $platform")
                return@withContext false
            }

            // Check for custom border setting
            val customBorderPath = SettingsFragment.getCustomBorderPath(context)

            // Apply iiSU border
            val finalBitmap = iconGenerator.generateIconWithBorder(bitmap, platform, ICON_SIZE, Pair(0.5f, 0.5f), customBorderPath) ?: run {
                Log.w(TAG, "Border generation failed, using plain fallback icon")
                resizeToSquare(bitmap, ICON_SIZE)
            }

            // Delete existing icon files
            deleteExistingAsset(game.folder, "icon")

            // Get export format settings
            val exportFormat = SettingsFragment.getExportFormat(context)
            val jpegQuality = SettingsFragment.getJpegQuality(context)

            val (format, extension, quality) = if (exportFormat == "JPEG") {
                Triple(Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
            } else {
                Triple(Bitmap.CompressFormat.PNG, "png", 100)
            }

            val iconFile = File(game.folder, "icon.$extension")
            FileOutputStream(iconFile).use { out ->
                finalBitmap.compress(format, quality, out)
            }

            Log.d(TAG, "Saved fallback icon to: ${iconFile.absolutePath}")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to use platform fallback icon", e)
            false
        }
    }

    // ==================== Source-specific Search Methods ====================

    private fun getLibretroIconOptions(gameName: String, platform: String): List<ArtworkOption> {
        val playlistName = libretroPlaylistMap[platform.lowercase()] ?: return emptyList()
        val encodedPlaylist = URLEncoder.encode(playlistName, "UTF-8")
        val encodedGame = URLEncoder.encode(gameName, "UTF-8")

        val url = "$LIBRETRO_BASE_URL/$encodedPlaylist/Named_Boxarts/$encodedGame.png"

        // Check if the URL is valid by trying to connect
        if (isUrlReachable(url)) {
            val thumbnail = downloadThumbnail(url)
            return listOf(ArtworkOption(
                url = url,
                source = "Libretro",
                thumbnail = thumbnail
            ))
        }
        return emptyList()
    }

    private fun getTheGamesDBIconOptions(gameName: String, platform: String): List<ArtworkOption> {
        val platformId = tgdbPlatformMap[platform.lowercase()] ?: return emptyList()

        val searchUrl = "$TGDB_BASE_URL/Games/ByGameName?" +
            "apikey=$tgdbApiKey" +
            "&name=${URLEncoder.encode(gameName, "UTF-8")}" +
            "&filter[platform]=$platformId" +
            "&include=boxart"

        val response = httpGet(searchUrl, TGDB_TIMEOUT) ?: return emptyList()

        val json = JSONObject(response)
        val data = json.optJSONObject("data") ?: return emptyList()
        val games = data.optJSONArray("games") ?: return emptyList()
        if (games.length() == 0) return emptyList()

        val options = mutableListOf<ArtworkOption>()

        // Get boxart info
        val include = json.optJSONObject("include") ?: return emptyList()
        val boxart = include.optJSONObject("boxart") ?: return emptyList()
        val thumbBaseUrl = boxart.optJSONObject("base_url")?.optString("thumb") ?: return emptyList()
        val originalBaseUrl = boxart.optJSONObject("base_url")?.optString("original") ?: thumbBaseUrl

        // Collect options from all matching games (up to 5)
        for (g in 0 until minOf(games.length(), 5)) {
            val gameData = games.getJSONObject(g)
            val gameId = gameData.getInt("id")
            val images = boxart.optJSONObject("data")?.optJSONArray(gameId.toString()) ?: continue

            for (i in 0 until images.length()) {
                val img = images.getJSONObject(i)
                val side = img.optString("side")
                if (side == "front") {
                    val filename = img.getString("filename")
                    val imageUrl = originalBaseUrl + filename
                    val thumbUrl = thumbBaseUrl + filename
                    val thumbnail = downloadThumbnail(thumbUrl)

                    options.add(ArtworkOption(
                        url = imageUrl,
                        source = "TheGamesDB",
                        thumbnail = thumbnail
                    ))
                }
            }
        }

        return options
    }

    private fun getSteamGridDBIconOptions(gameName: String, platform: String, squareOnly: Boolean = true): List<ArtworkOption> {
        val apiKey = sgdbApiKey ?: return emptyList()

        val searchUrl = "$SGDB_BASE_URL/search/autocomplete/${URLEncoder.encode(gameName, "UTF-8")}"
        val response = httpGetWithAuth(searchUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val json = JSONObject(response)
        if (!json.optBoolean("success", false)) return emptyList()

        val data = json.optJSONArray("data") ?: return emptyList()
        if (data.length() == 0) return emptyList()

        val options = mutableListOf<ArtworkOption>()

        // Find the best matching game for the platform
        val gameId = findBestMatchingGameId(data, gameName, platform)
        if (gameId == null) {
            Log.w(TAG, "No matching SGDB game found for $gameName on $platform")
            return emptyList()
        }

        // When squareOnly is true, filter to square dimensions. Otherwise get all dimensions.
        val dimensionsParam = if (squareOnly) {
            "dimensions=1024x1024,512x512"
        } else {
            "" // No dimension filter - get all available
        }

        val gridsUrl = if (dimensionsParam.isNotEmpty()) {
            "$SGDB_BASE_URL/grids/game/$gameId?$dimensionsParam&types=static&limit=20"
        } else {
            "$SGDB_BASE_URL/grids/game/$gameId?types=static&limit=20"
        }
        val gridsResponse = httpGetWithAuth(gridsUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val gridsJson = JSONObject(gridsResponse)
        if (!gridsJson.optBoolean("success", false)) return emptyList()

        val grids = gridsJson.optJSONArray("data") ?: return emptyList()

        for (i in 0 until grids.length()) {
            val grid = grids.getJSONObject(i)
            val imageUrl = grid.getString("url")
            val thumbUrl = grid.optString("thumb", imageUrl)
            val width = grid.optInt("width", 0)
            val height = grid.optInt("height", 0)
            val thumbnail = if (squareOnly || (width > 0 && width == height)) {
                downloadThumbnail(thumbUrl)
            } else {
                downloadThumbnailPreserveAspect(thumbUrl)
            }

            options.add(ArtworkOption(
                url = imageUrl,
                source = "SteamGridDB",
                thumbnail = thumbnail,
                width = width,
                height = height
            ))
        }

        return options
    }

    private fun getSteamGridDBHeroOptions(gameName: String, platform: String): List<ArtworkOption> {
        val apiKey = sgdbApiKey ?: return emptyList()

        val searchUrl = "$SGDB_BASE_URL/search/autocomplete/${URLEncoder.encode(gameName, "UTF-8")}"
        val response = httpGetWithAuth(searchUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val json = JSONObject(response)
        if (!json.optBoolean("success", false)) return emptyList()

        val data = json.optJSONArray("data") ?: return emptyList()
        if (data.length() == 0) return emptyList()

        val options = mutableListOf<ArtworkOption>()

        // Find the best matching game for the platform
        val gameId = findBestMatchingGameId(data, gameName, platform)
        if (gameId == null) {
            Log.w(TAG, "No matching SGDB game found for $gameName on $platform")
            return emptyList()
        }

        // Get hero images
        val heroesUrl = "$SGDB_BASE_URL/heroes/game/$gameId?types=static&limit=10"
        val heroesResponse = httpGetWithAuth(heroesUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val heroesJson = JSONObject(heroesResponse)
        if (!heroesJson.optBoolean("success", false)) return emptyList()

        val heroes = heroesJson.optJSONArray("data") ?: return emptyList()

        for (i in 0 until heroes.length()) {
            val hero = heroes.getJSONObject(i)
            val imageUrl = hero.getString("url")
            val thumbUrl = hero.optString("thumb", imageUrl)
            val width = hero.optInt("width", 0)
            val height = hero.optInt("height", 0)
            // Use aspect-preserving thumbnail for heroes (wide banners)
            val thumbnail = downloadThumbnailPreserveAspect(thumbUrl)

            options.add(ArtworkOption(
                url = imageUrl,
                source = "SteamGridDB",
                thumbnail = thumbnail,
                width = width,
                height = height
            ))
        }

        return options
    }

    private fun getSteamGridDBLogoOptions(gameName: String, platform: String): List<ArtworkOption> {
        val apiKey = sgdbApiKey ?: return emptyList()

        val searchUrl = "$SGDB_BASE_URL/search/autocomplete/${URLEncoder.encode(gameName, "UTF-8")}"
        val response = httpGetWithAuth(searchUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val json = JSONObject(response)
        if (!json.optBoolean("success", false)) return emptyList()

        val data = json.optJSONArray("data") ?: return emptyList()
        if (data.length() == 0) return emptyList()

        val options = mutableListOf<ArtworkOption>()

        // Find the best matching game for the platform
        val gameId = findBestMatchingGameId(data, gameName, platform)
        if (gameId == null) {
            Log.w(TAG, "No matching SGDB game found for $gameName on $platform")
            return emptyList()
        }

        // Get logo images
        val logosUrl = "$SGDB_BASE_URL/logos/game/$gameId?types=static&limit=10"
        val logosResponse = httpGetWithAuth(logosUrl, apiKey, SGDB_TIMEOUT) ?: return emptyList()

        val logosJson = JSONObject(logosResponse)
        if (!logosJson.optBoolean("success", false)) return emptyList()

        val logos = logosJson.optJSONArray("data") ?: return emptyList()

        for (i in 0 until logos.length()) {
            val logo = logos.getJSONObject(i)
            val imageUrl = logo.getString("url")
            val thumbUrl = logo.optString("thumb", imageUrl)
            val width = logo.optInt("width", 0)
            val height = logo.optInt("height", 0)
            // Use aspect-preserving thumbnail for logos (various aspect ratios)
            val thumbnail = downloadThumbnailPreserveAspect(thumbUrl)

            options.add(ArtworkOption(
                url = imageUrl,
                source = "SteamGridDB",
                thumbnail = thumbnail,
                width = width,
                height = height
            ))
        }

        return options
    }

    // ==================== IGDB Screenshot Scraping ====================

    // IGDB API configuration
    private var igdbAccessToken: String? = null
    private var igdbTokenExpiry: Long = 0

    /**
     * Get IGDB access token using Twitch OAuth2.
     * Caches the token until it expires.
     */
    private fun getIGDBAccessToken(): String? {
        // Check if we have a valid cached token
        if (igdbAccessToken != null && System.currentTimeMillis() < igdbTokenExpiry) {
            return igdbAccessToken
        }

        val clientId = SettingsFragment.getIgdbClientId(context)
        val clientSecret = SettingsFragment.getIgdbClientSecret(context)

        if (clientId.isNullOrEmpty() || clientSecret.isNullOrEmpty()) {
            Log.w(TAG, "IGDB credentials not configured")
            return null
        }

        try {
            val tokenUrl = "https://id.twitch.tv/oauth2/token"
            val postData = "client_id=$clientId&client_secret=$clientSecret&grant_type=client_credentials"

            val connection = URL(tokenUrl).openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 10000
            connection.readTimeout = 10000
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")

            connection.outputStream.use { os ->
                os.write(postData.toByteArray())
            }

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                val response = connection.inputStream.bufferedReader().readText()
                val json = JSONObject(response)
                igdbAccessToken = json.getString("access_token")
                val expiresIn = json.getLong("expires_in")
                // Set expiry 5 minutes before actual expiry for safety
                igdbTokenExpiry = System.currentTimeMillis() + (expiresIn - 300) * 1000
                Log.d(TAG, "IGDB access token obtained, expires in ${expiresIn}s")
                return igdbAccessToken
            } else {
                Log.e(TAG, "Failed to get IGDB token: ${connection.responseCode}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "IGDB OAuth failed", e)
        }

        return null
    }

    /**
     * Search IGDB for a game and get its ID.
     */
    private fun searchIGDBGame(gameName: String, platform: String): Int? {
        val accessToken = getIGDBAccessToken() ?: return null
        val clientId = SettingsFragment.getIgdbClientId(context) ?: return null

        try {
            val searchUrl = "https://api.igdb.com/v4/games"

            // Build the search query with platform filtering if possible
            val platformFilter = getIGDBPlatformId(platform)?.let {
                " & platforms = ($it)"
            } ?: ""

            val query = "search \"$gameName\"; fields id,name,screenshots; where screenshots != null$platformFilter; limit 5;"

            val connection = URL(searchUrl).openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 15000
            connection.readTimeout = 15000
            connection.setRequestProperty("Client-ID", clientId)
            connection.setRequestProperty("Authorization", "Bearer $accessToken")
            connection.setRequestProperty("Content-Type", "text/plain")

            connection.outputStream.use { os ->
                os.write(query.toByteArray())
            }

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                val response = connection.inputStream.bufferedReader().readText()
                val games = org.json.JSONArray(response)

                if (games.length() > 0) {
                    // Return the first game with screenshots
                    for (i in 0 until games.length()) {
                        val game = games.getJSONObject(i)
                        val screenshots = game.optJSONArray("screenshots")
                        if (screenshots != null && screenshots.length() > 0) {
                            Log.d(TAG, "Found IGDB game: ${game.optString("name")} with ${screenshots.length()} screenshots")
                            return game.getInt("id")
                        }
                    }
                }
            } else {
                Log.e(TAG, "IGDB search failed: ${connection.responseCode}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "IGDB search error", e)
        }

        return null
    }

    /**
     * Get screenshots for a game from IGDB.
     */
    private fun getIGDBScreenshotOptions(gameName: String, platform: String): List<ArtworkOption> {
        val accessToken = getIGDBAccessToken() ?: return emptyList()
        val clientId = SettingsFragment.getIgdbClientId(context) ?: return emptyList()

        try {
            // First search for the game
            val searchUrl = "https://api.igdb.com/v4/games"

            val platformFilter = getIGDBPlatformId(platform)?.let {
                " & platforms = ($it)"
            } ?: ""

            val query = "search \"$gameName\"; fields id,name,screenshots; where screenshots != null$platformFilter; limit 1;"

            var connection = URL(searchUrl).openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 15000
            connection.readTimeout = 15000
            connection.setRequestProperty("Client-ID", clientId)
            connection.setRequestProperty("Authorization", "Bearer $accessToken")
            connection.setRequestProperty("Content-Type", "text/plain")

            connection.outputStream.use { os ->
                os.write(query.toByteArray())
            }

            if (connection.responseCode != HttpURLConnection.HTTP_OK) {
                Log.e(TAG, "IGDB game search failed: ${connection.responseCode}")
                return emptyList()
            }

            val gamesResponse = connection.inputStream.bufferedReader().readText()
            val games = org.json.JSONArray(gamesResponse)

            if (games.length() == 0) {
                Log.d(TAG, "No IGDB games found for: $gameName")
                return emptyList()
            }

            val game = games.getJSONObject(0)
            val screenshotIds = game.optJSONArray("screenshots") ?: return emptyList()

            if (screenshotIds.length() == 0) {
                return emptyList()
            }

            // Build list of screenshot IDs
            val ids = StringBuilder()
            for (i in 0 until screenshotIds.length()) {
                if (i > 0) ids.append(",")
                ids.append(screenshotIds.getInt(i))
            }

            // Fetch screenshot details
            val screenshotsUrl = "https://api.igdb.com/v4/screenshots"
            val screenshotQuery = "fields url,width,height; where id = ($ids); limit 10;"

            connection = URL(screenshotsUrl).openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 15000
            connection.readTimeout = 15000
            connection.setRequestProperty("Client-ID", clientId)
            connection.setRequestProperty("Authorization", "Bearer $accessToken")
            connection.setRequestProperty("Content-Type", "text/plain")

            connection.outputStream.use { os ->
                os.write(screenshotQuery.toByteArray())
            }

            if (connection.responseCode != HttpURLConnection.HTTP_OK) {
                Log.e(TAG, "IGDB screenshots fetch failed: ${connection.responseCode}")
                return emptyList()
            }

            val screenshotsResponse = connection.inputStream.bufferedReader().readText()
            val screenshots = org.json.JSONArray(screenshotsResponse)

            val options = mutableListOf<ArtworkOption>()

            for (i in 0 until screenshots.length()) {
                val screenshot = screenshots.getJSONObject(i)
                // IGDB returns URLs like //images.igdb.com/igdb/image/upload/t_thumb/xxx.jpg
                // We need to add https: and change the size
                var imageUrl = screenshot.optString("url", "")
                if (imageUrl.startsWith("//")) {
                    imageUrl = "https:$imageUrl"
                }
                // Change thumbnail size to full 1080p
                val fullUrl = imageUrl.replace("t_thumb", "t_1080p")
                val thumbUrl = imageUrl.replace("t_thumb", "t_screenshot_med")

                val width = screenshot.optInt("width", 0)
                val height = screenshot.optInt("height", 0)
                // Use aspect-preserving thumbnail for screenshots (wide images)
                val thumbnail = downloadThumbnailPreserveAspect(thumbUrl)

                options.add(ArtworkOption(
                    url = fullUrl,
                    source = "IGDB",
                    thumbnail = thumbnail,
                    width = width,
                    height = height
                ))
            }

            Log.d(TAG, "Found ${options.size} IGDB screenshots for: $gameName")
            return options

        } catch (e: Exception) {
            Log.e(TAG, "IGDB screenshot fetch error", e)
        }

        return emptyList()
    }

    /**
     * Map platform names to IGDB platform IDs.
     */
    private fun getIGDBPlatformId(platform: String): Int? {
        return when (platform.lowercase()) {
            // Nintendo
            "nes" -> 18
            "snes" -> 19
            "n64" -> 4
            "gamecube", "gc" -> 21
            "wii" -> 5
            "wiiu" -> 41
            "switch" -> 130
            "gb" -> 33
            "gbc" -> 22
            "gba" -> 24
            "nds" -> 20
            "3ds", "n3ds" -> 37
            // Sony
            "psx", "ps1" -> 7
            "ps2" -> 8
            "ps3" -> 9
            "ps4" -> 48
            "ps5" -> 167
            "psp" -> 38
            "psvita" -> 46
            // Sega
            "mastersystem" -> 64
            "genesis", "megadrive" -> 29
            "segacd" -> 78
            "sega32x" -> 30
            "saturn" -> 32
            "dreamcast" -> 23
            "gamegear" -> 35
            // Microsoft
            "xbox" -> 11
            "xbox360" -> 12
            else -> null
        }
    }

    // ==================== Screenshot Scraping ====================

    /**
     * Search for screenshot options from multiple sources.
     * Tries IGDB first (best quality and quantity), then Libretro as fallback.
     * Uses search variants to improve matching when initial search fails.
     */
    suspend fun searchScreenshotOptions(game: GameInfo, platform: String): ArtworkSearchResult = withContext(Dispatchers.IO) {
        Log.d(TAG, "Searching screenshot options for: ${game.name} -> ${game.searchName} (platform: $platform)")

        val options = mutableListOf<ArtworkOption>()

        // Load current screenshot if exists
        val currentImage = findScreenshotFile(game.folder)?.let { loadBitmapFromFile(it) }

        // Get search variants for better matching
        val searchVariants = TitleCleaner.getSearchVariants(game.searchName)

        // Try IGDB screenshots first (best quality and most screenshots per game)
        try {
            for (variant in searchVariants) {
                val igdbOptions = getIGDBScreenshotOptions(variant, platform)
                if (igdbOptions.isNotEmpty()) {
                    options.addAll(igdbOptions)
                    Log.d(TAG, "Found ${igdbOptions.size} IGDB screenshot results with variant: $variant")
                    break
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "IGDB screenshot search failed: ${e.message}")
        }

        // Try Libretro screenshots as fallback (only has 1 screenshot per game)
        if (options.isEmpty()) {
            try {
                for (variant in searchVariants) {
                    val libretroOptions = getLibretroScreenshotOptions(variant, platform)
                    if (libretroOptions.isNotEmpty()) {
                        options.addAll(libretroOptions)
                        Log.d(TAG, "Found ${libretroOptions.size} Libretro screenshot results with variant: $variant")
                        break
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Libretro screenshot search failed: ${e.message}")
            }
        }

        Log.d(TAG, "Found ${options.size} screenshot options for ${game.displayName}")

        ArtworkSearchResult(
            gameName = game.displayName,
            options = options,
            currentImage = currentImage
        )
    }

    /**
     * Download and save screenshots.
     * Saves as slide_1.png/jpg, slide_2.png/jpg, etc. (iiSU naming convention)
     */
    suspend fun saveScreenshotFromOption(option: ArtworkOption, game: GameInfo, slideIndex: Int = 1): Boolean = withContext(Dispatchers.IO) {
        try {
            val bitmap = downloadBitmap(option.url) ?: return@withContext false

            // Get export format settings
            val exportFormat = SettingsFragment.getExportFormat(context)
            val jpegQuality = SettingsFragment.getJpegQuality(context)

            val (format, extension, quality) = if (exportFormat == "JPEG") {
                Triple(Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
            } else {
                Triple(Bitmap.CompressFormat.PNG, "png", 100)
            }

            // Save as slide_N.png/jpg (iiSU naming convention)
            val screenshotFile = File(game.folder, "slide_$slideIndex.$extension")
            FileOutputStream(screenshotFile).use { out ->
                bitmap.compress(format, quality, out)
            }

            Log.d(TAG, "Saved screenshot to: ${screenshotFile.absolutePath} (format: $exportFormat)")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save screenshot", e)
            false
        }
    }

    /**
     * Scrape screenshots automatically.
     * Downloads up to screenshotCount screenshots (from settings).
     */
    suspend fun scrapeScreenshots(game: GameInfo, platform: String): Boolean = withContext(Dispatchers.IO) {
        Log.d(TAG, "scrapeScreenshots called for ${game.displayName}")

        // Check if screenshot scraping is enabled
        if (!SettingsFragment.isScreenshotsEnabled(context)) {
            Log.d(TAG, "Screenshot scraping disabled in settings")
            return@withContext false
        }

        val screenshotCount = SettingsFragment.getScreenshotCount(context)
        val result = searchScreenshotOptions(game, platform)
        Log.d(TAG, "Found ${result.options.size} screenshot options for ${game.displayName}")

        if (result.options.isEmpty()) {
            Log.d(TAG, "No screenshot options found for ${game.displayName}")
            return@withContext false
        }

        // Delete existing screenshots first
        deleteExistingScreenshots(game.folder)

        var saved = 0
        for (i in 0 until minOf(screenshotCount, result.options.size)) {
            val success = saveScreenshotFromOption(result.options[i], game, i + 1)
            if (success) saved++
        }

        Log.d(TAG, "Saved $saved of $screenshotCount screenshots for ${game.displayName}")
        saved > 0
    }

    private fun getLibretroScreenshotOptions(gameName: String, platform: String): List<ArtworkOption> {
        val playlistName = libretroPlaylistMap[platform.lowercase()] ?: return emptyList()
        val encodedPlaylist = URLEncoder.encode(playlistName, "UTF-8")
        val encodedGame = URLEncoder.encode(gameName, "UTF-8")

        val options = mutableListOf<ArtworkOption>()

        // Libretro has "Named_Snaps" folder for screenshots
        val baseUrl = "$LIBRETRO_BASE_URL/$encodedPlaylist/Named_Snaps/$encodedGame.png"

        // Check if the URL is valid by trying to connect
        if (isUrlReachable(baseUrl)) {
            val thumbnail = downloadThumbnail(baseUrl)
            options.add(ArtworkOption(
                url = baseUrl,
                source = "Libretro",
                thumbnail = thumbnail
            ))
        }

        return options
    }

    private fun findScreenshotFile(folder: File): File? {
        val extensions = listOf("png", "jpg", "jpeg")
        for (i in 1..10) {
            for (ext in extensions) {
                val file = File(folder, "slide_$i.$ext")
                if (file.exists()) return file
            }
        }
        return null
    }

    private fun deleteExistingScreenshots(folder: File) {
        val extensions = listOf("png", "jpg", "jpeg")
        for (i in 1..10) {
            extensions.forEach { ext ->
                val file = File(folder, "slide_$i.$ext")
                if (file.exists()) {
                    val deleted = file.delete()
                    Log.d(TAG, "Deleting ${file.name}: $deleted")
                }
            }
        }
    }

    // ==================== Helper Methods ====================

    /**
     * Find the best matching game ID from SteamGridDB search results.
     * Uses string similarity scoring to find the closest match.
     */
    @Suppress("UNUSED_PARAMETER")
    private fun findBestMatchingGameId(data: org.json.JSONArray, gameName: String, platform: String): Int? {
        val normalizedQuery = normalizeForMatching(gameName)
        var bestMatchId: Int? = null
        var bestScore = 0.0

        for (i in 0 until data.length()) {
            val gameResult = data.getJSONObject(i)
            val resultName = gameResult.optString("name", "")
            val gameId = gameResult.getInt("id")

            val normalizedName = normalizeForMatching(resultName)
            val score = calculateMatchScore(normalizedQuery, normalizedName)

            Log.d(TAG, "Match score for '$resultName': $score (normalized: '$normalizedName' vs '$normalizedQuery')")

            if (score > bestScore) {
                bestScore = score
                bestMatchId = gameId
            }

            // Perfect match - no need to continue
            if (score >= 1.0) break
        }

        if (bestMatchId != null) {
            Log.d(TAG, "Best match for '$gameName': ID $bestMatchId with score $bestScore")
        } else {
            Log.w(TAG, "No matching game found for '$gameName'")
        }

        return bestMatchId
    }

    /**
     * Normalize game name for comparison by removing special characters and normalizing spaces.
     * Handles accented characters by converting them to their ASCII equivalents.
     * Handles sorted titles like "Legend of Zelda, The" -> "The Legend of Zelda"
     */
    private fun normalizeForMatching(name: String): String {
        // First, handle "Name, The/A/An" format by moving article to the front
        var result = name.trim()
        when {
            result.endsWith(", The", ignoreCase = true) -> {
                result = "The " + result.dropLast(5)
            }
            result.endsWith(", A", ignoreCase = true) -> {
                result = "A " + result.dropLast(3)
            }
            result.endsWith(", An", ignoreCase = true) -> {
                result = "An " + result.dropLast(4)
            }
        }

        // Normalize accented characters to ASCII equivalents
        val normalized = java.text.Normalizer.normalize(result, java.text.Normalizer.Form.NFD)
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

        // Game name starts with the query (high priority)
        // e.g., "pokemon moon" matches "pokemon moon" better than "pokemon moon black 2"
        if (gameName.startsWith(query)) {
            // Penalize longer names that just happen to start with the query
            val extraLength = gameName.length - query.length
            // Small penalty for each extra character
            return (0.95 - (extraLength * 0.02)).coerceAtLeast(0.5)
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

    /**
     * Normalize game name for searching by using TitleCleaner.
     * Removes region tags, version info, dump info, etc.
     */
    @Suppress("unused")
    private fun normalizeGameName(name: String): String {
        return TitleCleaner.normalizeForSearch(name)
    }

    /**
     * Delete existing asset files, including both app-generated and external iiSU naming conventions.
     *
     * iiSU naming convention:
     * - icon: icon.png/jpg
     * - hero: hero_1.png/jpg, hero_2.png/jpg, etc.
     * - logo: title.png/jpg
     *
     * Legacy app naming (for cleanup):
     * - hero: hero.png
     * - logo: logo.png
     */
    private fun deleteExistingAsset(folder: File, baseName: String) {
        val extensions = listOf("png", "jpg", "jpeg")

        // Delete standard named files (icon.png, icon.jpg, etc.)
        extensions.forEach { ext ->
            val file = File(folder, "$baseName.$ext")
            if (file.exists()) {
                val deleted = file.delete()
                Log.d(TAG, "Deleting ${file.name}: $deleted")
            }
        }

        // Handle special naming conventions
        when (baseName) {
            "hero" -> {
                // Delete hero files: hero_1.png/jpg, hero_2.png/jpg, etc.
                for (i in 1..10) {
                    extensions.forEach { ext ->
                        val file = File(folder, "hero_$i.$ext")
                        if (file.exists()) {
                            val deleted = file.delete()
                            Log.d(TAG, "Deleting ${file.name}: $deleted")
                        }
                    }
                }
            }
            "logo" -> {
                // Delete title files: title.png, title.jpg (iiSU convention)
                extensions.forEach { ext ->
                    val file = File(folder, "title.$ext")
                    if (file.exists()) {
                        val deleted = file.delete()
                        Log.d(TAG, "Deleting ${file.name}: $deleted")
                    }
                }
            }
        }
    }

    private fun findAssetFile(folder: File, baseName: String): File? {
        val extensions = listOf("png", "jpg", "jpeg")
        for (ext in extensions) {
            val file = File(folder, "$baseName.$ext")
            if (file.exists()) return file
        }
        return null
    }

    /**
     * Find external hero file (hero_1.jpg, hero_2.jpg, etc.).
     */
    private fun findExternalHeroFile(folder: File): File? {
        val extensions = listOf("jpg", "jpeg", "png")
        for (i in 1..10) {
            for (ext in extensions) {
                val file = File(folder, "hero_$i.$ext")
                if (file.exists()) return file
            }
        }
        return null
    }

    private fun loadBitmapFromFile(file: File): Bitmap? {
        return try {
            BitmapFactory.decodeFile(file.absolutePath)
        } catch (e: Exception) {
            null
        }
    }

    private fun isUrlReachable(url: String): Boolean {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.requestMethod = "HEAD"
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")
            connection.responseCode == HttpURLConnection.HTTP_OK
        } catch (e: Exception) {
            false
        }
    }

    private fun downloadThumbnail(url: String): Bitmap? {
        return try {
            val bitmap = downloadBitmap(url) ?: return null
            resizeToSquare(bitmap, THUMBNAIL_SIZE)
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Download thumbnail preserving aspect ratio (for heroes, logos, screenshots).
     * Scales down to fit within maxSize while maintaining proportions.
     */
    private fun downloadThumbnailPreserveAspect(url: String, maxSize: Int = THUMBNAIL_SIZE * 2): Bitmap? {
        return try {
            val bitmap = downloadBitmap(url) ?: return null
            resizePreserveAspect(bitmap, maxSize)
        } catch (e: Exception) {
            null
        }
    }

    private fun resizePreserveAspect(bitmap: Bitmap, maxSize: Int): Bitmap {
        val width = bitmap.width
        val height = bitmap.height
        val maxDim = maxOf(width, height)

        if (maxDim <= maxSize) {
            return bitmap // Already small enough
        }

        val scale = maxSize.toFloat() / maxDim
        val newWidth = (width * scale).toInt()
        val newHeight = (height * scale).toInt()

        return Bitmap.createScaledBitmap(bitmap, newWidth, newHeight, true)
    }

    private fun downloadBitmap(url: String): Bitmap? {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = 30000
            connection.readTimeout = 30000
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")

            if (connection.responseCode == HttpURLConnection.HTTP_OK) {
                BitmapFactory.decodeStream(connection.inputStream)
            } else null
        } catch (e: Exception) {
            Log.e(TAG, "Failed to download: $url", e)
            null
        }
    }

    private fun resizeToSquare(bitmap: Bitmap, size: Int): Bitmap {
        val minDim = minOf(bitmap.width, bitmap.height)
        val x = (bitmap.width - minDim) / 2
        val y = (bitmap.height - minDim) / 2
        val cropped = Bitmap.createBitmap(bitmap, x, y, minDim, minDim)
        return Bitmap.createScaledBitmap(cropped, size, size, true)
    }

    private fun httpGet(url: String, timeout: Int): String? {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = timeout
            connection.readTimeout = timeout
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

    private fun httpGetWithAuth(url: String, apiKey: String, timeout: Int): String? {
        return try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = timeout
            connection.readTimeout = timeout
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
}
