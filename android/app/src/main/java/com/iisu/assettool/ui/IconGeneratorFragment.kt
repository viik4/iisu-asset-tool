package com.iisu.assettool.ui

import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.LinearLayoutManager
import coil.imageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import com.iisu.assettool.R
import com.iisu.assettool.data.ArtworkResult
import com.iisu.assettool.data.ArtworkScraper
import com.iisu.assettool.data.ArtworkType
import com.iisu.assettool.data.GameSearchResult
import com.iisu.assettool.data.Platform
import com.iisu.assettool.databinding.FragmentIconGeneratorBinding
import com.iisu.assettool.util.IisuDirectoryManager
import com.iisu.assettool.util.ImageProcessor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream

/**
 * Icon Generator Fragment
 *
 * Replicates the desktop Icon Generator flow:
 * 1. User enters game name and selects platform
 * 2. Search returns list of matching games from SteamGridDB
 * 3. User selects a game from results
 * 4. Artwork is fetched and the platform border is applied
 * 5. User can save the generated icon
 */
class IconGeneratorFragment : Fragment() {

    private var _binding: FragmentIconGeneratorBinding? = null
    private val binding get() = _binding!!

    private val artworkScraper = ArtworkScraper()
    private val imageProcessor = ImageProcessor()
    private var currentBitmap: Bitmap? = null
    private var selectedGame: GameSearchResult? = null
    private var currentArtworkList: List<ArtworkResult> = emptyList()
    private var currentArtworkIndex = 0
    private var selectedPlatformIndex = 0
    private var selectedArtworkTypeIndex = 0
    private var isSearchCollapsed = false

    private lateinit var gameSearchAdapter: GameSearchAdapter
    private lateinit var artworkAdapter: SearchResultsAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentIconGeneratorBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Load SteamGridDB API key from settings
        val sgdbApiKey = SettingsFragment.getSteamGridDBApiKey(requireContext())
        if (sgdbApiKey != null) {
            artworkScraper.setSteamGridDBApiKey(sgdbApiKey)
        }

