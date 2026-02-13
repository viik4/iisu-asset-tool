package com.iisu.assettool.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Client for the iiSU Asset Server (local/self-hosted backend)
 *
 * Connects to a FastAPI backend that stores assets locally.
 * Provides:
 * - Public read access to browse and download assets
 * - Public upload access (write-only, no delete)
 * - Faster access than Google Drive (no rate limiting)
 */
class AssetServerClient(
    private val serverUrl: String = "https://assets.iisu.community"
) {
    companion object {
        private const val TAG = "AssetServerClient"
        private const val CONNECT_TIMEOUT = 10_000 // 10 seconds
        private const val READ_TIMEOUT = 60_000 // 60 seconds
    }

    // Data classes
    data class Platform(
        val id: Int,
        val name: String,
        val displayName: String?,
        val gameCount: Int = 0
    )

    data class Asset(
        val id: Int,
        val assetType: String,
        val filename: String,
        val fileSize: Int,
        val mimeType: String,
        val width: Int?,
        val height: Int?,
        val downloadUrl: String,
        val thumbnailUrl: String
    )

    data class Game(
        val id: Int,
        val name: String,
        val platformName: String,
        val variantNumber: Int,
        val assetCount: Int,
        val assets: List<Asset>
    )

    data class SearchResult(
        val id: Int,
        val name: String,
        val platformName: String,
        val variantNumber: Int,
        val assetCount: Int,
        val iconUrl: String?
    )

    data class Stats(
        val platforms: Int,
        val games: Int,
        val assets: Int,
        val totalSizeMb: Double
    )

    data class UploadResult(
        val success: Boolean,
        val message: String,
        val gameId: Int?,
        val assetId: Int?
    )

    /**
     * Check if the server is available
     */
    suspend fun isAvailable(): Boolean = withContext(Dispatchers.IO) {
        try {
            val url = URL("$serverUrl/")
            val connection = url.openConnection() as HttpURLConnection
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.requestMethod = "GET"

            val responseCode = connection.responseCode
            connection.disconnect()

            responseCode == 200
        } catch (e: Exception) {
            Log.d(TAG, "Server not available: ${e.message}")
            false
        }
    }

    /**
     * Get all platforms
     */
    suspend fun getPlatforms(): List<Platform> = withContext(Dispatchers.IO) {
        try {
            val response = httpGet("$serverUrl/api/platforms")
            val jsonArray = JSONArray(response)

            val platforms = mutableListOf<Platform>()
            for (i in 0 until jsonArray.length()) {
                val obj = jsonArray.getJSONObject(i)
                platforms.add(
                    Platform(
                        id = obj.getInt("id"),
                        name = obj.getString("name"),
                        displayName = obj.optString("display_name"),
                        gameCount = obj.optInt("game_count", 0)
                    )
                )
            }
            platforms
        } catch (e: Exception) {
            Log.e(TAG, "Error getting platforms: ${e.message}")
            emptyList()
        }
    }

    /**
     * Get only platforms that have at least one game with assets.
     * Uses the /api/platforms/with-games endpoint which pre-filters empty platforms.
     */
    suspend fun getPlatformsWithGames(): List<Platform> = withContext(Dispatchers.IO) {
        try {
            val response = httpGet("$serverUrl/api/platforms/with-games")
            val jsonArray = JSONArray(response)

            val platforms = mutableListOf<Platform>()
            for (i in 0 until jsonArray.length()) {
                val obj = jsonArray.getJSONObject(i)
                platforms.add(
                    Platform(
                        id = obj.getInt("id"),
                        name = obj.getString("name"),
                        displayName = obj.optString("display_name"),
                        gameCount = obj.optInt("game_count", 0)
                    )
                )
            }
            platforms
        } catch (e: Exception) {
            Log.e(TAG, "Error getting platforms with games: ${e.message}")
            emptyList()
        }
    }

    /**
     * Get games with optional platform filter
     */
    suspend fun getGames(platform: String? = null): List<Game> = withContext(Dispatchers.IO) {
        try {
            val url = if (platform != null) {
                "$serverUrl/api/games?platform=${java.net.URLEncoder.encode(platform, "UTF-8")}"
            } else {
                "$serverUrl/api/games"
            }

            val response = httpGet(url)
            parseGamesJson(response)
        } catch (e: Exception) {
            Log.e(TAG, "Error getting games: ${e.message}")
            emptyList()
        }
    }

    /**
     * Get a specific game by ID
     */
    suspend fun getGame(gameId: Int): Game? = withContext(Dispatchers.IO) {
        try {
            val response = httpGet("$serverUrl/api/games/$gameId")
            val obj = JSONObject(response)
            parseGameJson(obj)
        } catch (e: Exception) {
            Log.e(TAG, "Error getting game: ${e.message}")
            null
        }
    }

    /**
     * Search for games
     */
    suspend fun searchGames(query: String, limit: Int = 50): List<SearchResult> = withContext(Dispatchers.IO) {
        try {
            val encodedQuery = java.net.URLEncoder.encode(query, "UTF-8")
            val response = httpGet("$serverUrl/api/search?q=$encodedQuery&limit=$limit")
            val jsonArray = JSONArray(response)

            val results = mutableListOf<SearchResult>()
            for (i in 0 until jsonArray.length()) {
                val obj = jsonArray.getJSONObject(i)
                results.add(
                    SearchResult(
                        id = obj.getInt("id"),
                        name = obj.getString("name"),
                        platformName = obj.getString("platform_name"),
                        variantNumber = obj.getInt("variant_number"),
                        assetCount = obj.getInt("asset_count"),
                        iconUrl = obj.optString("icon_url").takeIf { it.isNotEmpty() }
                    )
                )
            }
            results
        } catch (e: Exception) {
            Log.e(TAG, "Error searching games: ${e.message}")
            emptyList()
        }
    }

    /**
     * Get database statistics
     */
    suspend fun getStats(): Stats? = withContext(Dispatchers.IO) {
        try {
            val response = httpGet("$serverUrl/api/stats")
            val obj = JSONObject(response)

            Stats(
                platforms = obj.getInt("platforms"),
                games = obj.getInt("games"),
                assets = obj.getInt("assets"),
                totalSizeMb = obj.getDouble("total_size_mb")
            )
        } catch (e: Exception) {
            Log.e(TAG, "Error getting stats: ${e.message}")
            null
        }
    }

    /**
     * Download an asset to a file
     */
    suspend fun downloadAsset(downloadUrl: String, outputFile: File): Boolean = withContext(Dispatchers.IO) {
        try {
            val url = URL(downloadUrl)
            val connection = url.openConnection() as HttpURLConnection
            connection.connectTimeout = CONNECT_TIMEOUT
            connection.readTimeout = READ_TIMEOUT
            connection.instanceFollowRedirects = true

            if (connection.responseCode == 200) {
                outputFile.parentFile?.mkdirs()
                connection.inputStream.use { input ->
                    FileOutputStream(outputFile).use { output ->
                        input.copyTo(output)
                    }
                }
                true
            } else {
                Log.e(TAG, "Download failed with status: ${connection.responseCode}")
                false
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error downloading asset: ${e.message}")
            false
        }
    }

    /**
     * Upload an asset to the server
     */
    suspend fun uploadAsset(
        file: File,
        gameName: String,
        platform: String,
        assetType: String,
        variantNumber: Int = 1
    ): UploadResult = withContext(Dispatchers.IO) {
        try {
            val boundary = "===${System.currentTimeMillis()}==="
            val url = URL("$serverUrl/api/upload")
            val connection = url.openConnection() as HttpURLConnection

            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            connection.connectTimeout = CONNECT_TIMEOUT
            connection.readTimeout = READ_TIMEOUT * 2 // Allow more time for uploads

            connection.outputStream.use { output ->
                val writer = output.bufferedWriter()

                // Add form fields
                fun addFormField(name: String, value: String) {
                    writer.write("--$boundary\r\n")
                    writer.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
                    writer.write("$value\r\n")
                }

                addFormField("game_name", gameName)
                addFormField("platform", platform)
                addFormField("asset_type", assetType)
                addFormField("variant_number", variantNumber.toString())

                // Add file
                writer.write("--$boundary\r\n")
                writer.write("Content-Disposition: form-data; name=\"file\"; filename=\"${file.name}\"\r\n")
                writer.write("Content-Type: application/octet-stream\r\n\r\n")
                writer.flush()

                file.inputStream().use { fileInput ->
                    fileInput.copyTo(output)
                }

                writer.write("\r\n--$boundary--\r\n")
                writer.flush()
            }

            val responseCode = connection.responseCode
            val responseBody = if (responseCode == 200) {
                connection.inputStream.bufferedReader().readText()
            } else {
                connection.errorStream?.bufferedReader()?.readText() ?: ""
            }

            val json = JSONObject(responseBody)
            UploadResult(
                success = json.getBoolean("success"),
                message = json.getString("message"),
                gameId = json.optInt("game_id").takeIf { it > 0 },
                assetId = json.optInt("asset_id").takeIf { it > 0 }
            )
        } catch (e: Exception) {
            Log.e(TAG, "Error uploading asset: ${e.message}")
            UploadResult(
                success = false,
                message = "Upload failed: ${e.message}",
                gameId = null,
                assetId = null
            )
        }
    }

    // Private helper methods

    private fun httpGet(urlString: String): String {
        val url = URL(urlString)
        val connection = url.openConnection() as HttpURLConnection
        connection.connectTimeout = CONNECT_TIMEOUT
        connection.readTimeout = READ_TIMEOUT
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")

        return try {
            if (connection.responseCode == 200) {
                connection.inputStream.bufferedReader().readText()
            } else {
                throw Exception("HTTP ${connection.responseCode}: ${connection.responseMessage}")
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun parseGamesJson(jsonString: String): List<Game> {
        val jsonArray = JSONArray(jsonString)
        val games = mutableListOf<Game>()

        for (i in 0 until jsonArray.length()) {
            val obj = jsonArray.getJSONObject(i)
            games.add(parseGameJson(obj))
        }

        return games
    }

    private fun parseGameJson(obj: JSONObject): Game {
        val assetsArray = obj.optJSONArray("assets") ?: JSONArray()
        val assets = mutableListOf<Asset>()

        for (i in 0 until assetsArray.length()) {
            val assetObj = assetsArray.getJSONObject(i)
            assets.add(
                Asset(
                    id = assetObj.getInt("id"),
                    assetType = assetObj.getString("asset_type"),
                    filename = assetObj.getString("filename"),
                    fileSize = assetObj.getInt("file_size"),
                    mimeType = assetObj.getString("mime_type"),
                    width = assetObj.optInt("width").takeIf { it > 0 },
                    height = assetObj.optInt("height").takeIf { it > 0 },
                    downloadUrl = assetObj.getString("download_url"),
                    thumbnailUrl = assetObj.getString("thumbnail_url")
                )
            )
        }

        return Game(
            id = obj.getInt("id"),
            name = obj.getString("name"),
            platformName = obj.getString("platform_name"),
            variantNumber = obj.getInt("variant_number"),
            assetCount = obj.optInt("asset_count", assets.size),
            assets = assets
        )
    }
}
