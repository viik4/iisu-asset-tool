package com.iisu.assettool.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.core.widget.addTextChangedListener
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentExistingAssetsBinding
import com.iisu.assettool.util.AndroidAppInfo
import com.iisu.assettool.util.ArtworkScraper
import com.iisu.assettool.util.GameCache
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import com.iisu.assettool.util.ViewAnimationUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Fragment for browsing and managing existing generated icons.
 * Displays icons organized by platform with support for filtering,
 * selection, and batch re-scraping operations.
 */
class ExistingAssetsFragment : Fragment() {

    companion object {
        const val ANDROID_APPS_PLATFORM_KEY = "__ANDROID_APPS__"
    }

    private var _binding: FragmentExistingAssetsBinding? = null
    private val binding get() = _binding!!

    private lateinit var assetAdapter: ExistingAssetAdapter
    private lateinit var artworkScraper: ArtworkScraper

    private var allAssets: List<ExistingAsset> = emptyList()
    private var filteredAssets: List<ExistingAsset> = emptyList()
    private var platforms: List<String> = emptyList()
    private var currentPlatformFilter: String? = null
    private var currentSearchFilter: String = ""

    private var isScraping: Boolean = false
    private var scrapingJob: Job? = null
    private var scrapingCancelled = AtomicBoolean(false)
    private var currentPickerDialog: ArtworkPickerDialog? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentExistingAssetsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        artworkScraper = ArtworkScraper(requireContext())

        // Load SteamGridDB API key from settings
        val sgdbApiKey = SettingsFragment.getSteamGridDBApiKey(requireContext())
        if (sgdbApiKey != null) {
            artworkScraper.setSteamGridDBApiKey(sgdbApiKey)
        }

