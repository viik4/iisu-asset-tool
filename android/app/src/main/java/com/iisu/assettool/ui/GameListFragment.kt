package com.iisu.assettool.ui

import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
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
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import android.app.Activity
import android.graphics.Bitmap
import android.net.Uri
import android.util.Log
import androidx.activity.result.contract.ActivityResultContracts
import java.io.FileOutputStream

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
    private var isGridView: Boolean = false  // Track current view mode

    // Track active scraping job for cancellation
    private var scrapingJob: Job? = null
    private var scrapingCancelled = AtomicBoolean(false)

    // Track pending crop operation
    private var pendingCropGame: GameInfo? = null
    private var currentPickerDialog: ArtworkPickerDialog? = null

    // Track pending upload operation
    private var pendingUploadGame: GameInfo? = null
    private var pendingUploadAssetType: AssetType? = null

    // Track pending soundbyte operation
    private var pendingSoundbtyeGame: GameInfo? = null

    private enum class AssetType { ICON, HERO, LOGO }

    // Activity result launchers for image upload
    private val pickIconLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedImage(it, AssetType.ICON) } }

    private val pickHeroLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedImage(it, AssetType.HERO) } }

    private val pickLogoLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedImage(it, AssetType.LOGO) } }

    // Activity result launcher for soundbyte file picker
    private val pickSoundbyteLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedSoundbyte(it) } }

    // Activity result launcher for crop activity
    private val cropLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val croppedPath = result.data?.getStringExtra(ImageCropActivity.RESULT_CROPPED_PATH)
            if (croppedPath != null && pendingCropGame != null) {
                // Save the cropped image as the icon with border
                viewLifecycleOwner.lifecycleScope.launch {
                    saveCroppedIconWithBorder(pendingCropGame!!, croppedPath)
                }
            }
        }
        pendingCropGame = null
    }

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

        // View mode toggle button
        binding.btnToggleViewMode.setOnClickListener {
            toggleViewMode()
        }
    }

    /**
     * Toggle between list and grid view modes
     */
    private fun toggleViewMode() {
        isGridView = !isGridView

        // Update button icon
        binding.btnToggleViewMode.setImageResource(
            if (isGridView) R.drawable.ic_view_list else R.drawable.ic_view_grid
        )

        // Update adapter view mode
        gameAdapter.viewMode = if (isGridView) GameAdapter.VIEW_TYPE_GRID else GameAdapter.VIEW_TYPE_LIST

        // Update layout manager
        binding.recyclerViewGames.layoutManager = if (isGridView) {
            // Calculate optimal span count based on screen width
            val spanCount = calculateGridSpanCount()
            GridLayoutManager(requireContext(), spanCount)
        } else {
            LinearLayoutManager(requireContext())
        }
    }

    /**
     * Calculate optimal number of columns for grid based on screen width
     * Aims for items around 140-180dp wide
     */
    private fun calculateGridSpanCount(): Int {
        val displayMetrics = resources.displayMetrics
        val screenWidthDp = displayMetrics.widthPixels / displayMetrics.density
        // Target item width of 150dp, minimum 2 columns, maximum 6 columns
        val idealItemWidth = 150f
        val spanCount = (screenWidthDp / idealItemWidth).toInt()
        return spanCount.coerceIn(2, 6)
    }

    /**
     * Show context menu for a game on long-press
     */
    private fun showGameContextMenu(game: GameInfo, anchorView: View) {
        val popup = PopupMenu(requireContext(), anchorView)
        popup.menuInflater.inflate(R.menu.context_game, popup.menu)

        popup.setOnMenuItemClickListener { menuItem ->
            when (menuItem.itemId) {
                R.id.action_preview_assets -> {
                    showAssetPreview(game)
                    true
                }
                R.id.action_edit_search_query -> {
                    showEditSearchQueryDialog(game)
                    true
                }
                R.id.action_generate_icon -> {
                    generateIconForGame(game)
                    true
                }
                R.id.action_generate_hero -> {
                    generateHeroForGame(game)
                    true
                }
                R.id.action_generate_logo -> {
                    generateLogoForGame(game)
                    true
                }
                R.id.action_manual_search -> {
                    manualSearch(game)
                    true
                }
                R.id.action_add_soundbyte -> {
                    addSoundbyte(game)
                    true
                }
                R.id.action_hide_title -> {
                    hideGame(game)
                    true
                }
                else -> false
            }
        }

        popup.show()
    }

    /**
     * Hide a game title from the list
     */
    private fun hideGame(game: GameInfo) {
        SettingsFragment.hideTitle(requireContext(), platformName, game.displayName)
        Toast.makeText(requireContext(), "\"${game.displayName}\" hidden", Toast.LENGTH_SHORT).show()
        // Refresh the games list
        refreshGamesAfterHide()
    }

    /**
     * Refresh games list after hiding a title
     */
    private fun refreshGamesAfterHide() {
        val hiddenTitles = SettingsFragment.getHiddenTitles(requireContext())[platformName] ?: emptySet()
        val filteredGames = games.filter { game ->
            !hiddenTitles.contains(game.displayName)
        }
        gameAdapter.submitList(filteredGames)
        binding.textGameCount.text = "${filteredGames.size} games"
    }

    /**
     * Add a local sound file as a soundbyte for a game
     */
    private fun addSoundbyte(game: GameInfo) {
        pendingSoundbtyeGame = game
        pickSoundbyteLauncher.launch("audio/*")
    }

    /**
     * Handle a picked audio file from the device and save it as a soundbyte
     */
    private fun handlePickedSoundbyte(uri: Uri) {
        val game = pendingSoundbtyeGame ?: return
        pendingSoundbtyeGame = null

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                // Determine extension from the content URI
                val mimeType = requireContext().contentResolver.getType(uri)
                val extension = when {
                    mimeType?.contains("flac") == true -> "flac"
                    mimeType?.contains("ogg") == true -> "ogg"
                    mimeType?.contains("wav") == true -> "wav"
                    mimeType?.contains("mp4") == true -> "mp3"
                    mimeType?.contains("m4a") == true -> "mp3"
                    else -> "mp3"
                }

                val targetFile = File(game.folder, "music.$extension")

                // Check if music file already exists
                val existingMusic = listOf("mp3", "ogg", "flac", "wav").firstOrNull { ext ->
                    File(game.folder, "music.$ext").exists()
                }

                if (existingMusic != null) {
                    // Ask to overwrite
                    withContext(Dispatchers.Main) {
                        com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                            .setTitle("Soundbyte Exists")
                            .setMessage("\"${game.displayName}\" already has a soundbyte (music.$existingMusic).\n\nOverwrite it?")
                            .setPositiveButton("Overwrite") { _, _ ->
                                performSoundbyteCopy(uri, targetFile, game, extension)
                            }
                            .setNegativeButton("Cancel", null)
                            .show()
                    }
                } else {
                    performSoundbyteCopy(uri, targetFile, game, extension)
                }

            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    /**
     * Copy the selected audio file to the game's folder as music.{ext}
     */
    @Suppress("UNUSED_PARAMETER")
    private fun performSoundbyteCopy(uri: Uri, targetFile: File, game: GameInfo, extension: String) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    // Delete any existing music files
                    listOf("mp3", "ogg", "flac", "wav").forEach { ext ->
                        val existing = File(game.folder, "music.$ext")
                        if (existing.exists()) existing.delete()
                    }

                    // Copy the selected file
                    requireContext().contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(targetFile).use { output ->
                            input.copyTo(output)
                        }
                    }
                }

                withContext(Dispatchers.Main) {
                    if (targetFile.exists() && targetFile.length() > 0) {
                        Toast.makeText(
                            requireContext(),
                            "Soundbyte added to \"${game.displayName}\"",
                            Toast.LENGTH_SHORT
                        ).show()
                    } else {
                        Toast.makeText(
                            requireContext(),
                            "Failed to save soundbyte",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }

            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    /**
     * Show asset preview dialog for a game
     */
    private fun showAssetPreview(game: GameInfo) {
        AssetPreviewDialog.show(
            context = requireContext(),
            game = game,
            onGenerateIcon = { generateIconForGame(game) },
            onGenerateHero = { generateHeroForGame(game) },
            onGenerateLogo = { generateLogoForGame(game) },
            onUploadIcon = {
                pendingUploadGame = game
                pickIconLauncher.launch("image/*")
            },
            onUploadHero = {
                pendingUploadGame = game
                pickHeroLauncher.launch("image/*")
            },
            onUploadLogo = {
                pendingUploadGame = game
                pickLogoLauncher.launch("image/*")
            }
        )
    }

    /**
     * Handle a picked image from the gallery
     */
    private fun handlePickedImage(uri: Uri, assetType: AssetType) {
        val game = pendingUploadGame ?: return
        pendingUploadGame = null

        viewLifecycleOwner.lifecycleScope.launch {
            setScrapingState(true)

            val success = withContext(Dispatchers.IO) {
                try {
                    val inputStream = requireContext().contentResolver.openInputStream(uri)
                    if (inputStream == null) {
                        Log.e("GameListFragment", "Failed to open input stream for URI: $uri")
                        return@withContext false
                    }

                    val bitmap = BitmapFactory.decodeStream(inputStream)
                    inputStream.close()

                    if (bitmap == null) {
                        Log.e("GameListFragment", "Failed to decode bitmap from URI: $uri")
                        return@withContext false
                    }

                    // Determine the target file based on asset type
                    val targetFile = when (assetType) {
                        AssetType.ICON -> File(game.folder, "icon.png")
                        AssetType.HERO -> File(game.folder, "hero.png")
                        AssetType.LOGO -> File(game.folder, "logo.png")
                    }

                    // Ensure parent directory exists
                    targetFile.parentFile?.mkdirs()

                    // Save the bitmap as PNG
                    FileOutputStream(targetFile).use { out ->
                        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
                    }

                    Log.d("GameListFragment", "Saved ${assetType.name.lowercase()} to ${targetFile.absolutePath}")
                    true
                } catch (e: Exception) {
                    Log.e("GameListFragment", "Error saving ${assetType.name.lowercase()}", e)
                    false
                }
            }

            if (_binding == null) return@launch
            setScrapingState(false)

            val assetName = assetType.name.lowercase().replaceFirstChar { it.uppercase() }
            if (success) {
                Toast.makeText(requireContext(), "$assetName saved for ${game.displayName}!", Toast.LENGTH_SHORT).show()
                refreshGameList()
            } else {
                Toast.makeText(requireContext(), "Failed to save $assetName", Toast.LENGTH_SHORT).show()
            }
        }
    }

    /**
     * Show dialog to edit the search query for a game
     * This allows users to manually specify what to search for
     */
    private fun showEditSearchQueryDialog(game: GameInfo) {
        val editText = EditText(requireContext()).apply {
            setText(game.searchName)
            setTextColor(resources.getColor(R.color.theme_text_primary, null))
            setHintTextColor(resources.getColor(R.color.theme_text_secondary, null))
            hint = "Enter search query..."
            setSingleLine(false)
            maxLines = 3
            setSelection(text.length)  // Move cursor to end
        }

        // Add padding around the EditText
        val container = FrameLayout(requireContext()).apply {
            val padding = (16 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding / 2, padding, 0)
            addView(editText)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Edit Search Query")
            .setMessage("Enter the game title to search for artwork.\nOriginal: ${game.displayName}")
            .setView(container)
            .setPositiveButton("Search") { _, _ ->
                val query = editText.text.toString().trim()
                if (query.isNotEmpty()) {
                    // Create a modified game with the custom search name
                    val modifiedGame = game.copy(name = query)

                    Toast.makeText(
                        requireContext(),
                        "Searching for: $query",
                        Toast.LENGTH_SHORT
                    ).show()

                    // Generate icon with the new search query
                    generateIconForGame(modifiedGame)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /**
     * Manual search - let user search for a different game and generate all assets (icons, heroes, logos)
     */
    private fun manualSearch(game: GameInfo) {
        // Show game search dialog
        GameSearchDialog.show(
            context = requireContext(),
            gameInfo = game,
            artworkScraper = artworkScraper
        ) { selectedResult ->
            // User selected a different game, now search for ALL artwork using the SGDB ID
            viewLifecycleOwner.lifecycleScope.launch {
                Toast.makeText(
                    requireContext(),
                    "Searching all artwork for: ${selectedResult.name}",
                    Toast.LENGTH_SHORT
                ).show()

                // Create a modified game info with the selected game's name
                val modifiedGame = game.copy(name = selectedResult.name)

                // Use the SteamGridDB game ID to fetch all assets (icons, heroes, logos)
                generateAllAssetsForGameById(modifiedGame, selectedResult.id)
            }
        }
    }

    /**
     * Generate all assets (icon, hero, logo) for a game using a known SteamGridDB game ID.
     * Shows pickers for each asset type in sequence.
     */
    private fun generateAllAssetsForGameById(game: GameInfo, sgdbGameId: Int) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        // Start with icon picker, then chain to hero and logo
        showIconPickerForGameById(game, sgdbGameId) {
            showHeroPickerForGameById(game, sgdbGameId) {
                showLogoPickerForGameById(game, sgdbGameId) {
                    Toast.makeText(
                        requireContext(),
                        "All assets complete for ${game.displayName}",
                        Toast.LENGTH_SHORT
                    ).show()
                    refreshGameList()
                }
            }
        }
    }

    /**
     * Show icon picker for a game using SteamGridDB game ID
     */
    private fun showIconPickerForGameById(game: GameInfo, sgdbGameId: Int, onComplete: () -> Unit) {
        var dialogCompleted = false  // Track if we've called onComplete
        var currentPickerDialog: ArtworkPickerDialog? = null

        // Use global setting for square icons only
        var currentSquareOnly = SettingsFragment.isSquareIconsOnly(requireContext())

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, platformName, currentSquareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                // If square-only returned nothing, suggest trying all results
                if (currentSquareOnly) {
                    withContext(Dispatchers.Main) {
                        AlertDialog.Builder(requireContext())
                            .setTitle("No Square Icons Found")
                            .setMessage("No square icons found for ${game.displayName}.\n\nWould you like to try searching all icons? You can crop non-square images.")
                            .setPositiveButton("Try All Icons") { _, _ ->
                                // Retry with squareOnly = false
                                showIconPickerForGameByIdWithFilter(game, sgdbGameId, false, onComplete)
                            }
                            .setNegativeButton("Skip") { _, _ ->
                                onComplete()
                            }
                            .show()
                    }
                } else {
                    Toast.makeText(
                        requireContext(),
                        "No icons found for ${game.displayName}",
                        Toast.LENGTH_SHORT
                    ).show()
                    onComplete()
                }
                return@launch
            }

            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                currentPickerDialog = ArtworkPickerDialog.showForIconWithFilter(
                    context = requireContext(),
                    searchResult = searchResult,
                    initialSquareOnly = currentSquareOnly,
                    onOptionSelected = { selectedOption ->
                        dialogCompleted = true
                        viewLifecycleOwner.lifecycleScope.launch {
                            handleIconSelection(game, selectedOption)
                            onComplete()
                        }
                    },
                    onSkip = {
                        dialogCompleted = true
                        onComplete()
                    },
                    onCancel = {
                        if (!dialogCompleted) {
                            dialogCompleted = true
                            onComplete()
                        }
                    },
                    onFilterChanged = { newSquareOnly ->
                        // Fetch new results with the updated filter
                        currentSquareOnly = newSquareOnly
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, platformName, newSquareOnly)
                            withContext(Dispatchers.Main) {
                                currentPickerDialog?.updateSearchResult(newResult)
                            }
                        }
                    }
                )
            }
        }
    }

    /**
     * Helper to show icon picker with a specific filter setting (used for retry)
     */
    private fun showIconPickerForGameByIdWithFilter(game: GameInfo, sgdbGameId: Int, squareOnly: Boolean, onComplete: () -> Unit) {
        var dialogCompleted = false
        var currentPickerDialog: ArtworkPickerDialog? = null
        var currentSquareOnly = squareOnly

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, platformName, currentSquareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No icons found for ${game.displayName}",
                    Toast.LENGTH_SHORT
                ).show()
                onComplete()
                return@launch
            }

            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                currentPickerDialog = ArtworkPickerDialog.showForIconWithFilter(
                    context = requireContext(),
                    searchResult = searchResult,
                    initialSquareOnly = currentSquareOnly,
                    onOptionSelected = { selectedOption ->
                        dialogCompleted = true
                        viewLifecycleOwner.lifecycleScope.launch {
                            handleIconSelection(game, selectedOption)
                            onComplete()
                        }
                    },
                    onSkip = {
                        dialogCompleted = true
                        onComplete()
                    },
                    onCancel = {
                        if (!dialogCompleted) {
                            dialogCompleted = true
                            onComplete()
                        }
                    },
                    onFilterChanged = { newSquareOnly ->
                        currentSquareOnly = newSquareOnly
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, platformName, newSquareOnly)
                            withContext(Dispatchers.Main) {
                                currentPickerDialog?.updateSearchResult(newResult)
                            }
                        }
                    }
                )
            }
        }
    }

    /**
     * Show hero picker for a game using SteamGridDB game ID
     */
    private fun showHeroPickerForGameById(game: GameInfo, sgdbGameId: Int, onComplete: () -> Unit) {
        var dialogCompleted = false

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchHeroOptionsByGameId(sgdbGameId, game)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No heroes found for ${game.displayName}",
                    Toast.LENGTH_SHORT
                ).show()
                onComplete()
                return@launch
            }

            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.showWithSkip(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.HERO,
                    searchResult = searchResult,
                    onOptionSelected = { selectedOption ->
                        dialogCompleted = true
                        viewLifecycleOwner.lifecycleScope.launch {
                            val success = artworkScraper.saveHeroFromOption(selectedOption, game)
                            if (success) {
                                Toast.makeText(
                                    requireContext(),
                                    "Hero saved for ${game.displayName}",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                            onComplete()
                        }
                    },
                    onSkip = {
                        dialogCompleted = true
                        onComplete()
                    },
                    onCancel = {
                        if (!dialogCompleted) {
                            dialogCompleted = true
                            onComplete()
                        }
                    }
                )
            }
        }
    }

    /**
     * Show logo picker for a game using SteamGridDB game ID
     */
    private fun showLogoPickerForGameById(game: GameInfo, sgdbGameId: Int, onComplete: () -> Unit) {
        var dialogCompleted = false

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchLogoOptionsByGameId(sgdbGameId, game)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No logos found for ${game.displayName}",
                    Toast.LENGTH_SHORT
                ).show()
                onComplete()
                return@launch
            }

            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.showWithSkip(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.LOGO,
                    searchResult = searchResult,
                    onOptionSelected = { selectedOption ->
                        dialogCompleted = true
                        viewLifecycleOwner.lifecycleScope.launch {
                            val success = artworkScraper.saveLogoFromOption(selectedOption, game)
                            if (success) {
                                Toast.makeText(
                                    requireContext(),
                                    "Logo saved for ${game.displayName}",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                            onComplete()
                        }
                    },
                    onSkip = {
                        dialogCompleted = true
                        onComplete()
                    },
                    onCancel = {
                        if (!dialogCompleted) {
                            dialogCompleted = true
                            onComplete()
                        }
                    }
                )
            }
        }
    }

    /**
     * Generate icon for a game using a known SteamGridDB game ID.
     * This is more accurate than name-based search since we already know the exact game.
     */
    private fun generateIconForGameById(game: GameInfo, sgdbGameId: Int) {
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        // Use global setting for square icons only
        val squareOnly = SettingsFragment.isSquareIconsOnly(requireContext())

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, platformName, squareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No icons found for ${game.displayName}",
                    Toast.LENGTH_SHORT
                ).show()
                return@launch
            }

            // Show picker dialog with options (no filter toggle - uses global setting)
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                    searchResult = searchResult
                ) { selectedOption ->
                    handleIconSelection(game, selectedOption)
                }
            }
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
            onGenerateLogo = { game -> generateLogoForGame(game) },
            onLongPress = { game, view -> showGameContextMenu(game, view) }
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

            // Check if deep search is enabled
            val deepSearch = SettingsFragment.isDeepSearchEnabled(requireContext())

            // Use cached games for fast loading
            var allGames = GameCache.getGamesForPlatform(platformName, forceRefresh, deepSearch)

            // Filter out hidden titles
            val hiddenTitles = SettingsFragment.getHiddenTitles(requireContext())[platformName] ?: emptySet()
            games = allGames.filter { game ->
                !hiddenTitles.contains(game.displayName)
            }

            val loadTime = System.currentTimeMillis() - startTime
            android.util.Log.d("GameListFragment", "Loaded ${games.size} games (${allGames.size - games.size} hidden) in ${loadTime}ms")

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

        // Use global setting for square icons only
        var currentSquareOnly = SettingsFragment.isSquareIconsOnly(requireContext())
        var currentPickerDialog: ArtworkPickerDialog? = null

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptions(game, platformName, currentSquareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                // If square-only returned nothing, suggest trying all results
                if (currentSquareOnly) {
                    withContext(Dispatchers.Main) {
                        AlertDialog.Builder(requireContext())
                            .setTitle("No Square Icons Found")
                            .setMessage("No square icons found for ${game.displayName}.\n\nWould you like to try searching all icons? You can crop non-square images.")
                            .setPositiveButton("Try All Icons") { _, _ ->
                                generateIconForGameWithFilter(game, false)
                            }
                            .setNegativeButton("Cancel", null)
                            .show()
                    }
                } else {
                    Toast.makeText(
                        requireContext(),
                        "No icons found for ${game.name}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
                return@launch
            }

            // Show picker dialog with filter toggle support
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                currentPickerDialog = ArtworkPickerDialog.showForIconWithFilter(
                    context = requireContext(),
                    searchResult = searchResult,
                    initialSquareOnly = currentSquareOnly,
                    onOptionSelected = { selectedOption ->
                        handleIconSelection(game, selectedOption)
                    },
                    onFilterChanged = { newSquareOnly ->
                        // Fetch new results with the updated filter
                        currentSquareOnly = newSquareOnly
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptions(game, platformName, newSquareOnly)
                            withContext(Dispatchers.Main) {
                                currentPickerDialog?.updateSearchResult(newResult)
                            }
                        }
                    }
                )
            }
        }
    }

    /**
     * Helper to generate icon with a specific filter setting (used for retry)
     */
    private fun generateIconForGameWithFilter(game: GameInfo, squareOnly: Boolean) {
        var currentSquareOnly = squareOnly
        var currentPickerDialog: ArtworkPickerDialog? = null

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptions(game, platformName, currentSquareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(
                    requireContext(),
                    "No icons found for ${game.name}",
                    Toast.LENGTH_SHORT
                ).show()
                return@launch
            }

            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                currentPickerDialog = ArtworkPickerDialog.showForIconWithFilter(
                    context = requireContext(),
                    searchResult = searchResult,
                    initialSquareOnly = currentSquareOnly,
                    onOptionSelected = { selectedOption ->
                        handleIconSelection(game, selectedOption)
                    },
                    onFilterChanged = { newSquareOnly ->
                        currentSquareOnly = newSquareOnly
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptions(game, platformName, newSquareOnly)
                            withContext(Dispatchers.Main) {
                                currentPickerDialog?.updateSearchResult(newResult)
                            }
                        }
                    }
                )
            }
        }
    }

    /**
     * Handle icon selection - either save directly (if square) or launch crop activity (if non-square)
     */
    private fun handleIconSelection(game: GameInfo, selectedOption: com.iisu.assettool.util.ArtworkOption) {
        val isSquare = ArtworkPickerDialog.isSquare(selectedOption)

        if (isSquare) {
            // Square image - save directly with iiSU border
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
        } else {
            // Non-square image - launch crop activity
            launchCropActivity(game, selectedOption)
        }
    }

    /**
     * Launch the crop activity for a non-square image
     */
    private fun launchCropActivity(game: GameInfo, option: com.iisu.assettool.util.ArtworkOption) {
        pendingCropGame = game

        // Create output path for the cropped image
        val outputPath = File(game.folder, "icon_cropped_temp.png").absolutePath

        val intent = ImageCropActivity.createIntent(
            context = requireContext(),
            imageUrl = option.url,
            imagePath = null,
            outputPath = outputPath,
            gameName = game.displayName
        )

        cropLauncher.launch(intent)
    }

    /**
     * Save a cropped image as an icon with iiSU border
     */
    private suspend fun saveCroppedIconWithBorder(game: GameInfo, croppedPath: String) {
        withContext(Dispatchers.IO) {
            try {
                val croppedFile = File(croppedPath)
                if (!croppedFile.exists()) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(requireContext(), "Cropped file not found", Toast.LENGTH_SHORT).show()
                    }
                    return@withContext
                }

                // Load the cropped bitmap
                val bitmap = android.graphics.BitmapFactory.decodeFile(croppedPath)
                if (bitmap == null) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(requireContext(), "Failed to load cropped image", Toast.LENGTH_SHORT).show()
                    }
                    return@withContext
                }

                // Get custom border path if set
                val customBorderPath = SettingsFragment.getCustomBorderPath(requireContext())

                // Apply iiSU border
                val iconGenerator = com.iisu.assettool.util.IconGenerator(requireContext())
                val finalBitmap = iconGenerator.generateIconWithBorder(
                    bitmap, platformName,
                    com.iisu.assettool.util.ArtworkScraper.HIGH_RES_ICON_SIZE,
                    Pair(0.5f, 0.5f),
                    customBorderPath
                )

                if (finalBitmap == null) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(requireContext(), "Failed to apply border", Toast.LENGTH_SHORT).show()
                    }
                    return@withContext
                }

                // Delete existing icon files
                val extensions = listOf("png", "jpg", "jpeg")
                extensions.forEach { ext ->
                    val file = File(game.folder, "icon.$ext")
                    if (file.exists()) file.delete()
                }

                // Get export format settings
                val exportFormat = SettingsFragment.getExportFormat(requireContext())
                val jpegQuality = SettingsFragment.getJpegQuality(requireContext())

                val (format, extension, quality) = if (exportFormat == "JPEG") {
                    Triple(android.graphics.Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
                } else {
                    Triple(android.graphics.Bitmap.CompressFormat.PNG, "png", 100)
                }

                // Save the final icon
                val iconFile = File(game.folder, "icon.$extension")
                java.io.FileOutputStream(iconFile).use { out ->
                    finalBitmap.compress(format, quality, out)
                }

                // Clean up temp file
                croppedFile.delete()

                withContext(Dispatchers.Main) {
                    if (_binding != null) {
                        Toast.makeText(
                            requireContext(),
                            "Icon saved with border for ${game.displayName}",
                            Toast.LENGTH_SHORT
                        ).show()
                        refreshGameList()
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
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
                    viewLifecycleOwner.lifecycleScope.launch heroLaunch@{
                        val success = artworkScraper.saveHeroFromOption(selectedOption, game)
                        if (_binding == null) return@heroLaunch

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
                    viewLifecycleOwner.lifecycleScope.launch logoLaunch@{
                        val success = artworkScraper.saveLogoFromOption(selectedOption, game)
                        if (_binding == null) return@logoLaunch

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

        // Show confirmation dialog
        androidx.appcompat.app.AlertDialog.Builder(requireContext())
            .setTitle("Generate All Icons")
            .setMessage("Are you sure you want to generate icons for ${games.size} games?\n\nThis will download and process artwork for all games in this platform.")
            .setPositiveButton("Generate") { _, _ ->
                startIconScraping(parallelCount)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startIconScraping(parallelCount: Int) {
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

        // Show confirmation dialog
        androidx.appcompat.app.AlertDialog.Builder(requireContext())
            .setTitle("Generate All Heroes")
            .setMessage("Are you sure you want to generate heroes for ${games.size} games?\n\nThis will download and process hero images for all games in this platform.")
            .setPositiveButton("Generate") { _, _ ->
                startHeroScraping(parallelCount)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startHeroScraping(parallelCount: Int) {
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

        // Show confirmation dialog
        androidx.appcompat.app.AlertDialog.Builder(requireContext())
            .setTitle("Generate All Logos")
            .setMessage("Are you sure you want to generate logos for ${games.size} games?\n\nThis will download and process logo images for all games in this platform.")
            .setPositiveButton("Generate") { _, _ ->
                startLogoScraping(parallelCount)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startLogoScraping(parallelCount: Int) {
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

        // Show confirmation dialog
        androidx.appcompat.app.AlertDialog.Builder(requireContext())
            .setTitle("Download All Screenshots")
            .setMessage("Are you sure you want to download $screenshotCount screenshots for ${games.size} games?\n\nThis will download ${screenshotCount * games.size} screenshot images total.")
            .setPositiveButton("Download") { _, _ ->
                startScreenshotScraping(parallelCount, screenshotCount)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startScreenshotScraping(parallelCount: Int, screenshotCount: Int) {
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
            // Use global setting for square icons only
            val squareOnly = SettingsFragment.isSquareIconsOnly(requireContext())

            scrapingJob = viewLifecycleOwner.lifecycleScope.launch {
                if (scrapingCancelled.get() || _binding == null) {
                    finishScraping("Processed $currentGameIndex/${games.size} games", wasCancelled = true)
                    return@launch
                }

                val iconResult = withContext(Dispatchers.IO) {
                    artworkScraper.searchIconOptions(game, platformName, squareOnly)
                }

                if (_binding == null || scrapingCancelled.get()) return@launch

                if (iconResult.options.isNotEmpty()) {
                    // Show icon picker (no filter toggle - uses global setting)
                    ArtworkPickerDialog.showWithSkip(
                        context = requireContext(),
                        artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                        searchResult = iconResult,
                        onOptionSelected = { selectedOption ->
                            viewLifecycleOwner.lifecycleScope.launch iconPickLaunch@{
                                if (scrapingCancelled.get() || _binding == null) return@iconPickLaunch

                                handleIconSelection(game, selectedOption)
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
                            viewLifecycleOwner.lifecycleScope.launch heroPickLaunch@{
                                if (scrapingCancelled.get() || _binding == null) {
                                    onComplete()
                                    return@heroPickLaunch
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
                        viewLifecycleOwner.lifecycleScope.launch heroSimpleLaunch@{
                            if (scrapingCancelled.get() || _binding == null) {
                                onComplete()
                                return@heroSimpleLaunch
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
                            viewLifecycleOwner.lifecycleScope.launch logoPickLaunch@{
                                if (scrapingCancelled.get() || _binding == null) {
                                    onComplete()
                                    return@logoPickLaunch
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
                        viewLifecycleOwner.lifecycleScope.launch logoSimpleLaunch@{
                            if (scrapingCancelled.get() || _binding == null) {
                                onComplete()
                                return@logoSimpleLaunch
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

            // Check if deep search is enabled
            val deepSearch = SettingsFragment.isDeepSearchEnabled(requireContext())

            // Force refresh from filesystem
            var allGames = GameCache.getGamesForPlatform(platformName, forceRefresh = true, deepSearch = deepSearch)

            // Filter out hidden titles
            val hiddenTitles = SettingsFragment.getHiddenTitles(requireContext())[platformName] ?: emptySet()
            games = allGames.filter { game ->
                !hiddenTitles.contains(game.displayName)
            }

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
