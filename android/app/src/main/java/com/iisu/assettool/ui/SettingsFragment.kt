package com.iisu.assettool.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import android.os.Environment
import android.provider.DocumentsContract
import android.util.Log
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatDelegate
import androidx.documentfile.provider.DocumentFile
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.viewpager2.adapter.FragmentStateAdapter
import com.google.android.material.tabs.TabLayoutMediator
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import com.iisu.assettool.BuildConfig
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentSettingsBinding
import com.iisu.assettool.util.ArtworkSource
import com.iisu.assettool.util.IisuDirectoryManager
import com.iisu.assettool.util.SourcePriorityAdapter
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

/**
 * Settings Fragment with Tabbed Interface
 *
 * Uses ViewPager2 with tabs like iiSU Launcher settings.
 * Tabs: Display Options, Appearance Options, Scraper Options, Input & Sound Options, System Options
 */
class SettingsFragment : Fragment() {

    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!

    companion object {
        const val PREFS_NAME = "iisu_asset_tool_prefs"
        const val PREF_SGDB_API_KEY = "steamgriddb_api_key"
        const val PREF_IGDB_CLIENT_ID = "igdb_client_id"
        const val PREF_IGDB_CLIENT_SECRET = "igdb_client_secret"
        const val PREF_PARALLEL_DOWNLOADS = "parallel_downloads"
        const val PREF_INTERACTIVE_MODE = "interactive_mode"
        const val PREF_DS_MODE = "ds_mode"
        const val PREF_CUSTOM_ASSET_DIR = "custom_asset_directory"
        const val PREF_SOURCE_PRIORITY = "source_priority"
        const val PREF_SCRAPE_LOGOS = "scrape_logos"
        const val PREF_LOGO_FALLBACK_BOXART = "logo_fallback_boxart"
        const val PREF_HERO_ENABLED = "hero_enabled"
        const val PREF_HERO_COUNT = "hero_count"
        const val PREF_HERO_CROP_ENABLED = "hero_crop_enabled"
        const val PREF_HERO_CROP_POSITION = "hero_crop_position"
        const val PREF_USE_FALLBACK = "use_platform_fallback"
        const val PREF_SKIP_SCRAPING = "skip_scraping"
        const val PREF_EXPORT_FORMAT = "export_format"
        const val PREF_JPEG_QUALITY = "jpeg_quality"
        const val PREF_USE_CUSTOM_BORDER = "use_custom_border"
        const val PREF_CUSTOM_BORDER_PATH = "custom_border_path"
        const val PREF_SCREENSHOTS_ENABLED = "screenshots_enabled"
        const val PREF_SCREENSHOT_COUNT = "screenshot_count"
        const val PREF_HIDDEN_TITLES = "hidden_titles"
        const val PREF_SQUARE_ICONS_ONLY = "square_icons_only"
        const val PREF_DEEP_SEARCH = "deep_search"
        const val PREF_ANDROID_APPS_PATH = "android_apps_path"
        const val PREF_MUSIC_ENABLED = "music_enabled"
        const val PREF_MUSIC_VOLUME = "music_volume"
        const val PREF_ROM_SOURCE_PATH = "rom_source_path"

        const val DEFAULT_PARALLEL_DOWNLOADS = 3
        const val DEFAULT_MUSIC_ENABLED = true
        const val DEFAULT_MUSIC_VOLUME = 50
        const val DEFAULT_SQUARE_ICONS_ONLY = true
        const val DEFAULT_INTERACTIVE_MODE = true
        const val DEFAULT_DS_MODE = false
        const val DEFAULT_SCRAPE_LOGOS = true
        const val DEFAULT_LOGO_FALLBACK_BOXART = true
        const val DEFAULT_HERO_ENABLED = true
        const val DEFAULT_HERO_COUNT = 1
        const val DEFAULT_HERO_CROP_ENABLED = true
        const val DEFAULT_HERO_CROP_POSITION = 0.5f
        const val HERO_TARGET_WIDTH = 1920
        const val HERO_TARGET_HEIGHT = 1080
        const val DEFAULT_USE_FALLBACK = false
        const val DEFAULT_SKIP_SCRAPING = false
        const val DEFAULT_EXPORT_FORMAT = "PNG"
        const val DEFAULT_JPEG_QUALITY = 95
        const val DEFAULT_USE_CUSTOM_BORDER = false
        const val DEFAULT_SCREENSHOTS_ENABLED = false
        const val DEFAULT_SCREENSHOT_COUNT = 3
        const val DEFAULT_DEEP_SEARCH = false
        const val DEFAULT_ANDROID_APPS_PATH = "/storage/emulated/0/Android/media/com.iisulauncher/iiSULauncher/assets/media/android/apps"

        private const val CUSTOM_BORDER_FILENAME = "custom_border.png"

        // Tab titles
        private val TAB_TITLES = arrayOf(
            "Display",
            "Appearance",
            "Scraper",
            "Output",
            "System"
        )

        // Static helper methods for accessing settings
        fun getSteamGridDBApiKey(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val key = prefs.getString(PREF_SGDB_API_KEY, null)
            return if (key.isNullOrBlank()) null else key
        }

        fun getIgdbClientId(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val key = prefs.getString(PREF_IGDB_CLIENT_ID, null)
            return if (key.isNullOrBlank()) null else key
        }

        fun getIgdbClientSecret(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val key = prefs.getString(PREF_IGDB_CLIENT_SECRET, null)
            return if (key.isNullOrBlank()) null else key
        }

        fun getParallelDownloads(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_PARALLEL_DOWNLOADS, DEFAULT_PARALLEL_DOWNLOADS)
        }