        setupPlatformSpinner()
        setupArtworkTypeSpinner()
        setupSearchResultsRecycler()
        setupSearchButton()
        setupSaveButton()
        setupCollapseExpand()
    }

    /**
     * Artwork types available in the spinner
     */
    private enum class ArtworkTypeOption(val displayName: String, val type: ArtworkType) {
        ICON("Icon", ArtworkType.ICON),
        HERO("Hero", ArtworkType.HERO),
        LOGO("Logo", ArtworkType.LOGO),
        SCREENSHOT("Screenshot", ArtworkType.SCREENSHOT)
    }

    private fun setupPlatformSpinner() {
        val platforms = Platform.values().map { it.displayName }
        val adapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_dropdown_item,
            platforms
        )
        binding.spinnerPlatform.setAdapter(adapter)
        binding.spinnerPlatform.setText(platforms.firstOrNull() ?: "", false)
        binding.spinnerPlatform.setOnItemClickListener { _, _, position, _ ->
            selectedPlatformIndex = position
        }
    }

    private fun setupArtworkTypeSpinner() {
        val artworkTypes = ArtworkTypeOption.values().map { it.displayName }
        val adapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_dropdown_item,
            artworkTypes
        )
        binding.spinnerArtworkType.setAdapter(adapter)
        binding.spinnerArtworkType.setText(artworkTypes.firstOrNull() ?: "", false)

        // When artwork type changes, re-fetch artwork for selected game
        binding.spinnerArtworkType.setOnItemClickListener { _, _, position, _ ->
            selectedArtworkTypeIndex = position
            // Only fetch if a game is already selected
            selectedGame?.let { game ->
                fetchArtworkForSelectedGame(game)
            }
        }
    }

    private fun getSelectedArtworkType(): ArtworkType {
        return ArtworkTypeOption.values().getOrElse(selectedArtworkTypeIndex) { ArtworkTypeOption.ICON }.type
    }

    private fun setupCollapseExpand() {
        // Collapse button in search card header
        binding.btnCollapseSearch.setOnClickListener {
            collapseSearch()
        }

        // Expand button in status row
        binding.btnExpandSearch.setOnClickListener {
            expandSearch()
        }
    }

    private fun collapseSearch() {
        isSearchCollapsed = true
        binding.layoutExpandableContent.visibility = View.GONE
        binding.btnCollapseSearch.visibility = View.GONE
        binding.btnExpandSearch.visibility = View.VISIBLE
    }

    private fun expandSearch() {
        isSearchCollapsed = false
        binding.layoutExpandableContent.visibility = View.VISIBLE
        binding.btnCollapseSearch.visibility = View.VISIBLE
        binding.btnExpandSearch.visibility = View.GONE
    }

    private fun setupSearchResultsRecycler() {
        // Adapter for game search results (vertical list)
        gameSearchAdapter = GameSearchAdapter { game ->
            selectedGame = game
            fetchArtworkForSelectedGame(game)
        }

        // Adapter for artwork options (2-column grid)
        artworkAdapter = SearchResultsAdapter { artwork ->
            applyBorderToArtwork(artwork)
        }

        binding.recyclerSearchResults.apply {
            layoutManager = LinearLayoutManager(context, LinearLayoutManager.VERTICAL, false)
            adapter = gameSearchAdapter

            // Disable ViewPager swiping when user is scrolling through results
            addOnScrollListener(object : androidx.recyclerview.widget.RecyclerView.OnScrollListener() {
                override fun onScrollStateChanged(recyclerView: androidx.recyclerview.widget.RecyclerView, newState: Int) {
                    val iconsFragment = parentFragment as? IconsFragment
                    when (newState) {
                        androidx.recyclerview.widget.RecyclerView.SCROLL_STATE_DRAGGING,
                        androidx.recyclerview.widget.RecyclerView.SCROLL_STATE_SETTLING -> {
                            // User is actively scrolling - disable ViewPager swipe
                            iconsFragment?.setSwipeEnabled(false)
                        }
                        androidx.recyclerview.widget.RecyclerView.SCROLL_STATE_IDLE -> {
                            // User stopped scrolling - re-enable ViewPager swipe
                            iconsFragment?.setSwipeEnabled(true)
                        }
                    }
                }
            })
        }
    }

    private fun setupSearchButton() {
        binding.buttonSearch.setOnClickListener {
            val query = binding.editTextSearch.text.toString().trim()
            if (query.isNotEmpty()) {
                searchGames(query)
            } else {
                Toast.makeText(context, "Please enter a game name", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun setupSaveButton() {
        binding.buttonSave.setOnClickListener {
            currentBitmap?.let { bitmap ->
                saveToGallery(bitmap)
            } ?: Toast.makeText(context, "No image to save", Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * Step 1: Search for games by name
     */
    private fun searchGames(query: String) {
        binding.progressBar.visibility = View.VISIBLE
        binding.buttonSearch.isEnabled = false
        binding.recyclerSearchResults.visibility = View.GONE
        selectedGame = null
        currentArtworkList = emptyList()

        lifecycleScope.launch {
            try {
                val games = withContext(Dispatchers.IO) {
                    artworkScraper.searchGames(query)
                }

                if (games.isNotEmpty()) {
                    gameSearchAdapter.submitList(games)
                    binding.recyclerSearchResults.visibility = View.VISIBLE
                    binding.textResultCount.text = "${games.size} games found - tap to select"

                    // Switch to vertical layout for game list
                    binding.recyclerSearchResults.apply {
                        layoutManager = LinearLayoutManager(context, LinearLayoutManager.VERTICAL, false)
                        adapter = gameSearchAdapter
                    }
                } else {
                    gameSearchAdapter.submitList(emptyList())
                    binding.recyclerSearchResults.visibility = View.GONE
                    Toast.makeText(context, R.string.error_no_results, Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                gameSearchAdapter.submitList(emptyList())
                binding.recyclerSearchResults.visibility = View.GONE
                Toast.makeText(context, R.string.error_network, Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressBar.visibility = View.GONE
                binding.buttonSearch.isEnabled = true
            }
        }
    }

    /**
     * Step 2: Fetch artwork options for the selected game
     */
    private fun fetchArtworkForSelectedGame(game: GameSearchResult) {
        binding.progressBar.visibility = View.VISIBLE
        val artworkType = getSelectedArtworkType()
        val artworkTypeName = ArtworkTypeOption.values().find { it.type == artworkType }?.displayName ?: "artwork"
        binding.textResultCount.text = "Loading $artworkTypeName for ${game.name}..."

        lifecycleScope.launch {
            try {
                val artworks = withContext(Dispatchers.IO) {
                    artworkScraper.fetchArtworkForGame(game.id, artworkType)
                }

                if (artworks.isNotEmpty()) {
                    currentArtworkList = artworks
                    currentArtworkIndex = 0

                    // Auto-collapse the search section to give more room for artwork
                    collapseSearch()

                    // Show artwork options in 2-column vertical grid
                    artworkAdapter.submitList(artworks)
                    binding.recyclerSearchResults.apply {
                        layoutManager = GridLayoutManager(context, 2)
                        adapter = artworkAdapter

                        // Add scroll listener for artwork grid to disable ViewPager swiping
                        clearOnScrollListeners()
                        addOnScrollListener(object : androidx.recyclerview.widget.RecyclerView.OnScrollListener() {
                            override fun onScrollStateChanged(recyclerView: androidx.recyclerview.widget.RecyclerView, newState: Int) {
                                val iconsFragment = parentFragment as? IconsFragment
                                when (newState) {
                                    androidx.recyclerview.widget.RecyclerView.SCROLL_STATE_DRAGGING,
                                    androidx.recyclerview.widget.RecyclerView.SCROLL_STATE_SETTLING -> {
                                        iconsFragment?.setSwipeEnabled(false)
                                    }
                                    androidx.recyclerview.widget.RecyclerView.SCROLL_STATE_IDLE -> {
                                        iconsFragment?.setSwipeEnabled(true)
                                    }
                                }
                            }
                        })
                    }
                    binding.textResultCount.text = "${artworks.size} artwork options - tap to select"

                    // Auto-apply first artwork with border
                    applyBorderToArtwork(artworks.first())
                } else {
                    Toast.makeText(context, "No artwork found for this game", Toast.LENGTH_SHORT).show()
                    binding.textResultCount.text = "No artwork found"
                }
            } catch (e: Exception) {
                Toast.makeText(context, "Failed to load artwork", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressBar.visibility = View.GONE
            }
        }
    }

    /**
     * Step 3: Apply the platform border to the selected artwork (for icons only)
     * For heroes, logos, and screenshots, just display without border
     */
    private fun applyBorderToArtwork(artwork: ArtworkResult) {
        val selectedPlatform = Platform.values()[selectedPlatformIndex]
        val artworkType = getSelectedArtworkType()
        binding.progressBar.visibility = View.VISIBLE

        // Adjust preview height based on artwork type
        updatePreviewDimensions(artworkType)

        lifecycleScope.launch {
            try {
                // Download the artwork image
                val artworkBitmap = withContext(Dispatchers.IO) {
                    downloadBitmap(artwork.url)
                }

                if (artworkBitmap != null) {
                    // Only apply borders to icons, not to heroes/logos/screenshots
                    if (artworkType == ArtworkType.ICON || artworkType == ArtworkType.COVER) {
                        // Load the platform border from assets
                        val borderBitmap = withContext(Dispatchers.IO) {
                            loadBorderForPlatform(selectedPlatform)
                        }

                        if (borderBitmap != null) {
                            // Apply the border
                            val result = withContext(Dispatchers.Default) {
                                imageProcessor.applyBorder(artworkBitmap, borderBitmap)
                            }

                            currentBitmap = result
                            binding.imagePreview.setImageBitmap(result)
                            binding.buttonSave.isEnabled = true
                        } else {
                            // No border available, just show the artwork
                            currentBitmap = artworkBitmap
                            binding.imagePreview.setImageBitmap(artworkBitmap)
                            binding.buttonSave.isEnabled = true
                            Toast.makeText(context, "No border found for ${selectedPlatform.displayName}", Toast.LENGTH_SHORT).show()
                        }
                    } else {
                        // For heroes, logos, screenshots - no border, just display
                        currentBitmap = artworkBitmap
                        binding.imagePreview.setImageBitmap(artworkBitmap)
                        binding.buttonSave.isEnabled = true
                    }
                } else {
                    Toast.makeText(context, "Failed to download artwork", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Toast.makeText(context, "Failed to process image", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressBar.visibility = View.GONE
            }
        }
    }

    /**
     * Adjust the preview ImageView dimensions based on artwork type.
     * Icons are square, heroes are wide (16:9 ratio).
     */
    private fun updatePreviewDimensions(artworkType: ArtworkType) {
        val layoutParams = binding.imagePreview.layoutParams
        val density = resources.displayMetrics.density

        when (artworkType) {
            ArtworkType.HERO, ArtworkType.SCREENSHOT -> {
                // Wide aspect ratio (approximately 16:9)
                layoutParams.height = (160 * density).toInt()
            }
            else -> {
                // Square aspect ratio for icons/logos
                layoutParams.height = (280 * density).toInt()
            }
        }
        binding.imagePreview.layoutParams = layoutParams
    }

    private suspend fun downloadBitmap(url: String): Bitmap? {
        return withContext(Dispatchers.IO) {
            try {
                val request = ImageRequest.Builder(requireContext())
                    .data(url)
                    .allowHardware(false)
                    .build()
                val result = requireContext().imageLoader.execute(request)
                if (result is SuccessResult) {
                    (result.drawable as? android.graphics.drawable.BitmapDrawable)?.bitmap
                } else null
            } catch (e: Exception) {
                null
            }
        }
    }

    private fun loadBorderForPlatform(platform: Platform): Bitmap? {
        return try {
            // Map platform to border filename
            val borderFilename = getBorderFilename(platform)
            requireContext().assets.open("borders/$borderFilename").use { inputStream ->
                BitmapFactory.decodeStream(inputStream)
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun getBorderFilename(platform: Platform): String {
        // Map platforms to available border files in assets/borders/
        return when (platform) {
            Platform.NES -> "NES.png"
            Platform.SNES -> "SNES.png"
            Platform.N64 -> "N64.png"
            Platform.N64DD -> "N64.png"
            Platform.GAMECUBE -> "Gamecube.png"
            Platform.WII -> "Wii.png"
            Platform.WII_U -> "Wii_U.png"
            Platform.SWITCH -> "Switch.png"
            Platform.GAMEBOY -> "Game_Boy.png"
            Platform.GAMEBOY_COLOR -> "Game_Boy_Color.png"
            Platform.GBA -> "Game_Boy_Advance.png"
            Platform.DS -> "NINTENDO_DS.png"
            Platform.THREEDS -> "NINTENDO_3DS.png"
            Platform.VIRTUAL_BOY -> "border.png"  // Fallback
            Platform.PS1 -> "PSX.png"
            Platform.PS2 -> "PS2.png"
            Platform.PS3 -> "PS3.png"
            Platform.PS4 -> "PS4.png"
            Platform.PS5 -> "PS4.png"  // Fallback to PS4
            Platform.PSP -> "PSP.png"
            Platform.VITA -> "PS_Vita.png"
            Platform.XBOX -> "Xbox.png"
            Platform.XBOX360 -> "XBOX_360.png"
            Platform.XBOXONE -> "Xbox.png"  // Fallback
            Platform.XBOXSERIES -> "Xbox.png"  // Fallback
            Platform.MASTER_SYSTEM -> "border.png"  // Fallback
            Platform.GENESIS -> "GENESIS.png"
            Platform.SEGA_CD -> "GENESIS.png"  // Fallback
            Platform.SEGA_32X -> "GENESIS.png"  // Fallback
            Platform.SATURN -> "Saturn.png"
            Platform.DREAMCAST -> "Dreamcast.png"
            Platform.GAMEGEAR -> "Game_Gear.png"
            Platform.NEOGEO -> "border.png"  // Fallback
            Platform.NEOGEO_CD -> "border.png"  // Fallback
            Platform.NEOGEO_POCKET -> "Neo_Geo_Pocket_Color.png"  // Use color version
            Platform.NEOGEO_POCKET_COLOR -> "Neo_Geo_Pocket_Color.png"
            Platform.ATARI2600 -> "border.png"  // Fallback
            Platform.ATARI5200 -> "border.png"  // Fallback
            Platform.ATARI7800 -> "border.png"  // Fallback
            Platform.ATARI_JAGUAR -> "border.png"  // Fallback
            Platform.ATARI_LYNX -> "border.png"  // Fallback
            Platform.ARCADE -> "border.png"  // Fallback
            Platform.MAME -> "border.png"  // Fallback
            Platform.FBA -> "border.png"  // Fallback
            Platform.TURBOGRAFX -> "border.png"  // Fallback
            Platform.TURBOGRAFX_CD -> "border.png"  // Fallback
            Platform.WONDERSWAN -> "border.png"  // Fallback
            Platform.WONDERSWAN_COLOR -> "border.png"  // Fallback
            Platform.COLECOVISION -> "border.png"  // Fallback
            Platform.INTELLIVISION -> "border.png"  // Fallback
            Platform.PC -> "border.png"  // Fallback
            Platform.DOS -> "border.png"  // Fallback
            Platform.SCUMMVM -> "border.png"  // Fallback
            Platform.ANDROID -> "Android.png"
        }
    }

    /**
     * Create a safe folder/file name from game title.
     * Matches the safe_slug function from the desktop Python version.
     */
    private fun safeSlug(name: String): String {
        return name.trim()
            .replace(Regex("[^\\w\\-\\s]"), "")  // Keep only word chars, hyphens, spaces
            .replace(Regex("\\s+"), "_")          // Spaces to underscores
            .take(180)                            // Limit length
    }

    /**
     * Get the filename for the current artwork type.
     * Matches desktop/iiSU naming: icon.png, title.png, hero_1.png, slide_1.png
     */
    private fun getArtworkFilename(artworkType: ArtworkType, extension: String = "png"): String {
        return when (artworkType) {
            ArtworkType.ICON, ArtworkType.COVER -> "icon.$extension"
            ArtworkType.LOGO -> "title.$extension"
            ArtworkType.HERO -> "hero_1.$extension"
            ArtworkType.SCREENSHOT -> "slide_1.$extension"
            else -> "icon.$extension"
        }
    }

    /**
     * Delete existing asset files before saving new one.
     * Removes both .png and .jpg versions to avoid duplicates.
     */
    private fun deleteExistingAsset(folder: File, baseName: String) {
        listOf("png", "jpg", "jpeg").forEach { ext ->
            val file = File(folder, "$baseName.$ext")
            if (file.exists()) file.delete()
        }
        // Also delete numbered versions for heroes/slides
        if (baseName == "hero" || baseName == "slide") {
            for (i in 1..10) {
                listOf("png", "jpg", "jpeg").forEach { ext ->
                    val file = File(folder, "${baseName}_$i.$ext")
                    if (file.exists()) file.delete()
                }
            }
        }
    }

    /**
     * Get the base name for the artwork type (used for deletion).
     */
    private fun getArtworkBaseName(artworkType: ArtworkType): String {
        return when (artworkType) {
            ArtworkType.ICON, ArtworkType.COVER -> "icon"
            ArtworkType.LOGO -> "title"
            ArtworkType.HERO -> "hero"
            ArtworkType.SCREENSHOT -> "slide"
            else -> "icon"
        }
    }

    /**
     * Find matching game folder in iiSU library.
     * Searches for exact match or similar folder names.
     */
    private fun findIisuGameFolder(platform: Platform, gameName: String): File? {
        val platformDir = IisuDirectoryManager.getPlatformDir(platform.iisuFolder)
        if (!platformDir.exists()) return null

        val sluggedName = safeSlug(gameName)
        val normalizedSearch = gameName.lowercase().replace(Regex("[^a-z0-9]"), "")

        // Look for matching folder
        return platformDir.listFiles()?.find { folder ->
            if (!folder.isDirectory || folder.name.startsWith(".")) return@find false

            val folderName = folder.name
            val normalizedFolder = folderName.lowercase().replace(Regex("[^a-z0-9]"), "")

            // Exact match or close enough
            folderName == sluggedName ||
            folderName.equals(gameName, ignoreCase = true) ||
            normalizedFolder == normalizedSearch ||
            normalizedFolder.contains(normalizedSearch) ||
            normalizedSearch.contains(normalizedFolder)
        }
    }

    private fun saveToGallery(bitmap: Bitmap) {
        lifecycleScope.launch {
            try {
                val gameName = selectedGame?.name ?: "Unknown"
                val platform = Platform.values()[selectedPlatformIndex]
                val artworkType = getSelectedArtworkType()

                // Get export format settings
                val exportFormat = SettingsFragment.getExportFormat(requireContext())
                val jpegQuality = SettingsFragment.getJpegQuality(requireContext())

                val (format, extension, quality) = if (exportFormat == "JPEG") {
                    Triple(Bitmap.CompressFormat.JPEG, "jpg", jpegQuality)
                } else {
                    Triple(Bitmap.CompressFormat.PNG, "png", 100)
                }

                val artworkFilename = getArtworkFilename(artworkType, extension)
                val artworkBaseName = getArtworkBaseName(artworkType)

                withContext(Dispatchers.IO) {
                    // Check if iiSU library exists and has matching game folder
                    val iisuGameFolder = if (IisuDirectoryManager.isIisuInstalled()) {
                        findIisuGameFolder(platform, gameName)
                    } else null

                    if (iisuGameFolder != null) {
                        // Save directly to iiSU library (replacing existing)
                        deleteExistingAsset(iisuGameFolder, artworkBaseName)

                        val outputFile = File(iisuGameFolder, artworkFilename)
                        FileOutputStream(outputFile).use { out ->
                            bitmap.compress(format, quality, out)
                        }

                        withContext(Dispatchers.Main) {
                            val artworkTypeName = ArtworkTypeOption.values().find { it.type == artworkType }?.displayName ?: "Image"
                            Toast.makeText(context, "$artworkTypeName saved to iiSU library!", Toast.LENGTH_SHORT).show()
                        }
                    } else {
                        // Fallback: Save to gallery with folder structure
                        val sluggedName = safeSlug(gameName)
                        val relativePath = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            "${Environment.DIRECTORY_PICTURES}/iiSU Asset Tool/${platform.iisuFolder}/$sluggedName"
                        } else {
                            "${Environment.DIRECTORY_PICTURES}/iiSU Asset Tool"
                        }

                        val contentValues = ContentValues().apply {
                            put(MediaStore.MediaColumns.DISPLAY_NAME, artworkFilename)
                            put(MediaStore.MediaColumns.MIME_TYPE, if (extension == "jpg") "image/jpeg" else "image/png")
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
                            }
                        }

                        val resolver = requireContext().contentResolver
                        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, contentValues)

                        uri?.let {
                            val outputStream: OutputStream? = resolver.openOutputStream(it)
                            outputStream?.use { stream ->
                                bitmap.compress(format, quality, stream)
                            }
                        }

                        withContext(Dispatchers.Main) {
                            val artworkTypeName = ArtworkTypeOption.values().find { it.type == artworkType }?.displayName ?: "Image"
                            Toast.makeText(context, "$artworkTypeName saved to gallery!", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            } catch (e: Exception) {
                Toast.makeText(context, "Failed to save image", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
