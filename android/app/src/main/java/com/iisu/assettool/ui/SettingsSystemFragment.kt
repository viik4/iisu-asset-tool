package com.iisu.assettool.ui

import android.app.Dialog
import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import coil.load
import com.google.android.material.button.MaterialButton
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.iisu.assettool.R
import com.iisu.assettool.databinding.DialogEditPlatformBinding
import com.iisu.assettool.databinding.FragmentSettingsSystemBinding
import com.iisu.assettool.util.IisuDirectoryManager
import com.iisu.assettool.util.PlatformConfig
import com.iisu.assettool.util.PlatformConfigAdapter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

/**
 * System Options settings tab.
 * Contains: Replace Launcher Assets, Android Apps Path, Platform Configuration, Platform Images
 */
class SettingsSystemFragment : Fragment() {

    private var _binding: FragmentSettingsSystemBinding? = null
    private val binding get() = _binding!!

    private var replaceCovers = true
    private var replaceBorders = true

    private lateinit var platformConfigAdapter: PlatformConfigAdapter

    // Platform images
    private lateinit var platformImageAdapter: PlatformImageAdapter
    private var platformImageSets: List<IisuDirectoryManager.PlatformImageSet> = emptyList()

    // Image picker state — tracks which image slot we're replacing
    private var pendingReplaceTarget: File? = null
    private var pendingReplacePlatformId: String? = null
    private var pendingReplaceDialog: Dialog? = null
    private lateinit var imagePickerLauncher: ActivityResultLauncher<String>

