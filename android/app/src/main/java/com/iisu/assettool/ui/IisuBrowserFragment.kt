package com.iisu.assettool.ui

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.DocumentsContract
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.documentfile.provider.DocumentFile
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentIisuBrowserBinding
import com.iisu.assettool.util.GameCache
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import com.iisu.assettool.util.PlatformAdapter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * iiSU Browser Fragment
 *
 * Browse and manage iiSU platform assets directly on the device.
 * Features:
 * - View all platforms with their iiSU-style icons
 * - See ROMs and missing artwork counts
 * - Batch scrape missing icons/covers
 * - Save directly to iiSU directory structure
 */
class IisuBrowserFragment : Fragment() {

    private var _binding: FragmentIisuBrowserBinding? = null
    private val binding get() = _binding!!

    private lateinit var platformAdapter: PlatformAdapter

    companion object {
        private const val TAG = "IisuBrowserFragment"
        private const val PREFS_NAME = "iisu_asset_tool_prefs"
        private const val PREF_ROM_PATH = "custom_rom_path"
    }

    // Folder picker launcher
    private val folderPickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri ->
        uri?.let { handleSelectedFolder(it) }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentIisuBrowserBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Load saved ROM path from preferences
        loadSavedRomPath()

        // Setup button click listener
        binding.btnSelectRomFolder.setOnClickListener {
            openFolderPicker()
        }

        // Debug: Log iiSU detection
        debugIisuDetection()

