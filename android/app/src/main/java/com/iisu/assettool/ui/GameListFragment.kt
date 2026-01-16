package com.iisu.assettool.ui

import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentGameListBinding
import com.iisu.assettool.util.ArtworkScraper
import com.iisu.assettool.util.GameAdapter
import com.iisu.assettool.util.GameCache
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Fragment for displaying and managing games within a platform.
 * Shows a list of games with options to generate icons and covers.
 */
class GameListFragment : Fragment() {

    private var _binding: FragmentGameListBinding? = null
    private val binding get() = _binding!!

    private lateinit var gameAdapter: GameAdapter
    private lateinit var artworkScraper: ArtworkScraper

    private var platformName: String = ""
    private var platformDisplayName: String = ""
    private var games: List<GameInfo> = emptyList()
    private var isScraping: Boolean = false

    // Track active scraping job for cancellation
    private var scrapingJob: Job? = null
    private var scrapingCancelled = AtomicBoolean(false)

    companion object {
        private const val ARG_PLATFORM_NAME = "platform_name"
        private const val ARG_PLATFORM_DISPLAY_NAME = "platform_display_name"

        fun newInstance(platformName: String, platformDisplayName: String): GameListFragment {
            return GameListFragment().apply {
                arguments = Bundle().apply {
                    putString(ARG_PLATFORM_NAME, platformName)
                    putString(ARG_PLATFORM_DISPLAY_NAME, platformDisplayName)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        arguments?.let {
            platformName = it.getString(ARG_PLATFORM_NAME, "")
            platformDisplayName = it.getString(ARG_PLATFORM_DISPLAY_NAME, "")
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentGameListBinding.inflate(inflater, container, false)
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
        loadGames()
    }

    private fun setupUI() {
        // Set platform name
        binding.textPlatformName.text = platformDisplayName

        // Load platform icon
        val platformIconFile = IisuDirectoryManager.getPlatformIcon(platformName)
        if (platformIconFile.exists()) {
            val bitmap = BitmapFactory.decodeFile(platformIconFile.absolutePath)
            if (bitmap != null) {
                binding.imagePlatformIcon.setImageBitmap(bitmap)
            } else {
                binding.imagePlatformIcon.setImageResource(R.drawable.ic_iisu_home)
            }
        } else {
            binding.imagePlatformIcon.setImageResource(R.drawable.ic_iisu_home)
        }

        // Back button
        binding.btnBack.setOnClickListener {
            parentFragmentManager.popBackStack()
        }

        // Bulk generate all assets button
        binding.btnBulkGenerate.setOnClickListener {
            showBulkGenerateDialog()
        }

        // Scrape all icons button
        binding.btnScrapeAllIcons.setOnClickListener {
            scrapeAllMissingIcons()
        }

        // Scrape all heroes button
        binding.btnScrapeAllHeroes.setOnClickListener {
            scrapeAllMissingHeroes()
        }

        // Scrape all logos button
        binding.btnScrapeAllLogos.setOnClickListener {
            scrapeAllMissingLogos()
        }

        // Scrape all screenshots button
        binding.btnScrapeAllScreenshots.setOnClickListener {
            scrapeAllScreenshots()
        }

        // Cancel scraping button
        binding.btnCancelScraping.setOnClickListener {
            cancelScraping()
        }
    }

    /**
     * Cancel any active scraping operation
     */
    private fun cancelScraping() {
        if (isScraping) {
            scrapingCancelled.set(true)
            scrapingJob?.cancel()

            // Immediately update UI - don't wait for network operations to finish
            setScrapingState(false)
            scrapingJob = null

            Toast.makeText(requireContext(), "Scraping cancelled", Toast.LENGTH_SHORT).show()
            refreshGameList()
        }
    }

    /**
     * Update UI to reflect scraping state
     */
    private fun setScrapingState(scraping: Boolean) {
        isScraping = scraping

        if (_binding == null) return

        // Show/hide cancel button
        binding.btnCancelScraping.visibility = if (scraping) View.VISIBLE else View.GONE

        // Show/hide progress bar
        binding.progressBar.visibility = if (scraping) View.VISIBLE else View.GONE

        // Enable/disable action buttons during scraping
        val enabled = !scraping
        binding.btnBulkGenerate.isEnabled = enabled
        binding.btnBulkGenerate.alpha = if (enabled) 1.0f else 0.5f
        binding.btnScrapeAllIcons.isEnabled = enabled
        binding.btnScrapeAllIcons.alpha = if (enabled) 1.0f else 0.5f
        binding.btnScrapeAllHeroes.isEnabled = enabled
        binding.btnScrapeAllHeroes.alpha = if (enabled) 1.0f else 0.5f
        binding.btnScrapeAllLogos.isEnabled = enabled
        binding.btnScrapeAllLogos.alpha = if (enabled) 1.0f else 0.5f
        binding.btnScrapeAllScreenshots.isEnabled = enabled
        binding.btnScrapeAllScreenshots.alpha = if (enabled) 1.0f else 0.5f
    }

    /**
     * Clean up after scraping completes or is cancelled
     */
    private fun finishScraping(message: String, wasCancelled: Boolean = false) {
        setScrapingState(false)
        scrapingJob = null
        scrapingCancelled.set(false)

        if (_binding != null) {
            val toastMessage = if (wasCancelled) "Scraping cancelled. $message" else message
            Toast.makeText(requireContext(), toastMessage, Toast.LENGTH_LONG).show()
        }

        refreshGameList()
    }

    private fun setupRecyclerView() {
        gameAdapter = GameAdapter(
            onGenerateIcon = { game -> generateIconForGame(game) },
            onGenerateHero = { game -> generateHeroForGame(game) },
            onGenerateLogo = { game -> generateLogoForGame(game) }
        )

        binding.recyclerViewGames.apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = gameAdapter
        }
    }

    private fun loadGames(forceRefresh: Boolean = false) {
        binding.progressBar.visibility = View.VISIBLE
        binding.textEmptyState.visibility = View.GONE

        viewLifecycleOwner.lifecycleScope.launch {
            val startTime = System.currentTimeMillis()

            // Use cached games for fast loading
            games = GameCache.getGamesForPlatform(platformName, forceRefresh)

            val loadTime = System.currentTimeMillis() - startTime
            android.util.Log.d("GameListFragment", "Loaded ${games.size} games in ${loadTime}ms")

            if (_binding == null) return@launch

            binding.progressBar.visibility = View.GONE

            if (games.isEmpty()) {
                binding.textEmptyState.visibility = View.VISIBLE
                binding.recyclerViewGames.visibility = View.GONE
            } else {
                binding.textEmptyState.visibility = View.GONE
                binding.recyclerViewGames.visibility = View.VISIBLE
                gameAdapter.submitList(games)
            }

            updateStats()
        }
    }

    private fun updateStats() {
        val gameCount = games.size
        val missingIcons = games.count { !it.hasIcon }
        val missingHeroes = games.count { !it.hasHero }
        val missingLogos = games.count { !it.hasLogo }
        val totalMissing = missingIcons + missingHeroes + missingLogos

        binding.textGameCount.text = "$gameCount games"
        binding.textAssetStats.text = if (totalMissing > 0) "$totalMissing missing assets" else "All assets present"

        // Bulk buttons are always enabled when there are games (can regenerate existing assets)
        val hasGames = gameCount > 0
        binding.btnScrapeAllIcons.isEnabled = hasGames
        binding.btnScrapeAllIcons.alpha = if (hasGames) 1.0f else 0.5f
        binding.btnScrapeAllHeroes.isEnabled = hasGames
        binding.btnScrapeAllHeroes.alpha = if (hasGames) 1.0f else 0.5f
        binding.btnScrapeAllLogos.isEnabled = hasGames
        binding.btnScrapeAllLogos.alpha = if (hasGames) 1.0f else 0.5f
        binding.btnScrapeAllScreenshots.isEnabled = hasGames
        binding.btnScrapeAllScreenshots.alpha = if (hasGames) 1.0f else 0.5f
        binding.btnBulkGenerate.isEnabled = hasGames
        binding.btnBulkGenerate.alpha = if (hasGames) 1.0f else 0.5f
    }

    private fun generateIconForGame(game: GameInfo) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(
            requireContext(),
            "Searching for icons...",
            Toast.LENGTH_SHORT
        ).show()

        viewLifecycleOwner.lifecycleScope.launch {
            // Search for artwork options
            val searchResult = artworkScraper.searchIconOptions(game, platformName)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No icons found for ${game.name}",
                    Toast.LENGTH_SHORT
                ).show()
                return@launch
            }

            // Show picker dialog with options
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                    searchResult = searchResult
                ) { selectedOption ->
                    // Save selected option with iiSU border
                    viewLifecycleOwner.lifecycleScope.launch {
                        val success = artworkScraper.saveIconFromOption(selectedOption, game, platformName)
                        if (_binding == null) return@launch

                        if (success) {
                            Toast.makeText(
                                requireContext(),
                                "Icon saved with border for ${game.name}",
                                Toast.LENGTH_SHORT
                            ).show()
                            refreshGameList()
                        } else {
                            Toast.makeText(
                                requireContext(),
                                "Failed to save icon",
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    }
                }
            }
        }
    }