    companion object {
        private const val PREFS_NAME = "iisu_asset_tool_prefs"
        private const val PREF_PLATFORM_CONFIGS = "platform_configs"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Register image picker before fragment view is created
        imagePickerLauncher = registerForActivityResult(
            ActivityResultContracts.GetContent()
        ) { uri: Uri? ->
            if (uri != null) {
                handleImagePicked(uri)
            }
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsSystemBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupReplaceLauncherAssets()
        setupAndroidAppsPath()
        setupRomSourcePath()
        setupHiddenTitles()
        setupPlatformConfiguration()
        setupPlatformImages()
    }

    override fun onResume() {
        super.onResume()
        // Refresh hidden titles in case user hid titles from the game list
        if (hiddenTitleAdapter != null) {
            loadHiddenTitles()
        }
    }

    // ==================== Replace Launcher Assets ====================

    private fun setupReplaceLauncherAssets() {
        binding.switchReplaceCovers.isChecked = replaceCovers
        binding.switchReplaceBorders.isChecked = replaceBorders

        binding.rowReplaceCovers.setOnClickListener {
            binding.switchReplaceCovers.toggle()
            replaceCovers = binding.switchReplaceCovers.isChecked
        }

        binding.rowReplaceBorders.setOnClickListener {
            binding.switchReplaceBorders.toggle()
            replaceBorders = binding.switchReplaceBorders.isChecked
        }

        binding.btnReplaceAllAssets.setOnClickListener {
            if (!replaceCovers && !replaceBorders) {
                Toast.makeText(
                    requireContext(),
                    R.string.settings_select_type,
                    Toast.LENGTH_SHORT
                ).show()
                return@setOnClickListener
            }
            replaceAllAssets()
        }
    }

    private fun replaceAllAssets() {
        viewLifecycleOwner.lifecycleScope.launch {
            binding.btnReplaceAllAssets.isEnabled = false
            binding.btnReplaceAllAssets.text = getString(R.string.settings_replacing)

            try {
                val result = withContext(Dispatchers.IO) {
                    performAssetReplacement()
                }

                if (result.success) {
                    Toast.makeText(
                        requireContext(),
                        getString(R.string.settings_replaced_count, result.coversReplaced, result.bordersReplaced),
                        Toast.LENGTH_LONG
                    ).show()
                } else {
                    Toast.makeText(
                        requireContext(),
                        result.errorMessage ?: getString(R.string.settings_replace_error),
                        Toast.LENGTH_LONG
                    ).show()
                }
            } catch (e: Exception) {
                Toast.makeText(
                    requireContext(),
                    getString(R.string.settings_replace_error),
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                binding.btnReplaceAllAssets.isEnabled = true
                binding.btnReplaceAllAssets.text = getString(R.string.settings_replace_all)
            }
        }
    }

    private data class ReplacementResult(
        val success: Boolean,
        val coversReplaced: Int = 0,
        val bordersReplaced: Int = 0,
        val errorMessage: String? = null
    )

    private fun performAssetReplacement(): ReplacementResult {
        val iisuRoot = IisuDirectoryManager.getIisuRoot()
        if (!iisuRoot.exists()) {
            return ReplacementResult(false, errorMessage = getString(R.string.settings_iisu_not_found))
        }

        var coversReplaced = 0
        var bordersReplaced = 0

        val platforms = IisuDirectoryManager.getPlatformsWithRoms()

        for (platform in platforms) {
            @Suppress("UNUSED_VARIABLE")
            val platformDir = IisuDirectoryManager.getPlatformDir(platform)
            val games = IisuDirectoryManager.getGamesForPlatform(platform)

            if (replaceCovers) {
                for (game in games) {
                    if (game.hasIcon && game.iconFile != null) {
                        coversReplaced++
                    }
                }
            }

            if (replaceBorders) {
                val platformsDir = IisuDirectoryManager.getPlatformsDir()
                val borderFile = File(platformsDir, "${platform}_border.png")
                if (borderFile.exists()) {
                    bordersReplaced++
                }
            }
        }

        return ReplacementResult(
            success = true,
            coversReplaced = coversReplaced,
            bordersReplaced = bordersReplaced
        )
    }

    private fun copyFile(source: File, dest: File) {
        FileInputStream(source).use { input ->
            FileOutputStream(dest).use { output ->
                input.copyTo(output)
            }
        }
    }

    // ==================== Android Apps Path ====================

    private fun setupAndroidAppsPath() {
        val currentPath = SettingsFragment.getAndroidAppsPath(requireContext())
        binding.editAndroidAppsPath.setText(currentPath)

        binding.btnSaveAndroidAppsPath.setOnClickListener {
            val newPath = binding.editAndroidAppsPath.text.toString().trim()
            if (newPath.isNotEmpty()) {
                SettingsFragment.setAndroidAppsPath(requireContext(), newPath)
                Toast.makeText(
                    requireContext(),
                    R.string.settings_android_apps_path_set,
                    Toast.LENGTH_SHORT
                ).show()
            }
        }

        binding.btnResetAndroidAppsPath.setOnClickListener {
            val defaultPath = SettingsFragment.DEFAULT_ANDROID_APPS_PATH
            binding.editAndroidAppsPath.setText(defaultPath)
            SettingsFragment.setAndroidAppsPath(requireContext(), defaultPath)
            Toast.makeText(
                requireContext(),
                R.string.settings_android_apps_path_reset,
                Toast.LENGTH_SHORT
            ).show()
        }
    }

    // ==================== ROM Source Path ====================

    private fun setupRomSourcePath() {
        // Load saved path
        val currentPath = SettingsFragment.getRomSourcePath(requireContext())
        if (currentPath != null) {
            binding.editRomSourcePath.setText(currentPath)
            // Also set it on IisuDirectoryManager
            IisuDirectoryManager.setRomSourcePath(File(currentPath))
        }

        binding.btnSaveRomSourcePath.setOnClickListener {
            val newPath = binding.editRomSourcePath.text.toString().trim()
            if (newPath.isNotEmpty()) {
                SettingsFragment.setRomSourcePath(requireContext(), newPath)
                IisuDirectoryManager.setRomSourcePath(File(newPath))
                Toast.makeText(
                    requireContext(),
                    R.string.settings_rom_source_saved,
                    Toast.LENGTH_SHORT
                ).show()
            }
        }

        binding.btnResetRomSourcePath.setOnClickListener {
            binding.editRomSourcePath.setText("")
            SettingsFragment.setRomSourcePath(requireContext(), null)
            IisuDirectoryManager.setRomSourcePath(null)
            binding.textRomSyncStatus.visibility = View.GONE
            Toast.makeText(
                requireContext(),
                R.string.settings_rom_source_cleared,
                Toast.LENGTH_SHORT
            ).show()
        }

        binding.btnSyncRomFolders.setOnClickListener {
            syncRomFolders()
        }
    }

    private fun syncRomFolders() {
        val romPath = binding.editRomSourcePath.text.toString().trim()
        if (romPath.isEmpty()) {
            Toast.makeText(
                requireContext(),
                R.string.settings_rom_sync_no_path,
                Toast.LENGTH_SHORT
            ).show()
            return
        }

        val romDir = File(romPath)
        if (!romDir.exists() || !romDir.isDirectory) {
            Toast.makeText(
                requireContext(),
                getString(R.string.settings_rom_sync_not_found, romPath),
                Toast.LENGTH_LONG
            ).show()
            return
        }

        // Save the path first
        SettingsFragment.setRomSourcePath(requireContext(), romPath)
        IisuDirectoryManager.setRomSourcePath(romDir)

        // Update UI
        binding.btnSyncRomFolders.isEnabled = false
        binding.btnSyncRomFolders.text = getString(R.string.settings_rom_sync_running)
        binding.textRomSyncStatus.visibility = View.VISIBLE
        binding.textRomSyncStatus.text = getString(R.string.settings_rom_sync_running)

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    IisuDirectoryManager.syncGameFoldersFromRomSource()
                }

                if (_binding == null) return@launch

                val created = result.first
                val existed = result.second

                binding.textRomSyncStatus.text = getString(
                    R.string.settings_rom_sync_done, created, existed
                )
                binding.textRomSyncStatus.visibility = View.VISIBLE

                Toast.makeText(
                    requireContext(),
                    getString(R.string.settings_rom_sync_done, created, existed),
                    Toast.LENGTH_LONG
                ).show()
            } catch (e: Exception) {
                if (_binding == null) return@launch

                binding.textRomSyncStatus.text = "Error: ${e.message}"
                binding.textRomSyncStatus.visibility = View.VISIBLE

                Toast.makeText(
                    requireContext(),
                    "Sync error: ${e.message}",
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                if (_binding != null) {
                    binding.btnSyncRomFolders.isEnabled = true
                    binding.btnSyncRomFolders.text = getString(R.string.settings_rom_sync_now)
                }
            }
        }
    }