        if (IisuDirectoryManager.isIisuInstalled()) {
            showIisuBrowser()
        } else {
            showNotInstalled()
        }
    }

    private fun loadSavedRomPath() {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val savedPath = prefs.getString(PREF_ROM_PATH, null)
        if (savedPath != null) {
            val file = java.io.File(savedPath)
            if (file.exists() && file.isDirectory) {
                IisuDirectoryManager.setCustomRomPath(file)
                Log.d(TAG, "Loaded saved ROM path: $savedPath")
            }
        }
    }

    private fun openFolderPicker() {
        try {
            folderPickerLauncher.launch(null)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to open folder picker", e)
            Toast.makeText(context, "Unable to open folder picker", Toast.LENGTH_SHORT).show()
        }
    }

    private fun handleSelectedFolder(uri: Uri) {
        Log.d(TAG, "Selected folder URI: $uri")

        // Convert content URI to file path
        val path = getPathFromUri(uri)
        if (path != null) {
            val file = java.io.File(path)
            Log.d(TAG, "Converted to file path: ${file.absolutePath}")

            if (file.exists() && file.isDirectory) {
                // Check if it has platform-named subdirectories (nes, snes, psx, etc.)
                val hasPlatforms = file.listFiles()?.any { platformDir ->
                    platformDir.isDirectory &&
                    !platformDir.name.startsWith(".") &&
                    IisuDirectoryManager.looksLikePlatformFolder(platformDir.name)
                } == true

                if (hasPlatforms) {
                    // Save to preferences
                    val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    prefs.edit().putString(PREF_ROM_PATH, file.absolutePath).apply()

                    // Set the custom path
                    IisuDirectoryManager.setCustomRomPath(file)

                    Toast.makeText(
                        context,
                        getString(R.string.rom_folder_selected, file.name),
                        Toast.LENGTH_SHORT
                    ).show()

                    // Clear caches and refresh the view
                    lifecycleScope.launch {
                        GameCache.clearCache(requireContext())
                        IisuDirectoryManager.clearCache()
                        if (IisuDirectoryManager.isIisuInstalled()) {
                            showIisuBrowser()
                        } else {
                            showNotInstalled()
                        }
                    }
                } else {
                    Toast.makeText(context, R.string.rom_folder_invalid, Toast.LENGTH_LONG).show()
                }
            } else {
                Toast.makeText(context, R.string.rom_folder_invalid, Toast.LENGTH_LONG).show()
            }
        } else {
            // Try using DocumentFile for SAF URIs
            handleSafUri(uri)
        }
    }

    private fun getPathFromUri(uri: Uri): String? {
        // Handle different URI schemes
        return when {
            uri.scheme == "file" -> uri.path
            uri.scheme == "content" -> {
                // Try to get path from content URI
                try {
                    val docId = DocumentsContract.getTreeDocumentId(uri)
                    if (docId.startsWith("primary:")) {
                        val path = docId.substringAfter("primary:")
                        "${Environment.getExternalStorageDirectory().absolutePath}/$path"
                    } else if (docId.contains(":")) {
                        // Handle other storage volumes
                        val split = docId.split(":")
                        if (split.size >= 2) {
                            "/storage/${split[0]}/${split[1]}"
                        } else null
                    } else null
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to get path from URI", e)
                    null
                }
            }
            else -> null
        }
    }

    private fun handleSafUri(uri: Uri) {
        // For SAF URIs that we can't convert to file paths,
        // try to use DocumentFile (limited functionality)
        val context = context ?: return
        val documentFile = DocumentFile.fromTreeUri(context, uri)

        if (documentFile != null && documentFile.isDirectory) {
            // Check if it has platform-named subdirectories
            val children = documentFile.listFiles()
            val hasPlatforms = children.any { child ->
                child.isDirectory &&
                child.name?.let { IisuDirectoryManager.looksLikePlatformFolder(it) } == true
            }

            if (hasPlatforms) {
                // We can't use SAF URIs directly with File API, show guidance
                Toast.makeText(
                    context,
                    "Please select a folder from Internal Storage > Android > media or the ROMs folder",
                    Toast.LENGTH_LONG
                ).show()
            } else {
                Toast.makeText(context, R.string.rom_folder_invalid, Toast.LENGTH_LONG).show()
            }
        } else {
            Toast.makeText(context, R.string.rom_folder_invalid, Toast.LENGTH_LONG).show()
        }
    }

    private fun debugIisuDetection() {
        Log.d(TAG, "=== iiSU Detection Debug ===")

        // Clear cache to force fresh detection
        IisuDirectoryManager.clearCache()

        val root = IisuDirectoryManager.getIisuRoot()
        Log.d(TAG, "iiSU root path: ${root.absolutePath}")
        Log.d(TAG, "iiSU root exists: ${root.exists()}")
        Log.d(TAG, "iiSU root isDirectory: ${root.isDirectory}")
        Log.d(TAG, "iiSU root canRead: ${root.canRead()}")
        Log.d(TAG, "isIisuInstalled(): ${IisuDirectoryManager.isIisuInstalled()}")

        if (root.exists() && root.canRead()) {
            val contents = root.listFiles()
            Log.d(TAG, "iiSU root contents: ${contents?.map { it.name }}")
        }

        // Check Android/data folder for iiSU packages
        val androidDataDir = java.io.File(Environment.getExternalStorageDirectory(), "Android/data")
        Log.d(TAG, "Android/data exists: ${androidDataDir.exists()}")
        Log.d(TAG, "Android/data canRead: ${androidDataDir.canRead()}")

        if (androidDataDir.exists() && androidDataDir.canRead()) {
            val iisuPackages = androidDataDir.listFiles()?.filter {
                it.name.contains("iisu", ignoreCase = true)
            }
            Log.d(TAG, "Found iiSU-related packages: ${iisuPackages?.map { it.name }}")

            // Deep exploration of iiSU package structure
            iisuPackages?.forEach { pkg ->
                Log.d(TAG, "=== Exploring ${pkg.name} ===")
                exploreDirectory(pkg, 0, 3)  // Explore up to 3 levels deep
            }
        }

        // Also check if ROMs might be in a shared location
        val externalStorage = Environment.getExternalStorageDirectory()
        Log.d(TAG, "=== Checking common ROM locations ===")

        // Check for ROMs folder at root
        val romsDir = java.io.File(externalStorage, "ROMs")
        if (romsDir.exists()) {
            Log.d(TAG, "Found ROMs dir at: ${romsDir.absolutePath}")
            Log.d(TAG, "  Contents: ${romsDir.listFiles()?.take(10)?.map { it.name }}")
        }

        // Check for ES-DE folder (often used with iiSU)
        val esdeDir = java.io.File(externalStorage, "ES-DE")
        if (esdeDir.exists()) {
            Log.d(TAG, "Found ES-DE dir at: ${esdeDir.absolutePath}")
            Log.d(TAG, "  ES-DE contents: ${esdeDir.listFiles()?.map { it.name }}")
            val esdeRoms = java.io.File(esdeDir, "ROMs")
            if (esdeRoms.exists()) {
                val romPlatforms = esdeRoms.listFiles()?.take(15)?.map { it.name }
                Log.d(TAG, "  ES-DE/ROMs contents: $romPlatforms")
                // Check first platform for ROMs
                esdeRoms.listFiles()?.firstOrNull { it.isDirectory }?.let { platform ->
                    val roms = platform.listFiles()?.take(5)?.map { it.name }
                    Log.d(TAG, "  First platform (${platform.name}) ROMs: $roms")
                }
            }
        }

        // Check for RetroArch folder
        val retroarchDir = java.io.File(externalStorage, "RetroArch")
        if (retroarchDir.exists()) {
            Log.d(TAG, "Found RetroArch dir at: ${retroarchDir.absolutePath}")
        }

        // Check the iiSU Launcher media path (most common location for ROMs)
        val iisuMediaPath = java.io.File(externalStorage, "Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles")
        Log.d(TAG, "=== Checking iiSU Media Path ===")
        Log.d(TAG, "iiSU media path: ${iisuMediaPath.absolutePath}")
        Log.d(TAG, "iiSU media path exists: ${iisuMediaPath.exists()}")
        if (iisuMediaPath.exists()) {
            val platforms = iisuMediaPath.listFiles()?.map { it.name }
            Log.d(TAG, "iiSU media path contents: $platforms")
        }

        // Also check Android/media folder in general
        val androidMediaDir = java.io.File(externalStorage, "Android/media")
        if (androidMediaDir.exists() && androidMediaDir.canRead()) {
            val mediaPackages = androidMediaDir.listFiles()?.filter {
                it.name.contains("iisu", ignoreCase = true)
            }
            Log.d(TAG, "Found iiSU packages in Android/media: ${mediaPackages?.map { it.name }}")
        }

        Log.d(TAG, "=== End Debug ===")
    }

    /**
     * Recursively explore directory structure for debugging
     */
    private fun exploreDirectory(dir: java.io.File, depth: Int, maxDepth: Int) {
        if (depth > maxDepth) return

        val indent = "  ".repeat(depth)
        val contents = dir.listFiles()

        if (contents == null) {
            Log.d(TAG, "$indent${dir.name}/ (cannot read)")
            return
        }

        Log.d(TAG, "$indent${dir.name}/")
        contents.sortedBy { it.name }.forEach { file ->
            if (file.isDirectory) {
                // Skip Android system directories
                if (file.name in listOf("cache", "code_cache", "shared_prefs", "databases", "lib")) {
                    Log.d(TAG, "$indent  ${file.name}/ (system dir, skipped)")
                } else {
                    exploreDirectory(file, depth + 1, maxDepth)
                }
            } else {
                val size = if (file.length() > 1024 * 1024) {
                    "${file.length() / (1024 * 1024)}MB"
                } else if (file.length() > 1024) {
                    "${file.length() / 1024}KB"
                } else {
                    "${file.length()}B"
                }
                Log.d(TAG, "$indent  ${file.name} ($size)")
            }
        }
    }

    private fun showNotInstalled() {
        binding.layoutNotInstalled.visibility = View.VISIBLE
        binding.layoutBrowser.visibility = View.GONE

        // Check if iiSU package exists but is empty (vs not installed at all)
        val androidDataDir = java.io.File(Environment.getExternalStorageDirectory(), "Android/data")
        val iisuPackageExists = androidDataDir.listFiles()?.any {
            it.name.contains("iisu", ignoreCase = true)
        } == true

        // Check for ES-DE ROMs location as a fallback source
        val esdeRoms = java.io.File(Environment.getExternalStorageDirectory(), "ES-DE/ROMs")
        val hasEsdeRoms = esdeRoms.exists() && esdeRoms.listFiles()?.any { it.isDirectory } == true

        if (iisuPackageExists) {
            Log.d(TAG, "Showing 'no ROMs configured' state (iiSU package found but empty)")
            binding.textNotInstalledTitle.text = "No ROMs Found"
            if (hasEsdeRoms) {
                binding.textNotInstalledDesc.text = "iiSU is installed but no ROMs are configured.\n\nES-DE ROMs folder detected - you can use this app\nto generate icons and covers for your games."
            } else {
                binding.textNotInstalledDesc.text = "iiSU is installed but no ROMs are configured.\n\nAdd ROMs to your iiSU library to browse them here,\nor use the generator tabs to create artwork."
            }
        } else {
            Log.d(TAG, "Showing 'not installed' state (no iiSU package found)")
            binding.textNotInstalledTitle.text = getString(R.string.iisu_not_installed)
            binding.textNotInstalledDesc.text = getString(R.string.iisu_not_installed_desc)
        }
    }

    private fun showIisuBrowser() {
        Log.d(TAG, "Showing iiSU browser")
        binding.layoutNotInstalled.visibility = View.GONE
        binding.layoutBrowser.visibility = View.VISIBLE

        setupPlatformGrid()
        loadPlatforms()
    }

    private fun setupPlatformGrid() {
        platformAdapter = PlatformAdapter { platform ->
            onPlatformSelected(platform)
        }

        binding.recyclerViewPlatforms.apply {
            // Use 5 columns for landscape tablet-style layout
            layoutManager = GridLayoutManager(context, 5)
            adapter = platformAdapter
        }

        // Refresh button
        binding.btnRefresh.setOnClickListener {
            refreshPlatforms()
        }
    }

    private fun loadPlatforms(forceRefresh: Boolean = false) {
        binding.progressBar.visibility = View.VISIBLE
        Log.d(TAG, "Loading platforms (forceRefresh: $forceRefresh)...")

        lifecycleScope.launch {
            val startTime = System.currentTimeMillis()

            // Use cached platform info for fast loading
            val cachedPlatforms = GameCache.getCachedPlatformInfoList(requireContext(), forceRefresh)

            val platforms = cachedPlatforms.map { cached ->
                PlatformInfo(
                    name = cached.name,
                    displayName = cached.displayName,
                    icon = GameCache.getPlatformIconBitmap(cached.iconPath),
                    gameCount = cached.gameCount,
                    missingIcons = cached.missingIcons,
                    missingHeroes = cached.missingHeroes,
                    missingLogos = cached.missingLogos
                )
            }

            val loadTime = System.currentTimeMillis() - startTime
            Log.d(TAG, "Loaded ${platforms.size} platforms in ${loadTime}ms")

            platformAdapter.submitList(platforms)
            binding.progressBar.visibility = View.GONE

            if (platforms.isEmpty()) {
                binding.textEmptyState.visibility = View.VISIBLE
                binding.textEmptyState.text = "No platforms found in iiSU directory.\nAdd games to your iiSU library first."
                Log.d(TAG, "No platforms found - showing empty state")
            } else {
                binding.textEmptyState.visibility = View.GONE
            }
        }
    }

    /**
     * Force refresh platforms from filesystem (clears cache).
     */
    private fun refreshPlatforms() {
        lifecycleScope.launch {
            GameCache.clearCache(requireContext())
            loadPlatforms(forceRefresh = true)
            Toast.makeText(context, "Refreshed platform list", Toast.LENGTH_SHORT).show()
        }
    }

    private fun formatPlatformName(name: String): String {
        return when (name.lowercase()) {
            "nes" -> "NES"
            "snes", "sfc" -> "SNES"
            "n64" -> "N64"
            "gc" -> "GameCube"
            "wii" -> "Wii"
            "wiiu" -> "Wii U"
            "switch" -> "Switch"
            "gb" -> "Game Boy"
            "gbc" -> "Game Boy Color"
            "gba" -> "GBA"
            "nds" -> "Nintendo DS"
            "n3ds" -> "3DS"
            "psx" -> "PlayStation"
            "ps2" -> "PS2"
            "psp" -> "PSP"
            "psvita" -> "PS Vita"
            "megadrive", "genesis" -> "Genesis"
            "saturn" -> "Saturn"
            "dreamcast" -> "Dreamcast"
            "gamegear" -> "Game Gear"
            else -> name.replaceFirstChar { it.uppercase() }
        }
    }

    private fun onPlatformSelected(platform: PlatformInfo) {
        // Navigate to game list fragment
        val gameListFragment = GameListFragment.newInstance(
            platformName = platform.name,
            platformDisplayName = platform.displayName
        )

        parentFragmentManager.beginTransaction()
            .setCustomAnimations(
                android.R.anim.slide_in_left,
                android.R.anim.slide_out_right,
                android.R.anim.slide_in_left,
                android.R.anim.slide_out_right
            )
            .replace(R.id.fragment_container, gameListFragment)
            .addToBackStack("game_list")
            .commit()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

data class PlatformInfo(
    val name: String,
    val displayName: String,
    val icon: android.graphics.Bitmap?,
    val gameCount: Int,
    val missingIcons: Int,
    val missingHeroes: Int,
    val missingLogos: Int
)