        setupUI()
        setupRecyclerView()
        loadAssets()
    }

    private fun setupUI() {
        // Refresh button
        binding.btnRefresh.setOnClickListener {
            loadAssets(forceRefresh = true)
        }

        // Search filter
        binding.editSearch.addTextChangedListener { text ->
            currentSearchFilter = text?.toString() ?: ""
            applyFilters()
        }

        // Platform dropdown
        binding.spinnerPlatform.setOnItemClickListener { _, _, position, _ ->
            currentPlatformFilter = if (position == 0) null else platforms.getOrNull(position - 1)
            applyFilters()
        }

        // Selection buttons
        binding.btnSelectAll.setOnClickListener {
            assetAdapter.selectAll()
        }

        binding.btnSelectNone.setOnClickListener {
            assetAdapter.selectNone()
        }

        // Re-scrape button
        binding.btnRescrapeSelected.setOnClickListener {
            rescrapeSelected()
        }

        // Cancel button
        binding.btnCancelScraping.setOnClickListener {
            cancelScraping()
        }
    }

    private fun setupRecyclerView() {
        assetAdapter = ExistingAssetAdapter(
            onAssetClick = { _ ->
                // Click just toggles selection, already handled in adapter
            },
            onAssetLongClick = { asset ->
                // Long click - show options for single asset
                showAssetOptions(asset)
            },
            onSelectionChanged = { count ->
                updateSelectionInfo(count)
            }
        )

        // Calculate number of columns based on screen width
        val displayMetrics = resources.displayMetrics
        val screenWidth = displayMetrics.widthPixels / displayMetrics.density
        val columnWidth = 148 // item width (140) + margin (8)
        val columns = ((screenWidth - 16) / columnWidth).toInt().coerceAtLeast(2)

        binding.recyclerViewAssets.apply {
            layoutManager = GridLayoutManager(requireContext(), columns)
            adapter = assetAdapter
            ViewAnimationUtils.applyLayoutAnimation(this)
        }
    }

    private fun loadAssets(forceRefresh: Boolean = false) {
        ViewAnimationUtils.fadeIn(binding.loadingIndicator, 150)
        ViewAnimationUtils.fadeOut(binding.layoutEmptyState)
        ViewAnimationUtils.fadeOut(binding.recyclerViewAssets)
        binding.textStatus.text = getString(R.string.existing_assets_scanning)

        viewLifecycleOwner.lifecycleScope.launch {
            val assets = mutableListOf<ExistingAsset>()
            val platformSet = mutableSetOf<String>()

            withContext(Dispatchers.IO) {
                // Get all platforms with content
                val platformList = IisuDirectoryManager.getPlatformsWithRoms()

                for (platform in platformList) {
                    // Get games for this platform
                    val games = if (forceRefresh) {
                        GameCache.invalidatePlatform(platform)
                        GameCache.getGamesForPlatform(platform, forceRefresh = true)
                    } else {
                        GameCache.getGamesForPlatform(platform)
                    }

                    // Find games with icons
                    for (game in games) {
                        if (game.hasIcon && game.iconFile != null) {
                            assets.add(
                                ExistingAsset(
                                    iconPath = game.iconFile,
                                    gameTitle = game.displayName,
                                    platformKey = platform,
                                    platformDisplayName = getPlatformDisplayName(platform)
                                )
                            )
                            platformSet.add(platform)
                        }
                    }
                }

                // Load Android apps with configured path
                val androidAppsPath = SettingsFragment.getAndroidAppsPath(requireContext())
                IisuDirectoryManager.setAndroidAppsPath(java.io.File(androidAppsPath))
                val androidApps = IisuDirectoryManager.getAndroidAppsWithIcons()
                for (app in androidApps) {
                    if (app.iconFile != null) {
                        assets.add(
                            ExistingAsset(
                                iconPath = app.iconFile,
                                gameTitle = app.displayName,
                                platformKey = ANDROID_APPS_PLATFORM_KEY,
                                platformDisplayName = "Android Apps",
                                isAndroidApp = true,
                                packageName = app.packageName
                            )
                        )
                        platformSet.add(ANDROID_APPS_PLATFORM_KEY)
                    }
                }
            }

            if (_binding == null) return@launch

            allAssets = assets.sortedWith(
                compareBy({ it.platformKey }, { it.gameTitle.lowercase() })
            )
            platforms = platformSet.sorted()

            // Setup platform dropdown
            val platformOptions = listOf("All Platforms") + platforms.map { getPlatformDisplayName(it) }
            val adapter = ArrayAdapter(
                requireContext(),
                android.R.layout.simple_dropdown_item_1line,
                platformOptions
            )
            binding.spinnerPlatform.setAdapter(adapter)

            ViewAnimationUtils.fadeOut(binding.loadingIndicator)

            if (allAssets.isEmpty()) {
                ViewAnimationUtils.fadeIn(binding.layoutEmptyState)
                ViewAnimationUtils.fadeOut(binding.recyclerViewAssets)
                binding.textPlatformCount.text = "0 platforms"
                binding.textAssetCount.text = "0 icons"
                binding.textStatus.text = getString(R.string.existing_assets_no_icons)
            } else {
                ViewAnimationUtils.fadeOut(binding.layoutEmptyState)
                ViewAnimationUtils.fadeIn(binding.recyclerViewAssets)
                applyFilters()
                binding.textPlatformCount.text = "${platforms.size} platforms"
                binding.textAssetCount.text = "${allAssets.size} icons"
                binding.textStatus.text = getString(R.string.existing_assets_ready)
            }
        }
    }

    private fun getPlatformDisplayName(platformKey: String): String {
        // Special case for Android apps
        if (platformKey == ANDROID_APPS_PLATFORM_KEY) {
            return "Android Apps"
        }
        // Convert platform folder names to display names
        return when (platformKey.lowercase()) {
            "nes", "famicom" -> "NES"
            "snes", "sfc" -> "SNES"
            "n64" -> "N64"
            "gc", "gamecube" -> "GameCube"
            "wii" -> "Wii"
            "wiiu" -> "Wii U"
            "switch" -> "Switch"
            "gb" -> "Game Boy"
            "gbc" -> "Game Boy Color"
            "gba" -> "Game Boy Advance"
            "nds" -> "Nintendo DS"
            "3ds" -> "Nintendo 3DS"
            "psx", "ps1", "playstation" -> "PlayStation"
            "ps2" -> "PlayStation 2"
            "ps3" -> "PlayStation 3"
            "psp" -> "PSP"
            "vita" -> "PS Vita"
            "genesis", "megadrive", "md" -> "Genesis"
            "sms", "mastersystem" -> "Master System"
            "gamegear", "gg" -> "Game Gear"
            "saturn" -> "Saturn"
            "dreamcast", "dc" -> "Dreamcast"
            "segacd", "scd" -> "Sega CD"
            "32x" -> "32X"
            "arcade", "mame", "fba" -> "Arcade"
            "neogeo", "neo-geo" -> "Neo Geo"
            "pcengine", "pce", "tg16", "turbografx" -> "TurboGrafx-16"
            "atari2600" -> "Atari 2600"
            "atari5200" -> "Atari 5200"
            "atari7800" -> "Atari 7800"
            "atarilynx", "lynx" -> "Atari Lynx"
            "jaguar" -> "Atari Jaguar"
            "dos" -> "DOS"
            "scummvm" -> "ScummVM"
            else -> platformKey.replaceFirstChar { it.uppercase() }
        }
    }

    private fun applyFilters() {
        filteredAssets = allAssets.filter { asset ->
            val matchesPlatform = currentPlatformFilter == null ||
                asset.platformKey == currentPlatformFilter

            val matchesSearch = currentSearchFilter.isBlank() ||
                asset.gameTitle.contains(currentSearchFilter, ignoreCase = true)

            matchesPlatform && matchesSearch
        }

        assetAdapter.submitList(filteredAssets)

        if (filteredAssets.isEmpty() && allAssets.isNotEmpty()) {
            binding.textStatus.text = "No matches for current filters"
        } else {
            binding.textStatus.text = "${filteredAssets.size} icons shown"
        }
    }

    private fun updateSelectionInfo(count: Int) {
        if (count > 0) {
            binding.textSelectionInfo.text = "$count selected"
            binding.btnRescrapeSelected.isEnabled = !isScraping
        } else {
            binding.textSelectionInfo.text = getString(R.string.existing_assets_hint)
            binding.btnRescrapeSelected.isEnabled = false
        }
    }

    private fun showAssetOptions(asset: ExistingAsset) {
        val options = arrayOf(
            "Re-scrape Icon",
            "View in folder"
        )

        AlertDialog.Builder(requireContext())
            .setTitle(asset.gameTitle)
            .setItems(options) { _, which ->
                when (which) {
                    0 -> rescrapeAsset(asset)
                    1 -> {
                        Toast.makeText(
                            requireContext(),
                            "Path: ${asset.iconPath.parent}",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun rescrapeAsset(asset: ExistingAsset) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        // Create a temporary GameInfo for the asset
        val gameFolder = asset.iconPath.parentFile ?: return
        val gameInfo = GameInfo(
            name = gameFolder.name,
            folder = gameFolder,
            hasIcon = true,
            iconFile = asset.iconPath
        )

        Toast.makeText(requireContext(), "Searching for icons...", Toast.LENGTH_SHORT).show()

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptions(gameInfo, asset.platformKey)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No icons found for ${asset.gameTitle}",
                    Toast.LENGTH_SHORT
                ).show()
                return@launch
            }

            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                currentPickerDialog = ArtworkPickerDialog.showWithFilter(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                    searchResult = searchResult,
                    onOptionSelected = { selectedOption ->
                        viewLifecycleOwner.lifecycleScope.launch innerLaunch@{
                            val success = artworkScraper.saveIconFromOption(
                                selectedOption,
                                gameInfo,
                                asset.platformKey
                            )
                            if (_binding == null) return@innerLaunch

                            if (success) {
                                Toast.makeText(
                                    requireContext(),
                                    "Icon saved for ${asset.gameTitle}",
                                    Toast.LENGTH_SHORT
                                ).show()
                                loadAssets(forceRefresh = true)
                            } else {
                                Toast.makeText(
                                    requireContext(),
                                    "Failed to save icon",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        }
                    },
                    onFilterChanged = { newSquareOnly ->
                        // Fetch new results with the updated filter
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptions(gameInfo, asset.platformKey, newSquareOnly)
                            withContext(Dispatchers.Main) {
                                currentPickerDialog?.updateSearchResult(newResult)
                            }
                        }
                    }
                )
            }
        }
    }

    private fun rescrapeSelected() {
        val selected = assetAdapter.getSelectedAssets()
        if (selected.isEmpty()) {
            Toast.makeText(requireContext(), "No assets selected", Toast.LENGTH_SHORT).show()
            return
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Re-scrape Icons")
            .setMessage(
                "Re-scrape ${selected.size} selected icon(s)?\n\n" +
                "This will use automatic mode (first result) for each game."
            )
            .setPositiveButton("Re-scrape") { _, _ ->
                performBatchRescrape(selected)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun performBatchRescrape(assets: List<ExistingAsset>) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())

        scrapingCancelled.set(false)
        setScrapingState(true)

        Toast.makeText(
            requireContext(),
            "Re-scraping ${assets.size} icons ($parallelCount parallel)...",
            Toast.LENGTH_LONG
        ).show()

        scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
            val successCount = AtomicInteger(0)
            val failCount = AtomicInteger(0)
            val completedCount = AtomicInteger(0)
            val totalAssets = assets.size

            val semaphore = Semaphore(parallelCount)

            try {
                val jobs = assets.map { asset ->
                    async(Dispatchers.IO) {
                        if (scrapingCancelled.get() || !isActive) return@async

                        semaphore.withPermit {
                            if (scrapingCancelled.get() || !isActive) return@withPermit

                            val gameFolder = asset.iconPath.parentFile ?: return@withPermit
                            val gameInfo = GameInfo(
                                name = gameFolder.name,
                                folder = gameFolder,
                                hasIcon = true,
                                iconFile = asset.iconPath
                            )

                            val success = artworkScraper.scrapeIcon(gameInfo, asset.platformKey)
                            if (success) successCount.incrementAndGet() else failCount.incrementAndGet()

                            val completed = completedCount.incrementAndGet()
                            if (!scrapingCancelled.get() && _binding != null) {
                                withContext(Dispatchers.Main) {
                                    binding.progressBar.progress = (completed * 100) / totalAssets
                                    binding.textStatus.text = "Re-scraping: $completed/$totalAssets..."
                                }
                            }
                        }
                    }
                }

                jobs.awaitAll()

                if (!scrapingCancelled.get()) {
                    finishScraping(
                        "Re-scraped: ${successCount.get()} found, ${failCount.get()} not found",
                        wasCancelled = false
                    )
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                scrapingCancelled.set(false)
            } catch (e: Exception) {
                if (!scrapingCancelled.get()) {
                    finishScraping("Error: ${e.message}")
                }
            }
        }
    }

    private fun cancelScraping() {
        if (isScraping) {
            scrapingCancelled.set(true)
            scrapingJob?.cancel()

            setScrapingState(false)
            scrapingJob = null

            Toast.makeText(requireContext(), "Scraping cancelled", Toast.LENGTH_SHORT).show()
            loadAssets(forceRefresh = true)
        }
    }

    private fun setScrapingState(scraping: Boolean) {
        isScraping = scraping

        if (_binding == null) return

        binding.btnCancelScraping.visibility = if (scraping) View.VISIBLE else View.GONE
        binding.progressBar.visibility = if (scraping) View.VISIBLE else View.GONE
        binding.progressBar.progress = 0

        val enabled = !scraping
        binding.btnRefresh.isEnabled = enabled
        binding.btnRefresh.alpha = if (enabled) 1.0f else 0.5f
        binding.btnSelectAll.isEnabled = enabled
        binding.btnSelectNone.isEnabled = enabled
        binding.btnRescrapeSelected.isEnabled = enabled && assetAdapter.getSelectedCount() > 0
    }

    private fun finishScraping(message: String, wasCancelled: Boolean = false) {
        setScrapingState(false)
        scrapingJob = null
        scrapingCancelled.set(false)

        if (_binding != null) {
            val toastMessage = if (wasCancelled) "Scraping cancelled. $message" else message
            Toast.makeText(requireContext(), toastMessage, Toast.LENGTH_LONG).show()
        }

        loadAssets(forceRefresh = true)
        assetAdapter.selectNone()
    }

    override fun onDestroyView() {
        if (isScraping) {
            scrapingCancelled.set(true)
            scrapingJob?.cancel()
            isScraping = false
        }

        super.onDestroyView()
        _binding = null
    }
}
