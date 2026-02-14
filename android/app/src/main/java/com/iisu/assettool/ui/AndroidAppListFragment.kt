package com.iisu.assettool.ui

import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.PopupMenu
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentAndroidAppListBinding
import com.iisu.assettool.util.AndroidAppAdapter
import com.iisu.assettool.util.AndroidAppInfo
import com.iisu.assettool.util.ArtworkScraper
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import com.iisu.assettool.util.ViewAnimationUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

/**
 * Fragment for displaying and managing Android apps.
 * Shows a list of Android apps with options to generate icons, heroes, and logos.
 */
class AndroidAppListFragment : Fragment() {

    private var _binding: FragmentAndroidAppListBinding? = null
    private val binding get() = _binding!!

    private lateinit var androidAppAdapter: AndroidAppAdapter
    private lateinit var artworkScraper: ArtworkScraper
    private var apps: List<AndroidAppInfo> = emptyList()

    // Track pending soundbyte operation
    private var pendingSoundbtyeApp: AndroidAppInfo? = null

    // Activity result launcher for soundbyte file picker
    private val pickSoundbyteLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedSoundbyte(it) } }

    companion object {
        private const val TAG = "AndroidAppListFragment"

        fun newInstance(): AndroidAppListFragment {
            return AndroidAppListFragment()
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentAndroidAppListBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        artworkScraper = ArtworkScraper(requireContext())

        // Set API keys if available
        SettingsFragment.getSteamGridDBApiKey(requireContext())?.let {
            artworkScraper.setSteamGridDBApiKey(it)
        }

        setupUI()
        setupRecyclerView()
        loadApps()
    }

    private fun setupUI() {
        // Set title
        binding.textTitle.text = "Android Apps"

        // Back button
        binding.btnBack.setOnClickListener {
            parentFragmentManager.popBackStack()
        }

        // Refresh button
        binding.btnRefresh.setOnClickListener {
            loadApps(forceRefresh = true)
            Toast.makeText(context, "Refreshed app list", Toast.LENGTH_SHORT).show()
        }
    }

    private fun setupRecyclerView() {
        androidAppAdapter = AndroidAppAdapter(
            onAppClick = { app -> onAndroidAppSelected(app) },
            onLongPress = { app, view -> showAppContextMenu(app, view) }
        )

        binding.recyclerViewApps.apply {
            // Use 5 columns for landscape tablet-style layout
            layoutManager = GridLayoutManager(context, 5)
            adapter = androidAppAdapter
            ViewAnimationUtils.applyLayoutAnimation(this)
        }
    }

    @Suppress("UNUSED_PARAMETER")
    private fun loadApps(forceRefresh: Boolean = false) {
        ViewAnimationUtils.fadeIn(binding.progressBar, 150)
        ViewAnimationUtils.fadeOut(binding.textEmptyState)

        viewLifecycleOwner.lifecycleScope.launch {
            val startTime = System.currentTimeMillis()

            apps = withContext(Dispatchers.IO) {
                IisuDirectoryManager.getAndroidApps()
            }

            val loadTime = System.currentTimeMillis() - startTime
            Log.d(TAG, "Loaded ${apps.size} Android apps in ${loadTime}ms")

            if (_binding == null) return@launch

            ViewAnimationUtils.fadeOut(binding.progressBar)

            if (apps.isEmpty()) {
                binding.textEmptyState.text = "No Android apps found.\n\nConfigure the Android apps path in Settings."
                ViewAnimationUtils.fadeIn(binding.textEmptyState)
                ViewAnimationUtils.fadeOut(binding.recyclerViewApps)
            } else {
                ViewAnimationUtils.fadeOut(binding.textEmptyState)
                ViewAnimationUtils.fadeIn(binding.recyclerViewApps)
                androidAppAdapter.submitList(apps)
            }

            updateStats()
        }
    }

    private fun updateStats() {
        val appCount = apps.size
        val missingCount = apps.sumOf { it.missingCount }

        binding.textAppCount.text = "$appCount apps"
        binding.textAssetStats.text = if (missingCount > 0) "$missingCount missing assets" else "All assets present"
    }

    private fun onAndroidAppSelected(app: AndroidAppInfo) {
        // Navigate to app detail fragment for asset editing
        Log.d(TAG, "Android app selected: ${app.packageName}")

        val appDetailFragment = AndroidAppDetailFragment.newInstance(app.packageName)

        parentFragmentManager.beginTransaction()
            .setCustomAnimations(
                R.anim.fragment_fade_enter,
                R.anim.fragment_fade_exit,
                R.anim.fragment_fade_enter,
                R.anim.fragment_fade_exit
            )
            .replace(R.id.fragment_container, appDetailFragment)
            .addToBackStack("android_app_detail")
            .commit()
    }

    // ==================== Context Menu ====================

    /**
     * Show context menu for an Android app on long-press
     */
    private fun showAppContextMenu(app: AndroidAppInfo, anchorView: View) {
        val popup = PopupMenu(requireContext(), anchorView)
        popup.menuInflater.inflate(R.menu.context_android_app, popup.menu)

        popup.setOnMenuItemClickListener { menuItem ->
            when (menuItem.itemId) {
                R.id.action_edit_search_query -> {
                    showEditSearchQueryDialog(app)
                    true
                }
                R.id.action_generate_icon -> {
                    generateIconForApp(app)
                    true
                }
                R.id.action_generate_hero -> {
                    generateHeroForApp(app)
                    true
                }
                R.id.action_generate_logo -> {
                    generateLogoForApp(app)
                    true
                }
                R.id.action_manual_search -> {
                    manualSearch(app)
                    true
                }
                R.id.action_generate_all -> {
                    generateAllForApp(app)
                    true
                }
                R.id.action_add_soundbyte -> {
                    addSoundbyte(app)
                    true
                }
                R.id.action_hide_title -> {
                    hideApp(app)
                    true
                }
                else -> false
            }
        }

        popup.show()
    }

    /**
     * Convert AndroidAppInfo to GameInfo for use with existing artwork scraper
     */
    private fun appToGameInfo(app: AndroidAppInfo): GameInfo {
        return GameInfo(
            name = app.packageName,
            folder = app.folder,
            hasIcon = app.hasIcon,
            hasHero = app.hasHero,
            hasLogo = app.hasLogo,
            iconFile = app.iconFile,
            heroFile = app.heroFile,
            logoFile = app.logoFile
        )
    }

    // ==================== Manual Search & Edit Query ====================

    /**
     * Show dialog to edit the search query for an app
     */
    private fun showEditSearchQueryDialog(app: AndroidAppInfo) {
        val gameInfo = appToGameInfo(app)

        val editText = EditText(requireContext()).apply {
            setText(gameInfo.searchName)
            setTextColor(resources.getColor(R.color.theme_text_primary, null))
            setHintTextColor(resources.getColor(R.color.theme_text_secondary, null))
            hint = "Enter search query..."
            setSingleLine(false)
            maxLines = 3
            setSelection(text.length)
        }

        val container = FrameLayout(requireContext()).apply {
            val padding = (16 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding / 2, padding, 0)
            addView(editText)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Edit Search Query")
            .setMessage("Enter the app title to search for artwork.\nOriginal: ${app.displayName}")
            .setView(container)
            .setPositiveButton("Search") { _, _ ->
                val query = editText.text.toString().trim()
                if (query.isNotEmpty()) {
                    val modifiedGame = gameInfo.copy(name = query)

                    Toast.makeText(
                        requireContext(),
                        "Searching for: $query",
                        Toast.LENGTH_SHORT
                    ).show()

                    generateIconForApp(app, modifiedGame)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /**
     * Manual search - let user search for a different game and generate all assets
     */
    private fun manualSearch(app: AndroidAppInfo) {
        val gameInfo = appToGameInfo(app)

        GameSearchDialog.show(
            context = requireContext(),
            gameInfo = gameInfo,
            artworkScraper = artworkScraper
        ) { selectedResult ->
            viewLifecycleOwner.lifecycleScope.launch {
                Toast.makeText(
                    requireContext(),
                    "Searching all artwork for: ${selectedResult.name}",
                    Toast.LENGTH_SHORT
                ).show()

                val modifiedGame = gameInfo.copy(name = selectedResult.name)
                generateAllAssetsForAppById(modifiedGame, selectedResult.id)
            }
        }
    }

    /**
     * Generate all assets (icon, hero, logo) for an app using a known SteamGridDB game ID.
     * Shows pickers for each asset type in sequence.
     */
    private fun generateAllAssetsForAppById(game: GameInfo, sgdbGameId: Int) {
        showIconPickerForAppById(game, sgdbGameId) {
            showHeroPickerForAppById(game, sgdbGameId) {
                showLogoPickerForAppById(game, sgdbGameId) {
                    Toast.makeText(
                        requireContext(),
                        "All assets complete for ${game.displayName}",
                        Toast.LENGTH_SHORT
                    ).show()
                    loadApps()
                }
            }
        }
    }

    /**
     * Show icon picker for an app using SteamGridDB game ID
     */
    private fun showIconPickerForAppById(game: GameInfo, sgdbGameId: Int, onComplete: () -> Unit) {
        var dialogCompleted = false
        var currentPickerDialog: ArtworkPickerDialog? = null
        var currentSquareOnly = SettingsFragment.isSquareIconsOnly(requireContext())

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, "android", currentSquareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                if (currentSquareOnly) {
                    withContext(Dispatchers.Main) {
                        AlertDialog.Builder(requireContext())
                            .setTitle("No Square Icons Found")
                            .setMessage("No square icons found.\n\nWould you like to try all icons?")
                            .setPositiveButton("Try All Icons") { _, _ ->
                                showIconPickerForAppByIdWithFilter(game, sgdbGameId, false, onComplete)
                            }
                            .setNegativeButton("Skip") { _, _ ->
                                onComplete()
                            }
                            .show()
                    }
                } else {
                    Toast.makeText(requireContext(), "No icons found", Toast.LENGTH_SHORT).show()
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
                            val success = withContext(Dispatchers.IO) {
                                artworkScraper.saveIconFromOption(selectedOption, game, "android")
                            }
                            if (success) {
                                Toast.makeText(requireContext(), "Icon saved", Toast.LENGTH_SHORT).show()
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
                    },
                    onFilterChanged = { newSquareOnly ->
                        currentSquareOnly = newSquareOnly
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, "android", newSquareOnly)
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
    private fun showIconPickerForAppByIdWithFilter(game: GameInfo, sgdbGameId: Int, squareOnly: Boolean, onComplete: () -> Unit) {
        var dialogCompleted = false
        var currentPickerDialog: ArtworkPickerDialog? = null
        var currentSquareOnly = squareOnly

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, "android", currentSquareOnly)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(requireContext(), "No icons found", Toast.LENGTH_SHORT).show()
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
                            val success = withContext(Dispatchers.IO) {
                                artworkScraper.saveIconFromOption(selectedOption, game, "android")
                            }
                            if (success) {
                                Toast.makeText(requireContext(), "Icon saved", Toast.LENGTH_SHORT).show()
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
                    },
                    onFilterChanged = { newSquareOnly ->
                        currentSquareOnly = newSquareOnly
                        viewLifecycleOwner.lifecycleScope.launch {
                            val newResult = artworkScraper.searchIconOptionsByGameId(sgdbGameId, game, "android", newSquareOnly)
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
     * Show hero picker for an app using SteamGridDB game ID
     */
    private fun showHeroPickerForAppById(game: GameInfo, sgdbGameId: Int, onComplete: () -> Unit) {
        var dialogCompleted = false

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchHeroOptionsByGameId(sgdbGameId, game)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(requireContext(), "No heroes found", Toast.LENGTH_SHORT).show()
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
                                Toast.makeText(requireContext(), "Hero saved", Toast.LENGTH_SHORT).show()
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
     * Show logo picker for an app using SteamGridDB game ID
     */
    private fun showLogoPickerForAppById(game: GameInfo, sgdbGameId: Int, onComplete: () -> Unit) {
        var dialogCompleted = false

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchLogoOptionsByGameId(sgdbGameId, game)

            if (_binding == null) return@launch

            if (searchResult.options.isEmpty()) {
                Toast.makeText(requireContext(), "No logos found", Toast.LENGTH_SHORT).show()
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
                                Toast.makeText(requireContext(), "Logo saved", Toast.LENGTH_SHORT).show()
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

    // ==================== Asset Generation ====================

    /**
     * Generate icon for app, optionally using a modified GameInfo (from edit search query)
     */
    private fun generateIconForApp(app: AndroidAppInfo, overrideGameInfo: GameInfo? = null) {
        val gameInfo = overrideGameInfo ?: appToGameInfo(app)
        val squareOnly = SettingsFragment.isSquareIconsOnly(requireContext())

        Toast.makeText(requireContext(), "Searching for icons...", Toast.LENGTH_SHORT).show()

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val searchResult = withContext(Dispatchers.IO) {
                    artworkScraper.searchIconOptions(gameInfo, "android", squareOnly)
                }

                if (_binding == null) return@launch

                if (searchResult.options.isEmpty()) {
                    Toast.makeText(requireContext(), "No icons found for ${app.displayName}", Toast.LENGTH_SHORT).show()
                    return@launch
                }

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                    searchResult = searchResult,
                    onOptionSelected = { selectedOption ->
                        viewLifecycleOwner.lifecycleScope.launch {
                            val success = withContext(Dispatchers.IO) {
                                artworkScraper.saveIconFromOption(selectedOption, gameInfo, "android")
                            }
                            if (success) {
                                Toast.makeText(requireContext(), "Icon saved for ${app.displayName}", Toast.LENGTH_SHORT).show()
                                loadApps()
                            } else {
                                Toast.makeText(requireContext(), "Failed to save icon", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                )
            } catch (e: Exception) {
                Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun generateHeroForApp(app: AndroidAppInfo) {
        val gameInfo = appToGameInfo(app)

        Toast.makeText(requireContext(), "Searching for heroes...", Toast.LENGTH_SHORT).show()

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val searchResult = withContext(Dispatchers.IO) {
                    artworkScraper.searchHeroOptions(gameInfo, "android")
                }

                if (_binding == null) return@launch

                if (searchResult.options.isEmpty()) {
                    Toast.makeText(requireContext(), "No heroes found for ${app.displayName}", Toast.LENGTH_SHORT).show()
                    return@launch
                }

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.HERO,
                    searchResult = searchResult,
                    onOptionSelected = { selectedOption ->
                        viewLifecycleOwner.lifecycleScope.launch {
                            val success = withContext(Dispatchers.IO) {
                                artworkScraper.saveHeroFromOption(selectedOption, gameInfo)
                            }
                            if (success) {
                                Toast.makeText(requireContext(), "Hero saved for ${app.displayName}", Toast.LENGTH_SHORT).show()
                                loadApps()
                            } else {
                                Toast.makeText(requireContext(), "Failed to save hero", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                )
            } catch (e: Exception) {
                Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun generateLogoForApp(app: AndroidAppInfo) {
        val gameInfo = appToGameInfo(app)

        Toast.makeText(requireContext(), "Searching for logos...", Toast.LENGTH_SHORT).show()

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val searchResult = withContext(Dispatchers.IO) {
                    artworkScraper.searchLogoOptions(gameInfo, "android")
                }

                if (_binding == null) return@launch

                if (searchResult.options.isEmpty()) {
                    Toast.makeText(requireContext(), "No logos found for ${app.displayName}", Toast.LENGTH_SHORT).show()
                    return@launch
                }

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.LOGO,
                    searchResult = searchResult,
                    onOptionSelected = { selectedOption ->
                        viewLifecycleOwner.lifecycleScope.launch {
                            val success = withContext(Dispatchers.IO) {
                                artworkScraper.saveLogoFromOption(selectedOption, gameInfo)
                            }
                            if (success) {
                                Toast.makeText(requireContext(), "Logo saved for ${app.displayName}", Toast.LENGTH_SHORT).show()
                                loadApps()
                            } else {
                                Toast.makeText(requireContext(), "Failed to save logo", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                )
            } catch (e: Exception) {
                Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun generateAllForApp(app: AndroidAppInfo) {
        val gameInfo = appToGameInfo(app)

        Toast.makeText(requireContext(), "Generating all assets for ${app.displayName}...", Toast.LENGTH_SHORT).show()

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                var successCount = 0

                withContext(Dispatchers.IO) {
                    if (artworkScraper.scrapeIcon(gameInfo, "android")) successCount++
                    if (artworkScraper.scrapeHero(gameInfo, "android")) successCount++
                    if (artworkScraper.scrapeLogo(gameInfo, "android")) successCount++
                }

                if (_binding == null) return@launch

                Toast.makeText(
                    requireContext(),
                    "Generated $successCount/3 assets for ${app.displayName}",
                    Toast.LENGTH_SHORT
                ).show()

                loadApps()
            } catch (e: Exception) {
                Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    // ==================== Soundbyte ====================

    private fun addSoundbyte(app: AndroidAppInfo) {
        pendingSoundbtyeApp = app
        pickSoundbyteLauncher.launch("audio/*")
    }

    private fun handlePickedSoundbyte(uri: Uri) {
        val app = pendingSoundbtyeApp ?: return
        pendingSoundbtyeApp = null

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val mimeType = requireContext().contentResolver.getType(uri)
                val extension = when {
                    mimeType?.contains("flac") == true -> "flac"
                    mimeType?.contains("ogg") == true -> "ogg"
                    mimeType?.contains("wav") == true -> "wav"
                    else -> "mp3"
                }

                val targetFile = File(app.folder, "music.$extension")

                // Check if music file already exists
                val existingMusic = listOf("mp3", "ogg", "flac", "wav").firstOrNull { ext ->
                    File(app.folder, "music.$ext").exists()
                }

                if (existingMusic != null) {
                    withContext(Dispatchers.Main) {
                        MaterialAlertDialogBuilder(requireContext())
                            .setTitle("Soundbyte Exists")
                            .setMessage("\"${app.displayName}\" already has a soundbyte (music.$existingMusic).\n\nOverwrite it?")
                            .setPositiveButton("Overwrite") { _, _ ->
                                performSoundbyteCopy(uri, targetFile, app)
                            }
                            .setNegativeButton("Cancel", null)
                            .show()
                    }
                } else {
                    performSoundbyteCopy(uri, targetFile, app)
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun performSoundbyteCopy(uri: Uri, targetFile: File, app: AndroidAppInfo) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    // Delete any existing music files
                    listOf("mp3", "ogg", "flac", "wav").forEach { ext ->
                        val existing = File(app.folder, "music.$ext")
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
                            "Soundbyte added to \"${app.displayName}\"",
                            Toast.LENGTH_SHORT
                        ).show()
                    } else {
                        Toast.makeText(requireContext(), "Failed to save soundbyte", Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    // ==================== Hide Title ====================

    private fun hideApp(app: AndroidAppInfo) {
        SettingsFragment.hideTitle(requireContext(), "android", app.displayName)
        Toast.makeText(requireContext(), "\"${app.displayName}\" hidden", Toast.LENGTH_SHORT).show()

        // Filter hidden apps from the list
        val hiddenTitles = SettingsFragment.getHiddenTitles(requireContext())["android"] ?: emptySet()
        val filteredApps = apps.filter { !hiddenTitles.contains(it.displayName) }
        androidAppAdapter.submitList(filteredApps)
        binding.textAppCount.text = "${filteredApps.size} apps"
    }

    override fun onResume() {
        super.onResume()
        // Refresh to apply any hidden title changes from settings
        if (_binding != null && apps.isNotEmpty()) {
            val hiddenTitles = SettingsFragment.getHiddenTitles(requireContext())["android"] ?: emptySet()
            val filteredApps = apps.filter { !hiddenTitles.contains(it.displayName) }
            androidAppAdapter.submitList(filteredApps)
            binding.textAppCount.text = "${filteredApps.size} apps"
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
