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
import android.provider.DocumentsContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatDelegate
import androidx.documentfile.provider.DocumentFile
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import com.iisu.assettool.BuildConfig
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentSettingsBinding
import com.iisu.assettool.util.ArtworkSource
import com.iisu.assettool.util.SourcePriorityAdapter
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

/**
 * Settings Fragment
 *
 * Touch-friendly settings interface.
 * Features:
 * - Theme selection (Dark/Light/System)
 * - API key configuration for SteamGridDB
 * - Source priority with drag-to-reorder
 * - Logo/title settings
 * - Hero image settings
 * - Fallback icon settings
 * - Export format settings
 * - About section with iiSU branding
 */
class SettingsFragment : Fragment() {

    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!

    private lateinit var sourcePriorityAdapter: SourcePriorityAdapter

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
        const val PREF_HERO_CROP_POSITION = "hero_crop_position"  // 0.0 to 1.0, vertical position
        const val PREF_USE_FALLBACK = "use_platform_fallback"
        const val PREF_SKIP_SCRAPING = "skip_scraping"
        const val PREF_EXPORT_FORMAT = "export_format"
        const val PREF_JPEG_QUALITY = "jpeg_quality"
        const val PREF_USE_CUSTOM_BORDER = "use_custom_border"
        const val PREF_CUSTOM_BORDER_PATH = "custom_border_path"
        const val PREF_SCREENSHOTS_ENABLED = "screenshots_enabled"
        const val PREF_SCREENSHOT_COUNT = "screenshot_count"

        const val DEFAULT_PARALLEL_DOWNLOADS = 3
        const val DEFAULT_INTERACTIVE_MODE = true
        const val DEFAULT_DS_MODE = false
        const val DEFAULT_SCRAPE_LOGOS = true
        const val DEFAULT_LOGO_FALLBACK_BOXART = true
        const val DEFAULT_HERO_ENABLED = true
        const val DEFAULT_HERO_COUNT = 1
        const val DEFAULT_HERO_CROP_ENABLED = true
        const val DEFAULT_HERO_CROP_POSITION = 0.5f  // Center by default
        const val HERO_TARGET_WIDTH = 1920
        const val HERO_TARGET_HEIGHT = 1080
        const val DEFAULT_USE_FALLBACK = false
        const val DEFAULT_SKIP_SCRAPING = false
        const val DEFAULT_EXPORT_FORMAT = "PNG"
        const val DEFAULT_JPEG_QUALITY = 95
        const val DEFAULT_USE_CUSTOM_BORDER = false
        const val DEFAULT_SCREENSHOTS_ENABLED = false
        const val DEFAULT_SCREENSHOT_COUNT = 3

        private const val CUSTOM_BORDER_FILENAME = "custom_border.png"

        /**
         * Get the saved SteamGridDB API key.
         */
        fun getSteamGridDBApiKey(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val key = prefs.getString(PREF_SGDB_API_KEY, null)
            return if (key.isNullOrBlank()) null else key
        }

        /**
         * Get the saved IGDB Client ID.
         */
        fun getIgdbClientId(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val key = prefs.getString(PREF_IGDB_CLIENT_ID, null)
            return if (key.isNullOrBlank()) null else key
        }

        /**
         * Get the saved IGDB Client Secret.
         */
        fun getIgdbClientSecret(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val key = prefs.getString(PREF_IGDB_CLIENT_SECRET, null)
            return if (key.isNullOrBlank()) null else key
        }