    private fun generateHeroForGame(game: GameInfo) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(
            requireContext(),
            "Searching for heroes...",
            Toast.LENGTH_SHORT
        ).show()

        viewLifecycleOwner.lifecycleScope.launch {
            // Search for hero options
            val searchResult = artworkScraper.searchHeroOptions(game, platformName)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No heroes found for ${game.name}",
                    Toast.LENGTH_SHORT
                ).show()
                return@launch
            }

            // Show picker dialog with options
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.HERO,
                    searchResult = searchResult
                ) { selectedOption ->
                    // Save selected option
                    viewLifecycleOwner.lifecycleScope.launch {
                        val success = artworkScraper.saveHeroFromOption(selectedOption, game)
                        if (_binding == null) return@launch

                        if (success) {
                            Toast.makeText(
                                requireContext(),
                                "Hero saved for ${game.name}",
                                Toast.LENGTH_SHORT
                            ).show()
                            refreshGameList()
                        } else {
                            Toast.makeText(
                                requireContext(),
                                "Failed to save hero",
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    }
                }
            }
        }
    }

    private fun generateLogoForGame(game: GameInfo) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(
            requireContext(),
            "Searching for logos...",
            Toast.LENGTH_SHORT
        ).show()

        viewLifecycleOwner.lifecycleScope.launch {
            // Search for logo options
            val searchResult = artworkScraper.searchLogoOptions(game, platformName)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No logos found for ${game.name}",
                    Toast.LENGTH_SHORT
                ).show()
                return@launch
            }

            // Show picker dialog with options
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.LOGO,
                    searchResult = searchResult
                ) { selectedOption ->
                    // Save selected option
                    viewLifecycleOwner.lifecycleScope.launch {
                        val success = artworkScraper.saveLogoFromOption(selectedOption, game)
                        if (_binding == null) return@launch

                        if (success) {
                            Toast.makeText(
                                requireContext(),
                                "Logo saved for ${game.name}",
                                Toast.LENGTH_SHORT
                            ).show()
                            refreshGameList()
                        } else {
                            Toast.makeText(
                                requireContext(),
                                "Failed to save logo",
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    }
                }
            }
        }
    }

    private fun scrapeAllMissingIcons() {
        if (games.isEmpty()) {
            Toast.makeText(requireContext(), "No games to process", Toast.LENGTH_SHORT).show()
            return
        }

        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())

        scrapingCancelled.set(false)
        setScrapingState(true)

        Toast.makeText(
            requireContext(),
            "Generating icons for ${games.size} games ($parallelCount parallel)...",
            Toast.LENGTH_LONG
        ).show()

        scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
            val successCount = AtomicInteger(0)
            val failCount = AtomicInteger(0)
            val completedCount = AtomicInteger(0)
            val totalGames = games.size

            val semaphore = Semaphore(parallelCount)

            try {
                val jobs = games.map { game ->
                    async(Dispatchers.IO) {
                        if (scrapingCancelled.get() || !isActive) return@async

                        semaphore.withPermit {
                            if (scrapingCancelled.get() || !isActive) return@withPermit

                            val success = artworkScraper.scrapeIcon(game, platformName)
                            if (success) successCount.incrementAndGet() else failCount.incrementAndGet()

                            val completed = completedCount.incrementAndGet()
                            if (!scrapingCancelled.get() && _binding != null) {
                                withContext(Dispatchers.Main) {
                                    binding.textAssetStats.text = "Icons: $completed/$totalGames..."
                                }
                            }
                        }
                    }
                }

                jobs.awaitAll()

                // Only finish if not already cancelled (cancel button handles UI)
                if (!scrapingCancelled.get()) {
                    finishScraping(
                        "Icons: ${successCount.get()} found, ${failCount.get()} not found",
                        wasCancelled = false
                    )
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Job was cancelled - UI already updated by cancelScraping()
                // Just clean up the flag
                scrapingCancelled.set(false)
            } catch (e: Exception) {
                if (!scrapingCancelled.get()) {
                    finishScraping("Error: ${e.message}")
                }
            }
        }
    }

    private fun scrapeAllMissingHeroes() {
        if (games.isEmpty()) {
            Toast.makeText(requireContext(), "No games to process", Toast.LENGTH_SHORT).show()
            return
        }

        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())

        scrapingCancelled.set(false)
        setScrapingState(true)

        Toast.makeText(
            requireContext(),
            "Generating heroes for ${games.size} games ($parallelCount parallel)...",
            Toast.LENGTH_LONG
        ).show()

        scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
            val successCount = AtomicInteger(0)
            val failCount = AtomicInteger(0)
            val completedCount = AtomicInteger(0)
            val totalGames = games.size

            val semaphore = Semaphore(parallelCount)

            try {
                val jobs = games.map { game ->
                    async(Dispatchers.IO) {
                        if (scrapingCancelled.get() || !isActive) return@async

                        semaphore.withPermit {
                            if (scrapingCancelled.get() || !isActive) return@withPermit

                            val success = artworkScraper.scrapeHero(game, platformName)
                            if (success) successCount.incrementAndGet() else failCount.incrementAndGet()

                            val completed = completedCount.incrementAndGet()
                            if (!scrapingCancelled.get() && _binding != null) {
                                withContext(Dispatchers.Main) {
                                    binding.textAssetStats.text = "Heroes: $completed/$totalGames..."
                                }
                            }
                        }
                    }
                }

                jobs.awaitAll()

                // Only finish if not already cancelled (cancel button handles UI)
                if (!scrapingCancelled.get()) {
                    finishScraping(
                        "Heroes: ${successCount.get()} found, ${failCount.get()} not found",
                        wasCancelled = false
                    )
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Job was cancelled - UI already updated by cancelScraping()
                scrapingCancelled.set(false)
            } catch (e: Exception) {
                if (!scrapingCancelled.get()) {
                    finishScraping("Error: ${e.message}")
                }
            }
        }
    }

    private fun scrapeAllMissingLogos() {
        if (games.isEmpty()) {
            Toast.makeText(requireContext(), "No games to process", Toast.LENGTH_SHORT).show()
            return
        }

        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())

        scrapingCancelled.set(false)
        setScrapingState(true)

        Toast.makeText(
            requireContext(),
            "Generating logos for ${games.size} games ($parallelCount parallel)...",
            Toast.LENGTH_LONG
        ).show()

        scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
            val successCount = AtomicInteger(0)
            val failCount = AtomicInteger(0)
            val completedCount = AtomicInteger(0)
            val totalGames = games.size

            val semaphore = Semaphore(parallelCount)

            try {
                val jobs = games.map { game ->
                    async(Dispatchers.IO) {
                        if (scrapingCancelled.get() || !isActive) return@async

                        semaphore.withPermit {
                            if (scrapingCancelled.get() || !isActive) return@withPermit

                            val success = artworkScraper.scrapeLogo(game, platformName)
                            if (success) successCount.incrementAndGet() else failCount.incrementAndGet()

                            val completed = completedCount.incrementAndGet()
                            if (!scrapingCancelled.get() && _binding != null) {
                                withContext(Dispatchers.Main) {
                                    binding.textAssetStats.text = "Logos: $completed/$totalGames..."
                                }
                            }
                        }
                    }
                }

                jobs.awaitAll()

                // Only finish if not already cancelled (cancel button handles UI)
                if (!scrapingCancelled.get()) {
                    finishScraping(
                        "Logos: ${successCount.get()} found, ${failCount.get()} not found",
                        wasCancelled = false
                    )
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Job was cancelled - UI already updated by cancelScraping()
                scrapingCancelled.set(false)
            } catch (e: Exception) {
                if (!scrapingCancelled.get()) {
                    finishScraping("Error: ${e.message}")
                }
            }
        }
    }

    private fun scrapeAllScreenshots() {
        // Check if screenshots are enabled in settings
        if (!SettingsFragment.isScreenshotsEnabled(requireContext())) {
            Toast.makeText(requireContext(), "Screenshots are disabled in settings", Toast.LENGTH_SHORT).show()
            return
        }

        if (games.isEmpty()) {
            Toast.makeText(requireContext(), "No games to process", Toast.LENGTH_SHORT).show()
            return
        }

        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())
        val screenshotCount = SettingsFragment.getScreenshotCount(requireContext())

        scrapingCancelled.set(false)
        setScrapingState(true)

        Toast.makeText(
            requireContext(),
            "Downloading $screenshotCount screenshots for ${games.size} games ($parallelCount parallel)...",
            Toast.LENGTH_LONG
        ).show()

        scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
            val successCount = AtomicInteger(0)
            val failCount = AtomicInteger(0)
            val completedCount = AtomicInteger(0)
            val totalGames = games.size

            val semaphore = Semaphore(parallelCount)

            try {
                val jobs = games.map { game ->
                    async(Dispatchers.IO) {
                        if (scrapingCancelled.get() || !isActive) return@async

                        semaphore.withPermit {
                            if (scrapingCancelled.get() || !isActive) return@withPermit

                            val success = artworkScraper.scrapeScreenshots(game, platformName)
                            if (success) successCount.incrementAndGet() else failCount.incrementAndGet()

                            val completed = completedCount.incrementAndGet()
                            if (!scrapingCancelled.get() && _binding != null) {
                                withContext(Dispatchers.Main) {
                                    binding.textAssetStats.text = "Screenshots: $completed/$totalGames..."
                                }
                            }
                        }
                    }
                }

                jobs.awaitAll()

                // Only finish if not already cancelled (cancel button handles UI)
                if (!scrapingCancelled.get()) {
                    finishScraping(
                        "Screenshots: ${successCount.get()} found, ${failCount.get()} not found",
                        wasCancelled = false
                    )
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Job was cancelled - UI already updated by cancelScraping()
                scrapingCancelled.set(false)
            } catch (e: Exception) {
                if (!scrapingCancelled.get()) {
                    finishScraping("Error: ${e.message}")
                }
            }
        }
    }

    private fun showBulkGenerateDialog() {
        val totalGames = games.size
        val totalAssets = totalGames * 3 // icons, heroes, logos
        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())
        val interactiveMode = SettingsFragment.isInteractiveModeEnabled(requireContext())

        val modeText = if (interactiveMode) "Interactive (picker for each game)" else "Automatic (first result)"

        val message = "This will generate/regenerate ALL assets for $totalGames games:\n\n" +
            "• $totalGames icons\n" +
            "• $totalGames heroes\n" +
            "• $totalGames logos\n\n" +
            "Total: $totalAssets assets\n" +
            "Parallel: $parallelCount downloads\n" +
            "Mode: $modeText\n\n" +
            "Existing assets will be replaced. Continue?"

        androidx.appcompat.app.AlertDialog.Builder(requireContext())
            .setTitle("Bulk Generate Assets")
            .setMessage(message)
            .setPositiveButton("Generate All") { _, _ ->
                if (interactiveMode) {
                    bulkGenerateInteractive()
                } else {
                    bulkGenerateAllAssets()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun bulkGenerateAllAssets() {
        if (games.isEmpty()) {
            Toast.makeText(requireContext(), "No games to process", Toast.LENGTH_SHORT).show()
            return
        }

        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        val parallelCount = SettingsFragment.getParallelDownloads(requireContext())
        val totalGames = games.size

        scrapingCancelled.set(false)
        setScrapingState(true)

        Toast.makeText(
            requireContext(),
            "Generating assets for $totalGames games ($parallelCount parallel)...",
            Toast.LENGTH_LONG
        ).show()

        scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
            val iconSuccess = AtomicInteger(0)
            val iconFail = AtomicInteger(0)
            val heroSuccess = AtomicInteger(0)
            val heroFail = AtomicInteger(0)
            val logoSuccess = AtomicInteger(0)
            val logoFail = AtomicInteger(0)

            val semaphore = Semaphore(parallelCount)

            try {
                // Generate icons for ALL games (parallel)
                if (!scrapingCancelled.get()) {
                    val completedIcons = AtomicInteger(0)
                    val iconJobs = games.map { game ->
                        async(Dispatchers.IO) {
                            if (scrapingCancelled.get() || !isActive) return@async

                            semaphore.withPermit {
                                if (scrapingCancelled.get() || !isActive) return@withPermit

                                val success = artworkScraper.scrapeIcon(game, platformName)
                                if (success) iconSuccess.incrementAndGet() else iconFail.incrementAndGet()

                                val completed = completedIcons.incrementAndGet()
                                if (!scrapingCancelled.get() && _binding != null) {
                                    withContext(Dispatchers.Main) {
                                        binding.textAssetStats.text = "Icons: $completed/$totalGames..."
                                    }
                                }
                            }
                        }
                    }
                    iconJobs.awaitAll()
                }

                // Generate heroes for ALL games (parallel)
                if (!scrapingCancelled.get()) {
                    val completedHeroes = AtomicInteger(0)
                    val heroJobs = games.map { game ->
                        async(Dispatchers.IO) {
                            if (scrapingCancelled.get() || !isActive) return@async

                            semaphore.withPermit {
                                if (scrapingCancelled.get() || !isActive) return@withPermit

                                val success = artworkScraper.scrapeHero(game, platformName)
                                if (success) heroSuccess.incrementAndGet() else heroFail.incrementAndGet()

                                val completed = completedHeroes.incrementAndGet()
                                if (!scrapingCancelled.get() && _binding != null) {
                                    withContext(Dispatchers.Main) {
                                        binding.textAssetStats.text = "Heroes: $completed/$totalGames..."
                                    }
                                }
                            }
                        }
                    }
                    heroJobs.awaitAll()
                }

                // Generate logos for ALL games (parallel)
                if (!scrapingCancelled.get()) {
                    val completedLogos = AtomicInteger(0)
                    val logoJobs = games.map { game ->
                        async(Dispatchers.IO) {
                            if (scrapingCancelled.get() || !isActive) return@async

                            semaphore.withPermit {
                                if (scrapingCancelled.get() || !isActive) return@withPermit

                                val success = artworkScraper.scrapeLogo(game, platformName)
                                if (success) logoSuccess.incrementAndGet() else logoFail.incrementAndGet()

                                val completed = completedLogos.incrementAndGet()
                                if (!scrapingCancelled.get() && _binding != null) {
                                    withContext(Dispatchers.Main) {
                                        binding.textAssetStats.text = "Logos: $completed/$totalGames..."
                                    }
                                }
                            }
                        }
                    }
                    logoJobs.awaitAll()
                }

                val totalSuccess = iconSuccess.get() + heroSuccess.get() + logoSuccess.get()
                val totalFail = iconFail.get() + heroFail.get() + logoFail.get()

                // Only finish if not already cancelled (cancel button handles UI)
                if (!scrapingCancelled.get()) {
                    finishScraping(
                        "Complete: $totalSuccess found, $totalFail not found\n" +
                            "(Icons: ${iconSuccess.get()}, Heroes: ${heroSuccess.get()}, Logos: ${logoSuccess.get()})",
                        wasCancelled = false
                    )
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Job was cancelled - UI already updated by cancelScraping()
                scrapingCancelled.set(false)
            } catch (e: Exception) {
                if (!scrapingCancelled.get()) {
                    finishScraping("Error: ${e.message}")
                }
            }
        }
    }

    private fun bulkGenerateInteractive() {
        if (games.isEmpty()) {
            Toast.makeText(requireContext(), "No games to process", Toast.LENGTH_SHORT).show()
            return
        }

        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping already in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        scrapingCancelled.set(false)
        setScrapingState(true)

        // Process games one by one, showing picker for each
        var currentGameIndex = 0

        fun processNextGame() {
            if (scrapingCancelled.get() || _binding == null) {
                finishScraping("Processed $currentGameIndex/${games.size} games", wasCancelled = scrapingCancelled.get())
                return
            }

            if (currentGameIndex >= games.size) {
                finishScraping("Interactive generation complete!")
                return
            }

            val game = games[currentGameIndex]
            binding.textAssetStats.text = "Game ${currentGameIndex + 1}/${games.size}: ${game.displayName}"

            // Show icon picker for this game
            scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
                if (scrapingCancelled.get() || _binding == null) {
                    finishScraping("Processed $currentGameIndex/${games.size} games", wasCancelled = true)
                    return@launch
                }

                val iconResult = withContext(Dispatchers.IO) {
                    artworkScraper.searchIconOptions(game, platformName)
                }

                if (_binding == null || scrapingCancelled.get()) return@launch

                if (iconResult.options.isNotEmpty()) {
                    ArtworkPickerDialog.showWithSkip(
                        context = requireContext(),
                        artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                        searchResult = iconResult,
                        onOptionSelected = { selectedOption ->
                            viewLifecycleOwner.lifecycleScope.launch {
                                if (scrapingCancelled.get() || _binding == null) return@launch

                                withContext(Dispatchers.IO) {
                                    artworkScraper.saveIconFromOption(selectedOption, game, platformName)
                                }
                                // Continue to hero picker with skip support
                                val cancelBulk = {
                                    scrapingCancelled.set(true)
                                    finishScraping("Processed $currentGameIndex/${games.size} games", wasCancelled = true)
                                }
                                val skipToNextGame = {
                                    currentGameIndex++
                                    processNextGame()
                                }
                                showHeroPickerForGame(
                                    game = game,
                                    onComplete = {
                                        showLogoPickerForGame(
                                            game = game,
                                            onComplete = skipToNextGame,
                                            onSkipGame = skipToNextGame,
                                            onCancelBulk = cancelBulk
                                        )
                                    },
                                    onSkipGame = skipToNextGame,
                                    onCancelBulk = cancelBulk
                                )
                            }
                        },
                        onSkip = {
                            // Skip this game entirely, move to next
                            currentGameIndex++
                            processNextGame()
                        },
                        onCancel = {
                            // Cancel entire bulk operation
                            scrapingCancelled.set(true)
                            finishScraping("Processed $currentGameIndex/${games.size} games", wasCancelled = true)
                        }
                    )
                } else {
                    // No icons found, move to hero with skip support
                    val cancelBulk = {
                        scrapingCancelled.set(true)
                        finishScraping("Processed $currentGameIndex/${games.size} games", wasCancelled = true)
                    }
                    val skipToNextGame = {
                        currentGameIndex++
                        processNextGame()
                    }
                    showHeroPickerForGame(
                        game = game,
                        onComplete = {
                            showLogoPickerForGame(
                                game = game,
                                onComplete = skipToNextGame,
                                onSkipGame = skipToNextGame,
                                onCancelBulk = cancelBulk
                            )
                        },
                        onSkipGame = skipToNextGame,
                        onCancelBulk = cancelBulk
                    )
                }
            }
        }

        processNextGame()
    }

    private fun showHeroPickerForGame(
        game: GameInfo,
        onComplete: () -> Unit,
        onSkipGame: (() -> Unit)? = null,
        onCancelBulk: (() -> Unit)? = null
    ) {
        if (scrapingCancelled.get() || _binding == null) {
            onComplete()
            return
        }

        viewLifecycleOwner.lifecycleScope.launch {
            if (scrapingCancelled.get() || _binding == null) {
                onComplete()
                return@launch
            }

            val heroResult = withContext(Dispatchers.IO) {
                artworkScraper.searchHeroOptions(game, platformName)
            }

            if (_binding == null || scrapingCancelled.get()) {
                onComplete()
                return@launch
            }

            if (heroResult.options.isNotEmpty()) {
                // Use skip-enabled dialog if callbacks provided (bulk mode)
                if (onSkipGame != null && onCancelBulk != null) {
                    ArtworkPickerDialog.showWithSkip(
                        context = requireContext(),
                        artworkType = ArtworkPickerDialog.ArtworkType.HERO,
                        searchResult = heroResult,
                        onOptionSelected = { selectedOption ->
                            viewLifecycleOwner.lifecycleScope.launch {
                                if (scrapingCancelled.get() || _binding == null) {
                                    onComplete()
                                    return@launch
                                }

                                withContext(Dispatchers.IO) {
                                    artworkScraper.saveHeroFromOption(selectedOption, game)
                                }
                                onComplete()
                            }
                        },
                        onSkip = { onComplete() },  // Skip hero, continue to logo
                        onCancel = onCancelBulk
                    )
                } else {
                    // Single game mode - no skip
                    ArtworkPickerDialog.show(
                        requireContext(),
                        ArtworkPickerDialog.ArtworkType.HERO,
                        heroResult
                    ) { selectedOption ->
                        viewLifecycleOwner.lifecycleScope.launch {
                            if (scrapingCancelled.get() || _binding == null) {
                                onComplete()
                                return@launch
                            }

                            withContext(Dispatchers.IO) {
                                artworkScraper.saveHeroFromOption(selectedOption, game)
                            }
                            onComplete()
                        }
                    }
                }
            } else {
                onComplete()
            }
        }
    }

    private fun showLogoPickerForGame(
        game: GameInfo,
        onComplete: () -> Unit,
        onSkipGame: (() -> Unit)? = null,
        onCancelBulk: (() -> Unit)? = null
    ) {
        if (scrapingCancelled.get() || _binding == null) {
            onComplete()
            return
        }

        viewLifecycleOwner.lifecycleScope.launch {
            if (scrapingCancelled.get() || _binding == null) {
                onComplete()
                return@launch
            }

            val logoResult = withContext(Dispatchers.IO) {
                artworkScraper.searchLogoOptions(game, platformName)
            }

            if (_binding == null || scrapingCancelled.get()) {
                onComplete()
                return@launch
            }

            if (logoResult.options.isNotEmpty()) {
                // Use skip-enabled dialog if callbacks provided (bulk mode)
                if (onSkipGame != null && onCancelBulk != null) {
                    ArtworkPickerDialog.showWithSkip(
                        context = requireContext(),
                        artworkType = ArtworkPickerDialog.ArtworkType.LOGO,
                        searchResult = logoResult,
                        onOptionSelected = { selectedOption ->
                            viewLifecycleOwner.lifecycleScope.launch {
                                if (scrapingCancelled.get() || _binding == null) {
                                    onComplete()
                                    return@launch
                                }

                                withContext(Dispatchers.IO) {
                                    artworkScraper.saveLogoFromOption(selectedOption, game)
                                }
                                onComplete()
                            }
                        },
                        onSkip = { onComplete() },  // Skip logo, move to next game
                        onCancel = onCancelBulk
                    )
                } else {
                    // Single game mode - no skip
                    ArtworkPickerDialog.show(
                        requireContext(),
                        ArtworkPickerDialog.ArtworkType.LOGO,
                        logoResult
                    ) { selectedOption ->
                        viewLifecycleOwner.lifecycleScope.launch {
                            if (scrapingCancelled.get() || _binding == null) {
                                onComplete()
                                return@launch
                            }

                            withContext(Dispatchers.IO) {
                                artworkScraper.saveLogoFromOption(selectedOption, game)
                            }
                            onComplete()
                        }
                    }
                }
            } else {
                onComplete()
            }
        }
    }

    private fun refreshGameList() {
        if (_binding == null) return

        viewLifecycleOwner.lifecycleScope.launch {
            // Invalidate cache for this platform since games were modified
            GameCache.invalidatePlatform(platformName)

            // Force refresh from filesystem
            games = GameCache.getGamesForPlatform(platformName, forceRefresh = true)

            if (_binding == null) return@launch

            gameAdapter.submitList(games.toList()) // Create a new list to force DiffUtil update
            updateStats()
        }
    }

    override fun onDestroyView() {
        // Cancel any active scraping when leaving the fragment
        if (isScraping) {
            scrapingCancelled.set(true)
            scrapingJob?.cancel()
            isScraping = false
        }

        super.onDestroyView()
        _binding = null
    }
}