        fun isInteractiveModeEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_INTERACTIVE_MODE, DEFAULT_INTERACTIVE_MODE)
        }

        fun isDsModeEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_DS_MODE, DEFAULT_DS_MODE)
        }

        fun isDeepSearchEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_DEEP_SEARCH, DEFAULT_DEEP_SEARCH)
        }

        fun getAndroidAppsPath(context: Context): String {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getString(PREF_ANDROID_APPS_PATH, DEFAULT_ANDROID_APPS_PATH) ?: DEFAULT_ANDROID_APPS_PATH
        }

        fun setAndroidAppsPath(context: Context, path: String) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putString(PREF_ANDROID_APPS_PATH, path).apply()
        }

        fun isMusicEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_MUSIC_ENABLED, DEFAULT_MUSIC_ENABLED)
        }

        fun setMusicEnabled(context: Context, enabled: Boolean) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putBoolean(PREF_MUSIC_ENABLED, enabled).apply()
        }

        fun getMusicVolume(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_MUSIC_VOLUME, DEFAULT_MUSIC_VOLUME)
        }

        fun setMusicVolume(context: Context, volume: Int) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putInt(PREF_MUSIC_VOLUME, volume).apply()
        }

        fun getRomSourcePath(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val path = prefs.getString(PREF_ROM_SOURCE_PATH, null)
            return if (path.isNullOrBlank()) null else path
        }

        fun setRomSourcePath(context: Context, path: String?) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            if (path.isNullOrBlank()) {
                prefs.edit().remove(PREF_ROM_SOURCE_PATH).apply()
            } else {
                prefs.edit().putString(PREF_ROM_SOURCE_PATH, path).apply()
            }
        }

        fun getCustomAssetDirectory(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val path = prefs.getString(PREF_CUSTOM_ASSET_DIR, null)
            return if (path.isNullOrBlank()) null else path
        }

        fun getEnabledSources(context: Context): List<ArtworkSource> {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val json = prefs.getString(PREF_SOURCE_PRIORITY, null)

            return if (json != null) {
                try {
                    val array = JSONArray(json)
                    val sources = mutableListOf<ArtworkSource>()
                    val defaultSources = ArtworkSource.getDefaultSources().associateBy { it.id }

                    for (i in 0 until array.length()) {
                        val obj = array.getJSONObject(i)
                        val id = obj.getString("id")
                        val enabled = obj.getBoolean("enabled")
                        defaultSources[id]?.let { source ->
                            sources.add(source.copy(enabled = enabled))
                        }
                    }
                    sources.filter { it.enabled }
                } catch (e: Exception) {
                    ArtworkSource.getDefaultSources().filter { it.enabled }
                }
            } else {
                ArtworkSource.getDefaultSources().filter { it.enabled }
            }
        }

        fun isScrapeLogosEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SCRAPE_LOGOS, DEFAULT_SCRAPE_LOGOS)
        }

        fun isSquareIconsOnly(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SQUARE_ICONS_ONLY, DEFAULT_SQUARE_ICONS_ONLY)
        }

        fun setSquareIconsOnly(context: Context, value: Boolean) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putBoolean(PREF_SQUARE_ICONS_ONLY, value).apply()
        }

        fun isLogoFallbackBoxartEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_LOGO_FALLBACK_BOXART, DEFAULT_LOGO_FALLBACK_BOXART)
        }

        fun isHeroEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_HERO_ENABLED, DEFAULT_HERO_ENABLED)
        }

        fun getHeroCount(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_HERO_COUNT, DEFAULT_HERO_COUNT)
        }

        fun isHeroCropEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_HERO_CROP_ENABLED, DEFAULT_HERO_CROP_ENABLED)
        }

        fun getHeroCropPosition(context: Context): Float {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getFloat(PREF_HERO_CROP_POSITION, DEFAULT_HERO_CROP_POSITION)
        }

        fun isUseFallbackEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_USE_FALLBACK, DEFAULT_USE_FALLBACK)
        }

        fun isSkipScrapingEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SKIP_SCRAPING, DEFAULT_SKIP_SCRAPING)
        }

        fun getExportFormat(context: Context): String {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getString(PREF_EXPORT_FORMAT, DEFAULT_EXPORT_FORMAT) ?: DEFAULT_EXPORT_FORMAT
        }

        fun getJpegQuality(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_JPEG_QUALITY, DEFAULT_JPEG_QUALITY)
        }

        fun isCustomBorderEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_USE_CUSTOM_BORDER, DEFAULT_USE_CUSTOM_BORDER)
        }

        fun getCustomBorderPath(context: Context): String? {
            if (!isCustomBorderEnabled(context)) return null
            val file = File(context.filesDir, CUSTOM_BORDER_FILENAME)
            return if (file.exists()) file.absolutePath else null
        }

        fun isScreenshotsEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SCREENSHOTS_ENABLED, DEFAULT_SCREENSHOTS_ENABLED)
        }

        fun getScreenshotCount(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_SCREENSHOT_COUNT, DEFAULT_SCREENSHOT_COUNT)
        }

        /**
         * Get all hidden titles as a map of platform -> set of titles
         */
        fun getHiddenTitles(context: Context): Map<String, Set<String>> {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val json = prefs.getString(PREF_HIDDEN_TITLES, null) ?: return emptyMap()
            return try {
                val jsonObj = JSONObject(json)
                val result = mutableMapOf<String, Set<String>>()
                for (platform in jsonObj.keys()) {
                    val titlesArray = jsonObj.getJSONArray(platform)
                    val titles = mutableSetOf<String>()
                    for (i in 0 until titlesArray.length()) {
                        titles.add(titlesArray.getString(i))
                    }
                    result[platform] = titles
                }
                result
            } catch (e: Exception) {
                emptyMap()
            }
        }

        /**
         * Hide a title for a specific platform
         */
        fun hideTitle(context: Context, platform: String, title: String) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val hidden = getHiddenTitles(context).toMutableMap()
            val platformTitles = hidden.getOrDefault(platform, emptySet()).toMutableSet()
            platformTitles.add(title)
            hidden[platform] = platformTitles

            // Save as JSON
            val jsonObj = JSONObject()
            for ((p, titles) in hidden) {
                jsonObj.put(p, JSONArray(titles.toList()))
            }
            prefs.edit().putString(PREF_HIDDEN_TITLES, jsonObj.toString()).apply()
        }

        /**
         * Unhide a title for a specific platform
         */
        fun unhideTitle(context: Context, platform: String, title: String) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val hidden = getHiddenTitles(context).toMutableMap()
            val platformTitles = hidden.getOrDefault(platform, emptySet()).toMutableSet()
            platformTitles.remove(title)
            if (platformTitles.isEmpty()) {
                hidden.remove(platform)
            } else {
                hidden[platform] = platformTitles
            }

            // Save as JSON
            val jsonObj = JSONObject()
            for ((p, titles) in hidden) {
                jsonObj.put(p, JSONArray(titles.toList()))
            }
            prefs.edit().putString(PREF_HIDDEN_TITLES, jsonObj.toString()).apply()
        }

        /**
         * Check if a title is hidden
         */
        fun isTitleHidden(context: Context, platform: String, title: String): Boolean {
            val hidden = getHiddenTitles(context)
            return hidden[platform]?.contains(title) == true
        }

        /**
         * Clear all hidden titles
         */
        fun clearHiddenTitles(context: Context) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().remove(PREF_HIDDEN_TITLES).apply()
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Setup ViewPager2 with tabs
        val pagerAdapter = SettingsPagerAdapter(this)
        binding.viewPagerSettings.adapter = pagerAdapter

        // Connect TabLayout with ViewPager2
        TabLayoutMediator(binding.tabLayoutSettings, binding.viewPagerSettings) { tab, position ->
            tab.text = TAB_TITLES[position]
        }.attach()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    /**
     * ViewPager2 adapter for settings tabs
     */
    private inner class SettingsPagerAdapter(fragment: Fragment) : FragmentStateAdapter(fragment) {

        override fun getItemCount(): Int = TAB_TITLES.size

        override fun createFragment(position: Int): Fragment {
            return when (position) {
                0 -> SettingsDisplayFragment()
                1 -> SettingsAppearanceFragment()
                2 -> SettingsScraperFragment()
                3 -> SettingsOutputFragment()
                4 -> SettingsSystemFragment()
                else -> SettingsDisplayFragment()
            }
        }
    }
}
