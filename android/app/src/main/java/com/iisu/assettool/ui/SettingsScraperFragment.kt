package com.iisu.assettool.ui

import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import com.iisu.assettool.databinding.FragmentSettingsScraperBinding
import com.iisu.assettool.util.ArtworkSource
import com.iisu.assettool.util.SourcePriorityAdapter
import org.json.JSONArray
import org.json.JSONObject

/**
 * Scraper Options settings tab.
 * Contains: Generation settings, Extended Assets (DS Mode), Source Priority, Fallback settings
 */
class SettingsScraperFragment : Fragment() {

    private var _binding: FragmentSettingsScraperBinding? = null
    private val binding get() = _binding!!

    private var sourcePriorityAdapter: SourcePriorityAdapter? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsScraperBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupGenerationSettings()
        setupExtendedAssets()
        setupSourcePriority()
        setupFallbackSettings()
    }

    private fun setupGenerationSettings() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Parallel downloads slider
        val parallelDownloads = prefs.getInt(
            SettingsFragment.PREF_PARALLEL_DOWNLOADS,
            SettingsFragment.DEFAULT_PARALLEL_DOWNLOADS
        )
        binding.sliderParallelDownloads.value = parallelDownloads.toFloat()
        binding.textParallelCount.text = parallelDownloads.toString()

        binding.sliderParallelDownloads.addOnChangeListener { _, value, _ ->
            val count = value.toInt()
            binding.textParallelCount.text = count.toString()
            prefs.edit().putInt(SettingsFragment.PREF_PARALLEL_DOWNLOADS, count).apply()
        }

        // Interactive mode toggle
        val interactiveMode = prefs.getBoolean(
            SettingsFragment.PREF_INTERACTIVE_MODE,
            SettingsFragment.DEFAULT_INTERACTIVE_MODE
        )
        binding.switchInteractiveMode.isChecked = interactiveMode

        binding.rowInteractiveMode.setOnClickListener {
            binding.switchInteractiveMode.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_INTERACTIVE_MODE,
                binding.switchInteractiveMode.isChecked
            ).apply()
        }

        // Allow non-square icons toggle (inverse of "square only")
        val squareOnly = prefs.getBoolean(
            SettingsFragment.PREF_SQUARE_ICONS_ONLY,
            SettingsFragment.DEFAULT_SQUARE_ICONS_ONLY
        )
        binding.switchAllowNonSquareIcons.isChecked = !squareOnly  // Inverted - "allow non-square" is opposite of "square only"

        binding.rowAllowNonSquareIcons.setOnClickListener {
            binding.switchAllowNonSquareIcons.toggle()
            // Save inverted - if "allow non-square" is ON, "square only" should be OFF
            prefs.edit().putBoolean(
                SettingsFragment.PREF_SQUARE_ICONS_ONLY,
                !binding.switchAllowNonSquareIcons.isChecked
            ).apply()
        }

        // Deep search toggle
        val deepSearch = prefs.getBoolean(
            SettingsFragment.PREF_DEEP_SEARCH,
            SettingsFragment.DEFAULT_DEEP_SEARCH
        )
        binding.switchDeepSearch.isChecked = deepSearch

        binding.rowDeepSearch.setOnClickListener {
            binding.switchDeepSearch.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_DEEP_SEARCH,
                binding.switchDeepSearch.isChecked
            ).apply()
        }
    }

    private fun setupExtendedAssets() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // DS Mode toggle
        val dsMode = prefs.getBoolean(
            SettingsFragment.PREF_DS_MODE,
            SettingsFragment.DEFAULT_DS_MODE
        )
        binding.switchDsMode.isChecked = dsMode
        binding.layoutDsOptions.visibility = if (dsMode) View.VISIBLE else View.GONE

        binding.rowDsMode.setOnClickListener {
            binding.switchDsMode.toggle()
            val enabled = binding.switchDsMode.isChecked
            prefs.edit().putBoolean(SettingsFragment.PREF_DS_MODE, enabled).apply()
            binding.layoutDsOptions.visibility = if (enabled) View.VISIBLE else View.GONE
        }

        // DS Mode sub-options
        setupDsSubOptions(prefs)
    }

    private fun setupDsSubOptions(prefs: android.content.SharedPreferences) {
        // Logos
        val scrapeLogos = prefs.getBoolean(
            SettingsFragment.PREF_SCRAPE_LOGOS,
            SettingsFragment.DEFAULT_SCRAPE_LOGOS
        )
        binding.switchScrapeLogos.isChecked = scrapeLogos

        binding.rowScrapeLogos.setOnClickListener {
            binding.switchScrapeLogos.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_SCRAPE_LOGOS,
                binding.switchScrapeLogos.isChecked
            ).apply()
        }

        // Logo Fallback to Boxart
        val logoFallbackBoxart = prefs.getBoolean(
            SettingsFragment.PREF_LOGO_FALLBACK_BOXART,
            SettingsFragment.DEFAULT_LOGO_FALLBACK_BOXART
        )
        binding.switchLogoFallbackBoxart.isChecked = logoFallbackBoxart

        binding.rowLogoFallbackBoxart.setOnClickListener {
            binding.switchLogoFallbackBoxart.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_LOGO_FALLBACK_BOXART,
                binding.switchLogoFallbackBoxart.isChecked
            ).apply()
        }

        // Hero images
        val heroEnabled = prefs.getBoolean(
            SettingsFragment.PREF_HERO_ENABLED,
            SettingsFragment.DEFAULT_HERO_ENABLED
        )
        binding.switchHeroEnabled.isChecked = heroEnabled
        binding.layoutHeroCount.visibility = if (heroEnabled) View.VISIBLE else View.GONE
        binding.rowHeroCrop.visibility = if (heroEnabled) View.VISIBLE else View.GONE

        binding.rowHeroEnabled.setOnClickListener {
            binding.switchHeroEnabled.toggle()
            val enabled = binding.switchHeroEnabled.isChecked
            prefs.edit().putBoolean(SettingsFragment.PREF_HERO_ENABLED, enabled).apply()
            binding.layoutHeroCount.visibility = if (enabled) View.VISIBLE else View.GONE
            binding.rowHeroCrop.visibility = if (enabled) View.VISIBLE else View.GONE
        }

        // Hero count slider
        val heroCount = prefs.getInt(
            SettingsFragment.PREF_HERO_COUNT,
            SettingsFragment.DEFAULT_HERO_COUNT
        )
        binding.sliderHeroCount.value = heroCount.toFloat()
        binding.textHeroCount.text = heroCount.toString()

        binding.sliderHeroCount.addOnChangeListener { _, value, _ ->
            val count = value.toInt()
            binding.textHeroCount.text = count.toString()
            prefs.edit().putInt(SettingsFragment.PREF_HERO_COUNT, count).apply()
        }

        // Hero crop
        val heroCrop = prefs.getBoolean(
            SettingsFragment.PREF_HERO_CROP_ENABLED,
            SettingsFragment.DEFAULT_HERO_CROP_ENABLED
        )
        binding.switchHeroCrop.isChecked = heroCrop

        binding.rowHeroCrop.setOnClickListener {
            binding.switchHeroCrop.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_HERO_CROP_ENABLED,
                binding.switchHeroCrop.isChecked
            ).apply()
        }

        // Screenshots
        val screenshotsEnabled = prefs.getBoolean(
            SettingsFragment.PREF_SCREENSHOTS_ENABLED,
            SettingsFragment.DEFAULT_SCREENSHOTS_ENABLED
        )
        binding.switchScreenshotsEnabled.isChecked = screenshotsEnabled
        binding.layoutScreenshotCount.visibility = if (screenshotsEnabled) View.VISIBLE else View.GONE

        binding.rowScreenshotsEnabled.setOnClickListener {
            binding.switchScreenshotsEnabled.toggle()
            val enabled = binding.switchScreenshotsEnabled.isChecked
            prefs.edit().putBoolean(SettingsFragment.PREF_SCREENSHOTS_ENABLED, enabled).apply()
            binding.layoutScreenshotCount.visibility = if (enabled) View.VISIBLE else View.GONE
        }

        // Screenshot count slider
        val screenshotCount = prefs.getInt(
            SettingsFragment.PREF_SCREENSHOT_COUNT,
            SettingsFragment.DEFAULT_SCREENSHOT_COUNT
        )
        binding.sliderScreenshotCount.value = screenshotCount.toFloat()
        binding.textScreenshotCount.text = screenshotCount.toString()

        binding.sliderScreenshotCount.addOnChangeListener { _, value, _ ->
            val count = value.toInt()
            binding.textScreenshotCount.text = count.toString()
            prefs.edit().putInt(SettingsFragment.PREF_SCREENSHOT_COUNT, count).apply()
        }
    }

    private fun setupSourcePriority() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Load source priority
        val sources = loadSourcePriority(prefs)

        sourcePriorityAdapter = SourcePriorityAdapter { updatedSources ->
            saveSourcePriority(prefs, updatedSources)
        }

        binding.recyclerSourcePriority.apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = sourcePriorityAdapter
        }

        sourcePriorityAdapter?.setSources(sources)
        sourcePriorityAdapter?.attachToRecyclerView(binding.recyclerSourcePriority)

        // Enable all button
        binding.btnEnableAllSources.setOnClickListener {
            sourcePriorityAdapter?.enableAll()
        }

        // Disable all button
        binding.btnDisableAllSources.setOnClickListener {
            sourcePriorityAdapter?.disableAll()
        }
    }

    private fun loadSourcePriority(prefs: android.content.SharedPreferences): MutableList<ArtworkSource> {
        val json = prefs.getString(SettingsFragment.PREF_SOURCE_PRIORITY, null)

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

                // Add any new default sources that aren't in saved preferences
                val savedIds = sources.map { it.id }.toSet()
                ArtworkSource.getDefaultSources().forEach { source ->
                    if (source.id !in savedIds) {
                        sources.add(source)
                    }
                }

                sources
            } catch (e: Exception) {
                ArtworkSource.getDefaultSources().toMutableList()
            }
        } else {
            ArtworkSource.getDefaultSources().toMutableList()
        }
    }

    private fun saveSourcePriority(prefs: android.content.SharedPreferences, sources: List<ArtworkSource>) {
        val array = JSONArray()
        sources.forEach { source ->
            val obj = JSONObject().apply {
                put("id", source.id)
                put("enabled", source.enabled)
            }
            array.put(obj)
        }
        prefs.edit().putString(SettingsFragment.PREF_SOURCE_PRIORITY, array.toString()).apply()
    }

    private fun setupFallbackSettings() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Platform icon fallback
        val useFallback = prefs.getBoolean(
            SettingsFragment.PREF_USE_FALLBACK,
            SettingsFragment.DEFAULT_USE_FALLBACK
        )
        binding.switchUseFallback.isChecked = useFallback

        binding.rowUseFallback.setOnClickListener {
            binding.switchUseFallback.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_USE_FALLBACK,
                binding.switchUseFallback.isChecked
            ).apply()
        }

        // Skip scraping
        val skipScraping = prefs.getBoolean(
            SettingsFragment.PREF_SKIP_SCRAPING,
            SettingsFragment.DEFAULT_SKIP_SCRAPING
        )
        binding.switchSkipScraping.isChecked = skipScraping

        binding.rowSkipScraping.setOnClickListener {
            binding.switchSkipScraping.toggle()
            prefs.edit().putBoolean(
                SettingsFragment.PREF_SKIP_SCRAPING,
                binding.switchSkipScraping.isChecked
            ).apply()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        sourcePriorityAdapter = null
        _binding = null
    }
}
