package com.iisu.assettool.data

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Checks for app updates via the GitHub Releases API.
 *
 * Queries the latest release from viik4/iisu-asset-tool and compares
 * against the current app version. Handles APK download with progress
 * reporting for the Android build artifact.
 */
class UpdateChecker {

    companion object {
        private const val TAG = "UpdateChecker"
        private const val GITHUB_API_URL =
            "https://api.github.com/repos/viik4/iisu-asset-tool/releases/latest"
        private const val CONNECT_TIMEOUT = 10_000  // 10 seconds
        private const val READ_TIMEOUT = 30_000     // 30 seconds
        private const val DOWNLOAD_TIMEOUT = 300_000 // 5 minutes for APK download
        private const val PREFS_NAME = "updater_prefs"
        private const val KEY_LAST_CHECK = "last_update_check"
        private const val CHECK_COOLDOWN_MS = 3_600_000L  // 1 hour
        private const val APK_ASSET_NAME = "iiSU_Asset_Tool_Android.apk"
    }

    data class UpdateInfo(
        val latestVersion: String,
        val currentVersion: String,
        val isUpdateAvailable: Boolean,
        val changelog: String,
        val downloadUrl: String?,
        val downloadSize: Long,
        val releaseUrl: String
    )

    /**
     * Check the GitHub Releases API for a newer version.
     * Returns null if the check fails (no internet, API error, etc.)
     */
    suspend fun checkForUpdates(currentVersion: String): UpdateInfo? = withContext(Dispatchers.IO) {
        try {
            val url = URL(GITHUB_API_URL)
            val connection = url.openConnection() as HttpURLConnection
            connection.connectTimeout = CONNECT_TIMEOUT
            connection.readTimeout = READ_TIMEOUT
            connection.setRequestProperty("Accept", "application/vnd.github.v3+json")
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/$currentVersion")

            try {
                val responseCode = connection.responseCode
                if (responseCode != 200) {
                    Log.w(TAG, "GitHub API returned $responseCode")
                    return@withContext null
                }

                val responseText = connection.inputStream.bufferedReader().readText()
                val json = JSONObject(responseText)

                val tagName = json.optString("tag_name", "")
                val latestVersion = tagName.removePrefix("v")
                val changelog = json.optString("body", "")
                val releaseUrl = json.optString("html_url", "")

                // Find the APK asset
                var downloadUrl: String? = null
                var downloadSize: Long = 0
                val assets = json.optJSONArray("assets")
                if (assets != null) {
                    for (i in 0 until assets.length()) {
                        val asset = assets.getJSONObject(i)
                        val name = asset.optString("name", "")
                        if (name == APK_ASSET_NAME) {
                            downloadUrl = asset.optString("browser_download_url", "")
                            downloadSize = asset.optLong("size", 0)
                            break
                        }
                    }
                }

                val isNewer = compareVersions(currentVersion, latestVersion) < 0

                UpdateInfo(
                    latestVersion = latestVersion,
                    currentVersion = currentVersion,
                    isUpdateAvailable = isNewer,
                    changelog = changelog,
                    downloadUrl = downloadUrl,
                    downloadSize = downloadSize,
                    releaseUrl = releaseUrl
                )
            } finally {
                connection.disconnect()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Update check failed", e)
            null
        }
    }

    /**
     * Download the APK update to the given output file.
     * Reports progress via [onProgress] callback (bytesDownloaded, totalBytes).
     * Returns true on success.
     */
    suspend fun downloadApk(
        url: String,
        outputFile: File,
        onProgress: ((Long, Long) -> Unit)? = null
    ): Boolean = withContext(Dispatchers.IO) {
        try {
            outputFile.parentFile?.mkdirs()

            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = CONNECT_TIMEOUT
            connection.readTimeout = DOWNLOAD_TIMEOUT
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android")

            try {
                val responseCode = connection.responseCode
                if (responseCode != 200) {
                    Log.w(TAG, "Download returned $responseCode")
                    return@withContext false
                }

                val totalBytes = connection.contentLengthLong
                var downloadedBytes = 0L

                connection.inputStream.use { input ->
                    FileOutputStream(outputFile).use { output ->
                        val buffer = ByteArray(8192)
                        var bytesRead: Int
                        while (input.read(buffer).also { bytesRead = it } != -1) {
                            output.write(buffer, 0, bytesRead)
                            downloadedBytes += bytesRead
                            onProgress?.invoke(downloadedBytes, totalBytes)
                        }
                    }
                }

                downloadedBytes > 0
            } finally {
                connection.disconnect()
            }
        } catch (e: Exception) {
            Log.e(TAG, "APK download failed", e)
            outputFile.delete()
            false
        }
    }

    /**
     * Check whether we should perform an automatic update check
     * (respects 1-hour cooldown).
     */
    fun shouldCheckForUpdates(context: Context): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val lastCheck = prefs.getLong(KEY_LAST_CHECK, 0)
        return System.currentTimeMillis() - lastCheck > CHECK_COOLDOWN_MS
    }

    /**
     * Save the current time as the last update check timestamp.
     */
    fun saveLastCheckTime(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_CHECK, System.currentTimeMillis())
            .apply()
    }

    /**
     * Compare two version strings (e.g. "2.0.1" vs "2.1.0").
     * Returns negative if v1 < v2, 0 if equal, positive if v1 > v2.
     */
    private fun compareVersions(v1: String, v2: String): Int {
        val parts1 = v1.split(".").map { it.toIntOrNull() ?: 0 }
        val parts2 = v2.split(".").map { it.toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(parts1.size, parts2.size)) {
            val a = parts1.getOrElse(i) { 0 }
            val b = parts2.getOrElse(i) { 0 }
            if (a != b) return a.compareTo(b)
        }
        return 0
    }

    /**
     * Format a byte count into a human-readable string.
     */
    fun formatSize(bytes: Long): String {
        return when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "%.1f KB".format(bytes / 1024.0)
            bytes < 1024 * 1024 * 1024 -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
            else -> "%.2f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
        }
    }
}