    // ==================== Hidden Titles ====================

    /**
     * Data class for a hidden title entry displayed in the list
     */
    private data class HiddenTitleEntry(
        val platform: String,
        val title: String,
        var isSelected: Boolean = false
    )

    private var hiddenTitleEntries = mutableListOf<HiddenTitleEntry>()
    private var hiddenTitleAdapter: HiddenTitleAdapter? = null

    private fun setupHiddenTitles() {
        hiddenTitleAdapter = HiddenTitleAdapter(hiddenTitleEntries) {
            updateHiddenTitleButtonState()
        }

        binding.recyclerHiddenTitles.apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = hiddenTitleAdapter
        }

        binding.btnUnhideSelected.setOnClickListener {
            unhideSelected()
        }

        binding.btnClearAllHidden.setOnClickListener {
            confirmClearAllHidden()
        }

        loadHiddenTitles()
    }

    private fun loadHiddenTitles() {
        val allHidden = SettingsFragment.getHiddenTitles(requireContext())
        hiddenTitleEntries.clear()

        for ((platform, titles) in allHidden) {
            for (title in titles.sorted()) {
                hiddenTitleEntries.add(HiddenTitleEntry(platform, title))
            }
        }

        // Sort by platform then title
        hiddenTitleEntries.sortWith(compareBy({ it.platform.lowercase() }, { it.title.lowercase() }))

        hiddenTitleAdapter?.notifyDataSetChanged()
        updateHiddenTitlesVisibility()
    }

    private fun updateHiddenTitlesVisibility() {
        val hasHidden = hiddenTitleEntries.isNotEmpty()

        if (hasHidden) {
            binding.recyclerHiddenTitles.visibility = View.VISIBLE
            binding.textNoHiddenTitles.visibility = View.GONE
            binding.layoutHiddenTitleButtons.visibility = View.VISIBLE

            val count = hiddenTitleEntries.size
            binding.textHiddenCount.text = "$count hidden title${if (count != 1) "s" else ""}"
        } else {
            binding.recyclerHiddenTitles.visibility = View.GONE
            binding.textNoHiddenTitles.visibility = View.VISIBLE
            binding.layoutHiddenTitleButtons.visibility = View.GONE
            binding.textHiddenCount.text = "No hidden titles"
        }

        updateHiddenTitleButtonState()
    }

    private fun updateHiddenTitleButtonState() {
        val selectedCount = hiddenTitleEntries.count { it.isSelected }
        binding.btnUnhideSelected.isEnabled = selectedCount > 0
        binding.btnUnhideSelected.text = if (selectedCount > 0) {
            "Unhide Selected ($selectedCount)"
        } else {
            "Unhide Selected"
        }
    }

    private fun unhideSelected() {
        val selected = hiddenTitleEntries.filter { it.isSelected }
        if (selected.isEmpty()) return

        for (entry in selected) {
            SettingsFragment.unhideTitle(requireContext(), entry.platform, entry.title)
        }

        Toast.makeText(
            requireContext(),
            "${selected.size} title${if (selected.size != 1) "s" else ""} unhidden",
            Toast.LENGTH_SHORT
        ).show()

        loadHiddenTitles()
    }

    private fun confirmClearAllHidden() {
        if (hiddenTitleEntries.isEmpty()) return

        MaterialAlertDialogBuilder(requireContext())
            .setTitle("Clear All Hidden Titles?")
            .setMessage("This will unhide all ${hiddenTitleEntries.size} hidden titles across all platforms. This action cannot be undone.")
            .setPositiveButton("Clear All") { _, _ ->
                SettingsFragment.clearHiddenTitles(requireContext())
                Toast.makeText(requireContext(), "All hidden titles cleared", Toast.LENGTH_SHORT).show()
                loadHiddenTitles()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /**
     * Adapter for the hidden titles RecyclerView
     */
    private inner class HiddenTitleAdapter(
        private val items: MutableList<HiddenTitleEntry>,
        private val onSelectionChanged: () -> Unit
    ) : RecyclerView.Adapter<HiddenTitleAdapter.ViewHolder>() {

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val checkbox: android.widget.CheckBox = view.findViewById(R.id.checkboxHiddenTitle)
            val platformText: TextView = view.findViewById(R.id.textHiddenPlatform)
            val titleText: TextView = view.findViewById(R.id.textHiddenTitle)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_hidden_title, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            val entry = items[position]

            holder.platformText.text = entry.platform.uppercase()
            holder.titleText.text = entry.title

            // Prevent checkbox listener from firing during bind
            holder.checkbox.setOnCheckedChangeListener(null)
            holder.checkbox.isChecked = entry.isSelected

            holder.checkbox.setOnCheckedChangeListener { _, isChecked ->
                entry.isSelected = isChecked
                onSelectionChanged()
            }

            // Clicking the row toggles the checkbox
            holder.itemView.setOnClickListener {
                holder.checkbox.isChecked = !holder.checkbox.isChecked
            }
        }

        override fun getItemCount() = items.size
    }

    // ==================== Platform Configuration ====================

    private fun setupPlatformConfiguration() {
        platformConfigAdapter = PlatformConfigAdapter(
            onEditClick = { platform -> showEditPlatformDialog(platform) },
            onDeleteClick = { platform -> confirmDeletePlatform(platform) }
        )

        binding.recyclerPlatforms.apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = platformConfigAdapter
        }

        loadPlatformConfigs()

        binding.btnAddPlatform.setOnClickListener {
            showEditPlatformDialog(null)
        }
    }

    private fun loadPlatformConfigs() {
        lifecycleScope.launch {
            val platforms = withContext(Dispatchers.IO) {
                val detectedPlatforms = IisuDirectoryManager.getPlatformsWithRoms()
                val savedConfigs = getSavedPlatformConfigs()

                val allConfigs = mutableListOf<PlatformConfig>()

                for (platformId in detectedPlatforms) {
                    val savedConfig = savedConfigs.find { it.id == platformId }
                    if (savedConfig != null) {
                        allConfigs.add(savedConfig)
                    } else {
                        allConfigs.add(
                            PlatformConfig(
                                id = platformId,
                                displayName = formatPlatformName(platformId),
                                path = IisuDirectoryManager.getPlatformDir(platformId).absolutePath,
                                isCustom = false
                            )
                        )
                    }
                }

                for (config in savedConfigs) {
                    if (config.isCustom && allConfigs.none { it.id == config.id }) {
                        allConfigs.add(config)
                    }
                }

                allConfigs.sortedBy { it.displayName.lowercase() }
            }

            platformConfigAdapter.submitList(platforms)
        }
    }

    private fun getSavedPlatformConfigs(): List<PlatformConfig> {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val json = prefs.getString(PREF_PLATFORM_CONFIGS, null) ?: return emptyList()

        return try {
            val array = JSONArray(json)
            val configs = mutableListOf<PlatformConfig>()
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                configs.add(
                    PlatformConfig(
                        id = obj.getString("id"),
                        displayName = obj.getString("displayName"),
                        path = obj.getString("path"),
                        isCustom = obj.optBoolean("isCustom", false)
                    )
                )
            }
            configs
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun savePlatformConfig(config: PlatformConfig) {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val existingConfigs = getSavedPlatformConfigs().toMutableList()

        val existingIndex = existingConfigs.indexOfFirst { it.id == config.id }
        if (existingIndex >= 0) {
            existingConfigs[existingIndex] = config
        } else {
            existingConfigs.add(config)
        }

        val array = JSONArray()
        for (cfg in existingConfigs) {
            val obj = JSONObject().apply {
                put("id", cfg.id)
                put("displayName", cfg.displayName)
                put("path", cfg.path)
                put("isCustom", cfg.isCustom)
            }
            array.put(obj)
        }

        prefs.edit().putString(PREF_PLATFORM_CONFIGS, array.toString()).apply()
    }

    private fun deletePlatformConfig(config: PlatformConfig) {
        val prefs = requireContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val existingConfigs = getSavedPlatformConfigs().toMutableList()

        existingConfigs.removeAll { it.id == config.id }

        val array = JSONArray()
        for (cfg in existingConfigs) {
            val obj = JSONObject().apply {
                put("id", cfg.id)
                put("displayName", cfg.displayName)
                put("path", cfg.path)
                put("isCustom", cfg.isCustom)
            }
            array.put(obj)
        }

        prefs.edit().putString(PREF_PLATFORM_CONFIGS, array.toString()).apply()
    }

    private fun showEditPlatformDialog(platform: PlatformConfig?) {
        val dialogBinding = DialogEditPlatformBinding.inflate(layoutInflater)
        val isNew = platform == null

        if (platform != null) {
            dialogBinding.editPlatformId.setText(platform.id)
            dialogBinding.editDisplayName.setText(platform.displayName)
            dialogBinding.editCustomPath.setText(platform.path)
            dialogBinding.editPlatformId.isEnabled = platform.isCustom
        }

        MaterialAlertDialogBuilder(requireContext())
            .setTitle(if (isNew) "Add Platform" else "Edit Platform")
            .setView(dialogBinding.root)
            .setPositiveButton("Save") { _, _ ->
                val id = dialogBinding.editPlatformId.text.toString().trim().lowercase()
                val displayName = dialogBinding.editDisplayName.text.toString().trim()
                val customPath = dialogBinding.editCustomPath.text.toString().trim()

                if (id.isBlank()) {
                    Toast.makeText(context, "Platform ID is required", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                if (displayName.isBlank()) {
                    Toast.makeText(context, "Display name is required", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                val newConfig = PlatformConfig(
                    id = id,
                    displayName = displayName,
                    path = customPath.ifBlank {
                        IisuDirectoryManager.getPlatformDir(id).absolutePath
                    },
                    isCustom = isNew || platform?.isCustom == true
                )

                savePlatformConfig(newConfig)
                loadPlatformConfigs()
                Toast.makeText(context, "Platform saved", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun confirmDeletePlatform(platform: PlatformConfig) {
        MaterialAlertDialogBuilder(requireContext())
            .setTitle("Delete Platform?")
            .setMessage("Remove \"${platform.displayName}\" from the list?\n\nThis will only remove the configuration, not delete any files.")
            .setPositiveButton("Delete") { _, _ ->
                deletePlatformConfig(platform)
                loadPlatformConfigs()
                Toast.makeText(context, "Platform removed", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun formatPlatformName(name: String): String {
        return when (name.lowercase()) {
            "nes" -> "NES"
            "snes", "sfc" -> "SNES"
            "n64" -> "N64"
            "gc", "gamecube" -> "GameCube"
            "wii" -> "Wii"
            "wiiu" -> "Wii U"
            "switch" -> "Switch"
            "gb" -> "Game Boy"
            "gbc" -> "Game Boy Color"
            "gba" -> "GBA"
            "nds" -> "Nintendo DS"
            "n3ds", "3ds" -> "3DS"
            "psx", "ps1" -> "PlayStation"
            "ps2" -> "PS2"
            "ps3" -> "PS3"
            "psp" -> "PSP"
            "psvita", "vita" -> "PS Vita"
            "megadrive", "genesis" -> "Genesis"
            "saturn" -> "Saturn"
            "dreamcast" -> "Dreamcast"
            "gamegear", "gg" -> "Game Gear"
            "xbox" -> "Xbox"
            "xbox360" -> "Xbox 360"
            "android" -> "Android"
            else -> name.replaceFirstChar { it.uppercase() }
        }
    }

    // ==================== Platform Images ====================

    private fun setupPlatformImages() {
        platformImageAdapter = PlatformImageAdapter { imageSet ->
            showPlatformImageDialog(imageSet)
        }

        binding.recyclerPlatformImages.apply {
            layoutManager = GridLayoutManager(requireContext(), 4)
            adapter = platformImageAdapter
        }

        binding.btnRefreshPlatformImages.setOnClickListener {
            loadPlatformImages()
        }

        loadPlatformImages()
    }

    private fun loadPlatformImages() {
        binding.textPlatformImagesStatus.text = "Loading..."

        viewLifecycleOwner.lifecycleScope.launch {
            val imageSets = withContext(Dispatchers.IO) {
                IisuDirectoryManager.getLauncherPlatformImages()
            }

            if (_binding == null) return@launch

            platformImageSets = imageSets
            platformImageAdapter.submitList(imageSets)

            val dir = IisuDirectoryManager.getLauncherPlatformImagesDir()
            if (!dir.exists()) {
                binding.textPlatformImagesStatus.text = "Directory not found: ${dir.absolutePath}"
            } else if (imageSets.isEmpty()) {
                binding.textPlatformImagesStatus.text = "No platform images found in ${dir.absolutePath}"
            } else {
                binding.textPlatformImagesStatus.text = "${imageSets.size} platforms • ${dir.absolutePath}"
            }
        }
    }

    private fun showPlatformImageDialog(imageSet: IisuDirectoryManager.PlatformImageSet) {
        val ctx = requireContext()
        val dialog = Dialog(ctx, R.style.Theme_IisuAssetTool_Dialog)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.setContentView(R.layout.dialog_platform_images)

        // Size: 95% width, up to 90% height
        val dm = ctx.resources.displayMetrics
        val maxHeight = (dm.heightPixels * 0.90).toInt()
        dialog.window?.setLayout(
            (dm.widthPixels * 0.95).toInt(),
            ViewGroup.LayoutParams.WRAP_CONTENT
        )
        dialog.window?.decorView?.post {
            val h = dialog.window?.decorView?.height ?: 0
            if (h > maxHeight) {
                dialog.window?.setLayout((dm.widthPixels * 0.95).toInt(), maxHeight)
            }
        }

        // Store reference for image picker callback
        pendingReplaceDialog = dialog

        val platformDir = IisuDirectoryManager.getLauncherPlatformImagesDir()

        // Header
        dialog.findViewById<TextView>(R.id.textPlatformTitle).text = imageSet.displayName
        dialog.findViewById<TextView>(R.id.textPlatformPath).text = platformDir.absolutePath
        dialog.findViewById<MaterialButton>(R.id.btnClose).setOnClickListener { dialog.dismiss() }

        // Icon section
        setupImageSlot(
            dialog = dialog,
            imageView = dialog.findViewById(R.id.imageIcon),
            noImageView = dialog.findViewById(R.id.textNoIcon),
            filenameView = dialog.findViewById(R.id.textIconFilename),
            replaceBtn = dialog.findViewById(R.id.btnReplaceIcon),
            file = imageSet.icon,
            targetFilename = "${imageSet.platformId}.png",
            platformDir = platformDir,
            platformId = imageSet.platformId
        )

        // List icon section
        setupImageSlot(
            dialog = dialog,
            imageView = dialog.findViewById(R.id.imageList),
            noImageView = dialog.findViewById(R.id.textNoList),
            filenameView = dialog.findViewById(R.id.textListFilename),
            replaceBtn = dialog.findViewById(R.id.btnReplaceList),
            file = imageSet.listIcon,
            targetFilename = "${imageSet.platformId}_list.png",
            platformDir = platformDir,
            platformId = imageSet.platformId
        )

        // List selected section
        setupImageSlot(
            dialog = dialog,
            imageView = dialog.findViewById(R.id.imageListSelected),
            noImageView = dialog.findViewById(R.id.textNoListSelected),
            filenameView = dialog.findViewById(R.id.textListSelectedFilename),
            replaceBtn = dialog.findViewById(R.id.btnReplaceListSelected),
            file = imageSet.listSelected,
            targetFilename = "${imageSet.platformId}_list_selected.png",
            platformDir = platformDir,
            platformId = imageSet.platformId
        )

        // Title section
        setupImageSlot(
            dialog = dialog,
            imageView = dialog.findViewById(R.id.imageTitleImg),
            noImageView = dialog.findViewById(R.id.textNoTitle),
            filenameView = dialog.findViewById(R.id.textTitleFilename),
            replaceBtn = dialog.findViewById(R.id.btnReplaceTitle),
            file = imageSet.title,
            targetFilename = "${imageSet.platformId}_title.png",
            platformDir = platformDir,
            platformId = imageSet.platformId
        )

        dialog.show()
    }

    @Suppress("UNUSED_PARAMETER")
    private fun setupImageSlot(
        dialog: Dialog,
        imageView: ImageView,
        noImageView: TextView,
        filenameView: TextView,
        replaceBtn: MaterialButton,
        file: File?,
        targetFilename: String,
        platformDir: File,
        platformId: String
    ) {
        if (file != null && file.exists()) {
            imageView.load(file) {
                crossfade(true)
                error(R.drawable.ic_image_placeholder)
            }
            noImageView.visibility = View.GONE
            filenameView.text = "${file.name} • ${formatFileSize(file.length())}"
        } else {
            imageView.setImageResource(R.drawable.ic_image_placeholder)
            noImageView.visibility = View.VISIBLE
            filenameView.text = targetFilename
        }

        replaceBtn.setOnClickListener {
            // Store the target file path for when the picker returns
            pendingReplaceTarget = File(platformDir, targetFilename)
            pendingReplacePlatformId = platformId
            imagePickerLauncher.launch("image/*")
        }
    }

    private fun handleImagePicked(uri: Uri) {
        val targetFile = pendingReplaceTarget ?: return
        val platformId = pendingReplacePlatformId ?: return

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val success = withContext(Dispatchers.IO) {
                    copyUriToFile(uri, targetFile)
                }

                if (success) {
                    Toast.makeText(context, "Replaced ${targetFile.name}", Toast.LENGTH_SHORT).show()

                    // Refresh the dialog if still open
                    pendingReplaceDialog?.let { dialog ->
                        if (dialog.isShowing) {
                            dialog.dismiss()
                            // Re-scan and re-open dialog for this platform
                            val refreshedSets = withContext(Dispatchers.IO) {
                                IisuDirectoryManager.getLauncherPlatformImages()
                            }
                            platformImageSets = refreshedSets
                            platformImageAdapter.submitList(refreshedSets)

                            val updatedSet = refreshedSets.find { it.platformId == platformId }
                            if (updatedSet != null) {
                                showPlatformImageDialog(updatedSet)
                            }
                        }
                    }

                    // Refresh the grid
                    loadPlatformImages()
                } else {
                    Toast.makeText(context, "Failed to replace image", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                android.util.Log.e("SettingsSystem", "Error replacing image: ${e.message}", e)
                Toast.makeText(context, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun copyUriToFile(uri: Uri, targetFile: File): Boolean {
        return try {
            // Ensure parent directory exists
            targetFile.parentFile?.mkdirs()

            requireContext().contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(targetFile).use { output ->
                    input.copyTo(output)
                }
            }
            targetFile.exists() && targetFile.length() > 0
        } catch (e: Exception) {
            android.util.Log.e("SettingsSystem", "Error copying URI to file: ${e.message}", e)
            false
        }
    }

    private fun formatFileSize(bytes: Long): String {
        return when {
            bytes < 1024 -> "${bytes} B"
            bytes < 1024 * 1024 -> "${bytes / 1024} KB"
            else -> String.format("%.1f MB", bytes / (1024.0 * 1024.0))
        }
    }

    // ==================== Platform Image Grid Adapter ====================

    inner class PlatformImageAdapter(
        private val onPlatformClick: (IisuDirectoryManager.PlatformImageSet) -> Unit
    ) : RecyclerView.Adapter<PlatformImageAdapter.ViewHolder>() {

        private var items: List<IisuDirectoryManager.PlatformImageSet> = emptyList()

        fun submitList(newItems: List<IisuDirectoryManager.PlatformImageSet>) {
            items = newItems
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_platform_image, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            holder.bind(items[position])
        }

        override fun getItemCount() = items.size

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            private val imagePlatformIcon: ImageView = view.findViewById(R.id.imagePlatformIcon)
            private val textPlatformName: TextView = view.findViewById(R.id.textPlatformName)
            private val textImageCount: TextView = view.findViewById(R.id.textImageCount)
            private val textNoImage: TextView = view.findViewById(R.id.textNoImage)

            fun bind(imageSet: IisuDirectoryManager.PlatformImageSet) {
                textPlatformName.text = imageSet.displayName
                textImageCount.text = "${imageSet.imageCount}/4 images"

                // Show the main icon if available
                if (imageSet.icon != null && imageSet.icon.exists()) {
                    imagePlatformIcon.load(imageSet.icon) {
                        crossfade(true)
                        error(R.drawable.ic_image_placeholder)
                    }
                    textNoImage.visibility = View.GONE
                } else {
                    imagePlatformIcon.setImageResource(R.drawable.ic_image_placeholder)
                    textNoImage.visibility = View.VISIBLE
                }

                itemView.setOnClickListener { onPlatformClick(imageSet) }
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        pendingReplaceDialog = null
        _binding = null
    }
}