        /**
         * Get the number of parallel downloads for bulk generation.
         */
        fun getParallelDownloads(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_PARALLEL_DOWNLOADS, DEFAULT_PARALLEL_DOWNLOADS)
        }

        /**
         * Get whether interactive mode is enabled for bulk generation.
         */
        fun isInteractiveModeEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_INTERACTIVE_MODE, DEFAULT_INTERACTIVE_MODE)
        }

        /**
         * Get whether DS Mode is enabled (show hero/logo sections for dual-screen devices).
         */
        fun isDsModeEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_DS_MODE, DEFAULT_DS_MODE)
        }

        /**
         * Get custom asset directory path (or null if not set).
         */
        fun getCustomAssetDirectory(context: Context): String? {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val path = prefs.getString(PREF_CUSTOM_ASSET_DIR, null)
            return if (path.isNullOrBlank()) null else path
        }

        /**
         * Get the ordered list of enabled artwork sources.
         */
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

        /**
         * Get whether logo scraping is enabled.
         */
        fun isScrapeLogosEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SCRAPE_LOGOS, DEFAULT_SCRAPE_LOGOS)
        }

        /**
         * Get whether to fallback to boxart for logos.
         */
        fun isLogoFallbackBoxartEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_LOGO_FALLBACK_BOXART, DEFAULT_LOGO_FALLBACK_BOXART)
        }

        /**
         * Get whether hero image download is enabled.
         */
        fun isHeroEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_HERO_ENABLED, DEFAULT_HERO_ENABLED)
        }

        /**
         * Get the number of hero images to download per game.
         */
        fun getHeroCount(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_HERO_COUNT, DEFAULT_HERO_COUNT)
        }

        /**
         * Get whether hero cropping to 1920x1080 is enabled.
         */
        fun isHeroCropEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_HERO_CROP_ENABLED, DEFAULT_HERO_CROP_ENABLED)
        }

        /**
         * Get the hero crop vertical position (0.0 = top, 0.5 = center, 1.0 = bottom).
         */
        fun getHeroCropPosition(context: Context): Float {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getFloat(PREF_HERO_CROP_POSITION, DEFAULT_HERO_CROP_POSITION)
        }

        /**
         * Get whether to use platform icon fallback.
         */
        fun isUseFallbackEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_USE_FALLBACK, DEFAULT_USE_FALLBACK)
        }

        /**
         * Get whether to skip scraping entirely.
         */
        fun isSkipScrapingEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SKIP_SCRAPING, DEFAULT_SKIP_SCRAPING)
        }

        /**
         * Get the export format (PNG or JPEG).
         */
        fun getExportFormat(context: Context): String {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getString(PREF_EXPORT_FORMAT, DEFAULT_EXPORT_FORMAT) ?: DEFAULT_EXPORT_FORMAT
        }

        /**
         * Get the JPEG quality (1-100).
         */
        fun getJpegQuality(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_JPEG_QUALITY, DEFAULT_JPEG_QUALITY)
        }

        /**
         * Get whether to use custom border.
         */
        fun isCustomBorderEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_USE_CUSTOM_BORDER, DEFAULT_USE_CUSTOM_BORDER)
        }

        /**
         * Get the custom border file path (internal storage).
         */
        fun getCustomBorderPath(context: Context): String? {
            if (!isCustomBorderEnabled(context)) return null
            val file = File(context.filesDir, CUSTOM_BORDER_FILENAME)
            return if (file.exists()) file.absolutePath else null
        }

        /**
         * Get whether screenshot download is enabled.
         */
        fun isScreenshotsEnabled(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_SCREENSHOTS_ENABLED, DEFAULT_SCREENSHOTS_ENABLED)
        }

        /**
         * Get the number of screenshots to download per game.
         */
        fun getScreenshotCount(context: Context): Int {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getInt(PREF_SCREENSHOT_COUNT, DEFAULT_SCREENSHOT_COUNT)
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

    // Image picker for custom border
    private val pickCustomBorderLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                saveCustomBorder(uri)
            }
        }
    }

    // Directory picker for custom asset directory
    private val pickAssetDirLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri ->
        uri?.let { saveCustomAssetDirectory(it) }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        setupThemeSelection()
        setupApiKeySection()
        setupBulkGenerationSection()
        setupSourcePrioritySection()
        setupDsModeSection()
        setupLogoSection()
        setupHeroSection()
        setupScreenshotSection()
        setupCustomBorderSection()
        setupCustomAssetDirSection()
        setupFallbackSection()
        setupExportFormatSection()
        setupAboutSection()
    }

    private fun setupThemeSelection() {
        // Set current theme selection
        when (AppCompatDelegate.getDefaultNightMode()) {
            AppCompatDelegate.MODE_NIGHT_YES -> binding.radioThemeDark.isChecked = true
            AppCompatDelegate.MODE_NIGHT_NO -> binding.radioThemeLight.isChecked = true
            else -> binding.radioThemeSystem.isChecked = true
        }

        binding.radioGroupTheme.setOnCheckedChangeListener { _, checkedId ->
            val mode = when (checkedId) {
                R.id.radioThemeDark -> AppCompatDelegate.MODE_NIGHT_YES
                R.id.radioThemeLight -> AppCompatDelegate.MODE_NIGHT_NO
                else -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            }
            AppCompatDelegate.setDefaultNightMode(mode)
        }
    }

    private fun setupApiKeySection() {
        // Load saved API keys
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val savedSgdbKey = prefs.getString(PREF_SGDB_API_KEY, "")
        val savedIgdbClientId = prefs.getString(PREF_IGDB_CLIENT_ID, "")
        val savedIgdbClientSecret = prefs.getString(PREF_IGDB_CLIENT_SECRET, "")

        binding.editSgdbApiKey.setText(savedSgdbKey)
        binding.editIgdbClientId.setText(savedIgdbClientId)
        binding.editIgdbClientSecret.setText(savedIgdbClientSecret)

        // Save button click handler
        binding.btnSaveApiKey.setOnClickListener {
            val sgdbApiKey = binding.editSgdbApiKey.text?.toString()?.trim() ?: ""
            val igdbClientId = binding.editIgdbClientId.text?.toString()?.trim() ?: ""
            val igdbClientSecret = binding.editIgdbClientSecret.text?.toString()?.trim() ?: ""

            // Save all API keys to SharedPreferences
            prefs.edit()
                .putString(PREF_SGDB_API_KEY, sgdbApiKey)
                .putString(PREF_IGDB_CLIENT_ID, igdbClientId)
                .putString(PREF_IGDB_CLIENT_SECRET, igdbClientSecret)
                .apply()

            Toast.makeText(context, "API keys saved", Toast.LENGTH_SHORT).show()
        }
    }

    private fun setupBulkGenerationSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Parallel downloads slider
        val savedParallelCount = prefs.getInt(PREF_PARALLEL_DOWNLOADS, DEFAULT_PARALLEL_DOWNLOADS)
        binding.sliderParallelDownloads.value = savedParallelCount.toFloat()
        binding.textParallelCount.text = savedParallelCount.toString()

        binding.sliderParallelDownloads.addOnChangeListener { _, value, _ ->
            val count = value.toInt()
            binding.textParallelCount.text = count.toString()
            prefs.edit().putInt(PREF_PARALLEL_DOWNLOADS, count).apply()
        }

        // Interactive mode toggle
        val savedInteractiveMode = prefs.getBoolean(PREF_INTERACTIVE_MODE, DEFAULT_INTERACTIVE_MODE)
        binding.switchInteractiveMode.isChecked = savedInteractiveMode

        binding.switchInteractiveMode.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_INTERACTIVE_MODE, isChecked).apply()
            // Show warning when disabling interactive mode
            if (!isChecked) {
                Toast.makeText(
                    context,
                    "Warning: Without Interactive Mode, artwork will be auto-selected without prompting",
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }

    private fun setupDsModeSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // DS Mode toggle
        val savedDsMode = prefs.getBoolean(PREF_DS_MODE, DEFAULT_DS_MODE)
        binding.switchDsMode.isChecked = savedDsMode
        updateDsModeVisibility(savedDsMode)

        binding.switchDsMode.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_DS_MODE, isChecked).apply()
            updateDsModeVisibility(isChecked)
        }
    }

    private fun updateDsModeVisibility(dsMode: Boolean) {
        // Show/hide hero and logo sections based on DS Mode
        val visibility = if (dsMode) View.VISIBLE else View.GONE
        binding.cardHeroSection.visibility = visibility
        binding.cardLogoSection.visibility = visibility
    }

    private fun setupSourcePrioritySection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        sourcePriorityAdapter = SourcePriorityAdapter { sources ->
            // Save source priority when order changes
            val jsonArray = JSONArray()
            sources.forEach { source ->
                val obj = JSONObject()
                obj.put("id", source.id)
                obj.put("enabled", source.enabled)
                jsonArray.put(obj)
            }
            prefs.edit().putString(PREF_SOURCE_PRIORITY, jsonArray.toString()).apply()
        }

        binding.recyclerSourcePriority.apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = sourcePriorityAdapter
        }
        sourcePriorityAdapter.attachToRecyclerView(binding.recyclerSourcePriority)

        // Load saved source priority or use defaults
        val savedJson = prefs.getString(PREF_SOURCE_PRIORITY, null)
        val sources = if (savedJson != null) {
            try {
                val array = JSONArray(savedJson)
                val defaultSources = ArtworkSource.getDefaultSources().associateBy { it.id }
                val loadedSources = mutableListOf<ArtworkSource>()

                for (i in 0 until array.length()) {
                    val obj = array.getJSONObject(i)
                    val id = obj.getString("id")
                    val enabled = obj.getBoolean("enabled")
                    defaultSources[id]?.let { source ->
                        loadedSources.add(source.copy(enabled = enabled))
                    }
                }
                loadedSources
            } catch (e: Exception) {
                ArtworkSource.getDefaultSources()
            }
        } else {
            ArtworkSource.getDefaultSources()
        }

        sourcePriorityAdapter.setSources(sources)

        // Enable/Disable all buttons
        binding.btnEnableAllSources.setOnClickListener {
            sourcePriorityAdapter.enableAll()
        }

        binding.btnDisableAllSources.setOnClickListener {
            sourcePriorityAdapter.disableAll()
        }
    }

    private fun setupLogoSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Scrape logos toggle
        binding.switchScrapeLogos.isChecked = prefs.getBoolean(PREF_SCRAPE_LOGOS, DEFAULT_SCRAPE_LOGOS)
        binding.switchScrapeLogos.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_SCRAPE_LOGOS, isChecked).apply()
        }

        // Logo fallback to boxart toggle
        binding.switchLogoFallbackBoxart.isChecked = prefs.getBoolean(PREF_LOGO_FALLBACK_BOXART, DEFAULT_LOGO_FALLBACK_BOXART)
        binding.switchLogoFallbackBoxart.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_LOGO_FALLBACK_BOXART, isChecked).apply()
        }
    }

    private fun setupHeroSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Hero enabled toggle
        binding.switchHeroEnabled.isChecked = prefs.getBoolean(PREF_HERO_ENABLED, DEFAULT_HERO_ENABLED)
        binding.switchHeroEnabled.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_HERO_ENABLED, isChecked).apply()
        }

        // Hero count slider
        val savedHeroCount = prefs.getInt(PREF_HERO_COUNT, DEFAULT_HERO_COUNT)
        binding.sliderHeroCount.value = savedHeroCount.toFloat()
        binding.textHeroCount.text = savedHeroCount.toString()

        binding.sliderHeroCount.addOnChangeListener { _, value, _ ->
            val count = value.toInt()
            binding.textHeroCount.text = count.toString()
            prefs.edit().putInt(PREF_HERO_COUNT, count).apply()
        }

        // Hero crop toggle
        binding.switchHeroCrop.isChecked = prefs.getBoolean(PREF_HERO_CROP_ENABLED, DEFAULT_HERO_CROP_ENABLED)
        binding.switchHeroCrop.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_HERO_CROP_ENABLED, isChecked).apply()
            // Show/hide crop position slider based on crop toggle
            binding.layoutHeroCropPosition.visibility = if (isChecked) View.VISIBLE else View.GONE
        }

        // Hero crop position slider (0.0 = top, 0.5 = center, 1.0 = bottom)
        val savedCropPosition = prefs.getFloat(PREF_HERO_CROP_POSITION, DEFAULT_HERO_CROP_POSITION)
        binding.sliderHeroCropPosition.value = savedCropPosition
        updateCropPositionLabel(savedCropPosition)

        // Show/hide crop position based on crop toggle
        binding.layoutHeroCropPosition.visibility = if (binding.switchHeroCrop.isChecked) View.VISIBLE else View.GONE

        binding.sliderHeroCropPosition.addOnChangeListener { _, value, _ ->
            updateCropPositionLabel(value)
            prefs.edit().putFloat(PREF_HERO_CROP_POSITION, value).apply()
        }
    }

    private fun updateCropPositionLabel(position: Float) {
        val label = when {
            position <= 0.2f -> "Top"
            position <= 0.4f -> "Upper"
            position <= 0.6f -> "Center"
            position <= 0.8f -> "Lower"
            else -> "Bottom"
        }
        binding.textHeroCropPosition.text = label
    }

    private fun setupScreenshotSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Screenshots enabled toggle
        binding.switchScreenshotsEnabled.isChecked = prefs.getBoolean(PREF_SCREENSHOTS_ENABLED, DEFAULT_SCREENSHOTS_ENABLED)
        binding.switchScreenshotsEnabled.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_SCREENSHOTS_ENABLED, isChecked).apply()
        }

        // Screenshot count slider
        val savedScreenshotCount = prefs.getInt(PREF_SCREENSHOT_COUNT, DEFAULT_SCREENSHOT_COUNT)
        binding.sliderScreenshotCount.value = savedScreenshotCount.toFloat()
        binding.textScreenshotCount.text = savedScreenshotCount.toString()

        binding.sliderScreenshotCount.addOnChangeListener { _, value, _ ->
            val count = value.toInt()
            binding.textScreenshotCount.text = count.toString()
            prefs.edit().putInt(PREF_SCREENSHOT_COUNT, count).apply()
        }
    }

    private fun setupCustomBorderSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Use custom border toggle
        val useCustomBorder = prefs.getBoolean(PREF_USE_CUSTOM_BORDER, DEFAULT_USE_CUSTOM_BORDER)
        binding.switchUseCustomBorder.isChecked = useCustomBorder
        binding.layoutCustomBorder.visibility = if (useCustomBorder) View.VISIBLE else View.GONE

        binding.switchUseCustomBorder.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_USE_CUSTOM_BORDER, isChecked).apply()
            binding.layoutCustomBorder.visibility = if (isChecked) View.VISIBLE else View.GONE
        }

        // Select custom border button
        binding.btnSelectCustomBorder.setOnClickListener {
            val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "image/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }
            pickCustomBorderLauncher.launch(Intent.createChooser(intent, "Select Border Image"))
        }

        // Clear custom border button
        binding.btnClearCustomBorder.setOnClickListener {
            clearCustomBorder()
        }

        // Load existing custom border preview
        loadCustomBorderPreview()
    }

    private fun setupCustomAssetDirSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Load saved custom asset directory
        val savedPath = prefs.getString(PREF_CUSTOM_ASSET_DIR, null)
        updateCustomAssetDirDisplay(savedPath)

        // Select directory button
        binding.btnSelectAssetDir.setOnClickListener {
            pickAssetDirLauncher.launch(null)
        }

        // Clear directory button
        binding.btnClearAssetDir.setOnClickListener {
            prefs.edit().remove(PREF_CUSTOM_ASSET_DIR).apply()
            updateCustomAssetDirDisplay(null)
            Toast.makeText(context, "Custom asset directory cleared", Toast.LENGTH_SHORT).show()
        }
    }

    private fun saveCustomAssetDirectory(uri: Uri) {
        try {
            // Take persistable permission for the directory
            val takeFlags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            requireContext().contentResolver.takePersistableUriPermission(uri, takeFlags)

            // Save the URI string to preferences
            val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putString(PREF_CUSTOM_ASSET_DIR, uri.toString()).apply()

            updateCustomAssetDirDisplay(uri.toString())
            Toast.makeText(context, "Custom asset directory saved", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(context, "Failed to save directory: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun updateCustomAssetDirDisplay(uriString: String?) {
        if (uriString != null) {
            try {
                val uri = Uri.parse(uriString)
                val docFile = DocumentFile.fromTreeUri(requireContext(), uri)
                binding.textCustomAssetDir.text = docFile?.name ?: "Custom directory set"
            } catch (e: Exception) {
                binding.textCustomAssetDir.text = "Custom directory set"
            }
        } else {
            binding.textCustomAssetDir.text = "Default (iiSU Launcher media folder)"
        }
    }

    private fun saveCustomBorder(uri: Uri) {
        try {
            val inputStream = requireContext().contentResolver.openInputStream(uri)
            val bitmap = BitmapFactory.decodeStream(inputStream)
            inputStream?.close()

            if (bitmap == null) {
                Toast.makeText(context, "Failed to load image", Toast.LENGTH_SHORT).show()
                return
            }

            // Save to internal storage as PNG
            val file = File(requireContext().filesDir, CUSTOM_BORDER_FILENAME)
            FileOutputStream(file).use { out ->
                bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out)
            }

            // Update preview
            binding.imageCustomBorderPreview.setImageBitmap(bitmap)
            binding.textCustomBorderPath.text = "Custom border saved"

            Toast.makeText(context, "Custom border saved", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(context, "Failed to save border: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun clearCustomBorder() {
        try {
            val file = File(requireContext().filesDir, CUSTOM_BORDER_FILENAME)
            if (file.exists()) {
                file.delete()
            }

            binding.imageCustomBorderPreview.setImageDrawable(null)
            binding.textCustomBorderPath.text = "No custom border selected"

            Toast.makeText(context, "Custom border cleared", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(context, "Failed to clear border: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun loadCustomBorderPreview() {
        val file = File(requireContext().filesDir, CUSTOM_BORDER_FILENAME)
        if (file.exists()) {
            try {
                val bitmap = BitmapFactory.decodeFile(file.absolutePath)
                binding.imageCustomBorderPreview.setImageBitmap(bitmap)
                binding.textCustomBorderPath.text = "Custom border saved"
            } catch (e: Exception) {
                binding.textCustomBorderPath.text = "No custom border selected"
            }
        } else {
            binding.textCustomBorderPath.text = "No custom border selected"
        }
    }

    private fun setupFallbackSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Use fallback toggle
        binding.switchUseFallback.isChecked = prefs.getBoolean(PREF_USE_FALLBACK, DEFAULT_USE_FALLBACK)
        binding.switchUseFallback.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_USE_FALLBACK, isChecked).apply()
        }

        // Skip scraping toggle
        binding.switchSkipScraping.isChecked = prefs.getBoolean(PREF_SKIP_SCRAPING, DEFAULT_SKIP_SCRAPING)
        binding.switchSkipScraping.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(PREF_SKIP_SCRAPING, isChecked).apply()
            // If skip scraping is enabled, disable use fallback as it's redundant
            if (isChecked) {
                binding.switchUseFallback.isChecked = false
                binding.switchUseFallback.isEnabled = false
            } else {
                binding.switchUseFallback.isEnabled = true
            }
        }

        // Set initial enabled state for use fallback
        binding.switchUseFallback.isEnabled = !binding.switchSkipScraping.isChecked
    }

    private fun setupExportFormatSection() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        // Export format radio buttons
        val savedFormat = prefs.getString(PREF_EXPORT_FORMAT, DEFAULT_EXPORT_FORMAT)
        when (savedFormat) {
            "PNG" -> binding.radioFormatPng.isChecked = true
            "JPEG" -> binding.radioFormatJpeg.isChecked = true
        }

        binding.radioGroupExportFormat.setOnCheckedChangeListener { _, checkedId ->
            val format = when (checkedId) {
                R.id.radioFormatPng -> "PNG"
                R.id.radioFormatJpeg -> "JPEG"
                else -> "PNG"
            }
            prefs.edit().putString(PREF_EXPORT_FORMAT, format).apply()
            updateJpegQualityVisibility(format == "JPEG")
        }

        // JPEG quality slider
        val savedQuality = prefs.getInt(PREF_JPEG_QUALITY, DEFAULT_JPEG_QUALITY)
        binding.sliderJpegQuality.value = savedQuality.toFloat()
        binding.textJpegQuality.text = "$savedQuality%"

        binding.sliderJpegQuality.addOnChangeListener { _, value, _ ->
            val quality = value.toInt()
            binding.textJpegQuality.text = "$quality%"
            prefs.edit().putInt(PREF_JPEG_QUALITY, quality).apply()
        }

        // Set initial visibility
        updateJpegQualityVisibility(savedFormat == "JPEG")
    }

    private fun updateJpegQualityVisibility(visible: Boolean) {
        val visibility = if (visible) View.VISIBLE else View.GONE
        binding.labelJpegQuality.visibility = visibility
        binding.layoutJpegQuality.visibility = visibility
    }

    private fun setupAboutSection() {
        binding.textVersion.text = getString(R.string.settings_version) + ": " + BuildConfig.VERSION_NAME
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
