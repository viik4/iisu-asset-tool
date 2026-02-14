package com.iisu.assettool

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.drawable.LayerDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.iisu.assettool.databinding.ActivityMainBinding
import com.iisu.assettool.ui.DotGridDrawable
import com.iisu.assettool.ui.IconGeneratorFragment
import com.iisu.assettool.ui.IconsFragment
import com.iisu.assettool.ui.CustomImageFragment
import com.iisu.assettool.ui.IisuBrowserFragment
import com.iisu.assettool.ui.SettingsFragment
import com.iisu.assettool.ui.CommunityDbFragment
import com.iisu.assettool.ui.MusicFragment
import com.iisu.assettool.ui.OnboardingActivity
import com.iisu.assettool.data.UpdateChecker
import com.iisu.assettool.util.BackgroundMusicManager
import com.iisu.assettool.util.IisuDirectoryManager
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Main Activity for iiSU Asset Tool Android
 *
 * Landscape-oriented UI with side navigation matching iiSU's design language.
 * Features:
 * - iiSU Browser: Browse and manage iiSU platform assets directly
 * - Icon Generator: Scrape and generate game icons
 * - Custom Image: Process custom images with borders
 * - Settings: App configuration
 *
 * Design language:
 * - Side navigation rail for landscape mode
 * - iiSU-style icons with gradient selected states
 * - Cyan-to-magenta gradient for active items
 * - Dark theme matching iiSU aesthetic
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var hasInitializedFragment = false

    // Flag to prevent navigation listener from firing during initial setup
    private var isSettingUpNavigation = false

    // Modern ActivityResult API for storage permission
    private val manageStorageLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        // Check if permission was granted after returning
        onStoragePermissionResult()
    }

    companion object {
        private const val TAG = "MainActivity"
        private const val STORAGE_PERMISSION_CODE = 100
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupNavigation()
        setupLogoClick()
        applyDotGridBackground()
        loadSavedCustomAssetDirectory()
        loadSavedRomSourcePath()
        checkStoragePermissions()

        // Show onboarding on first launch or major update
        if (savedInstanceState == null && OnboardingActivity.shouldShowOnboarding(this)) {
            startActivity(Intent(this, OnboardingActivity::class.java))
        }

        // Load default fragment only if we have permissions
        if (savedInstanceState == null) {
            loadDefaultFragment()
        }

        // Initialize background music (iiSU OST by Thaddeus Silva)
        BackgroundMusicManager.initialize(this)

        // Auto-check for updates after a short delay
        lifecycleScope.launch {
            delay(5000)
            checkForUpdates(silent = true)
        }
    }

    /**
     * Set up the logo click listener to open Settings.
     */
    private fun setupLogoClick() {
        binding.appLogo.setOnClickListener {
            loadFragment(SettingsFragment())
            // Deselect nav items when settings is opened via logo
            binding.navigationRail.menu.setGroupCheckable(0, true, false)
            for (i in 0 until binding.navigationRail.menu.size()) {
                binding.navigationRail.menu.getItem(i).isChecked = false
            }
            binding.navigationRail.menu.setGroupCheckable(0, true, true)
        }
    }

    /**
     * Load the saved custom asset directory from preferences and set it in IisuDirectoryManager.
     * This ensures the custom directory is used even if the user doesn't visit Settings.
     */
    private fun loadSavedCustomAssetDirectory() {
        val prefs = getSharedPreferences(SettingsFragment.PREFS_NAME, MODE_PRIVATE)
        val savedPath = prefs.getString(SettingsFragment.PREF_CUSTOM_ASSET_DIR, null)
        if (savedPath != null) {
            val file = File(savedPath)
            if (file.exists() && file.isDirectory) {
                IisuDirectoryManager.setCustomRomPath(file)
                Log.d(TAG, "Loaded saved custom asset directory: $savedPath")
            }
        }
    }

    /**
     * Load the saved ROM source directory from preferences and set it in IisuDirectoryManager.
     * This ensures the ROM source is available even if the user doesn't visit Settings.
     */
    private fun loadSavedRomSourcePath() {
        val savedPath = SettingsFragment.getRomSourcePath(this)
        if (savedPath != null) {
            val file = File(savedPath)
            IisuDirectoryManager.setRomSourcePath(file)
            Log.d(TAG, "Loaded saved ROM source path: $savedPath")
        }
    }

    /**
     * Apply the dot grid overlay to the fragment container background.
     * Combines the base page background with a programmatic dot grid pattern.
     */
    private fun applyDotGridBackground() {
        val isDarkMode = when (AppCompatDelegate.getDefaultNightMode()) {
            AppCompatDelegate.MODE_NIGHT_YES -> true
            AppCompatDelegate.MODE_NIGHT_NO -> false
            else -> {
                // Follow system
                val nightModeFlags = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
                nightModeFlags == Configuration.UI_MODE_NIGHT_YES
            }
        }

        // Get the base background drawable
        val baseBackground = if (isDarkMode) {
            ContextCompat.getDrawable(this, R.drawable.bg_page)
        } else {
            ContextCompat.getDrawable(this, R.drawable.bg_page_light)
        }

        // Create the dot grid drawable with appropriate color
        val dotColor = if (isDarkMode) {
            ContextCompat.getColor(this, R.color.dot_grid_dark)
        } else {
            ContextCompat.getColor(this, R.color.dot_grid_light)
        }
        val dotGrid = DotGridDrawable(dotColor = dotColor, dotRadius = 1.5f, spacing = 28f)

        // Combine them in a LayerDrawable
        if (baseBackground != null) {
            val layerDrawable = LayerDrawable(arrayOf(baseBackground, dotGrid))
            binding.fragmentContainer.background = layerDrawable
        }

        // Also update nav rail background
        val navBackground = if (isDarkMode) {
            ContextCompat.getDrawable(this, R.drawable.bg_nav_rail)
        } else {
            ContextCompat.getDrawable(this, R.drawable.bg_nav_rail_light)
        }
        binding.navigationRail.background = navBackground
    }

    override fun onResume() {
        super.onResume()
        // Re-apply background in case theme changed
        applyDotGridBackground()
        // Re-check iiSU detection when returning from permission settings
        if (hasStoragePermission()) {
            debugIisuPaths()
        }
        // Resume background music if enabled
        BackgroundMusicManager.resume(this)
    }

    override fun onPause() {
        super.onPause()
        // Pause background music when app goes to background
        BackgroundMusicManager.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        // Release music resources when activity is destroyed
        BackgroundMusicManager.release()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        // Re-apply background when configuration (including night mode) changes
        applyDotGridBackground()
    }

    private fun hasStoragePermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun loadDefaultFragment() {
        hasInitializedFragment = true
        debugIisuPaths()

        // Prevent the navigation listener from creating a duplicate fragment
        // when we programmatically set selectedItemId
        isSettingUpNavigation = true

        // Start with iiSU Browser if iiSU is installed, otherwise Icons tab
        if (IisuDirectoryManager.isIisuInstalled()) {
            Log.d(TAG, "iiSU detected - loading browser")
            loadFragment(IisuBrowserFragment())
            binding.navigationRail.selectedItemId = R.id.nav_iisu_browser
        } else {
            Log.d(TAG, "iiSU not detected - loading icons tab")
            loadFragment(IconsFragment())
            binding.navigationRail.selectedItemId = R.id.nav_icons
        }

        // Re-enable the navigation listener for user interactions
        isSettingUpNavigation = false
    }

    private fun debugIisuPaths() {
        val root = IisuDirectoryManager.getIisuRoot()
        Log.d(TAG, "iiSU root path: ${root.absolutePath}")
        Log.d(TAG, "iiSU root exists: ${root.exists()}")
        Log.d(TAG, "iiSU root is directory: ${root.isDirectory}")
        Log.d(TAG, "iiSU root can read: ${root.canRead()}")

        if (root.exists() && root.isDirectory) {
            val contents = root.listFiles()
            Log.d(TAG, "iiSU root contents: ${contents?.map { it.name } ?: "null (permission denied?)"}")

            val platforms = IisuDirectoryManager.getPlatformsWithRoms()
            Log.d(TAG, "Platforms with ROMs: $platforms")
        }

        // Also check the external storage root
        val extStorage = Environment.getExternalStorageDirectory()
        Log.d(TAG, "External storage: ${extStorage.absolutePath}")
        Log.d(TAG, "External storage exists: ${extStorage.exists()}")
        Log.d(TAG, "External storage can read: ${extStorage.canRead()}")
    }

    private fun checkStoragePermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            // Android 11+ requires MANAGE_EXTERNAL_STORAGE
            if (!Environment.isExternalStorageManager()) {
                try {
                    val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                    intent.data = Uri.parse("package:$packageName")
                    manageStorageLauncher.launch(intent)
                } catch (e: Exception) {
                    val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                    manageStorageLauncher.launch(intent)
                }
            }
        } else {
            // Android 10 and below
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(
                        Manifest.permission.READ_EXTERNAL_STORAGE,
                        Manifest.permission.WRITE_EXTERNAL_STORAGE
                    ),
                    STORAGE_PERMISSION_CODE
                )
            }
        }
    }

    private fun setupNavigation() {
        binding.navigationRail.setOnItemSelectedListener { item ->
            // Skip if we're setting up navigation programmatically (during initial setup)
            if (isSettingUpNavigation) {
                Log.d(TAG, "Skipping nav listener - initial setup in progress")
                return@setOnItemSelectedListener true
            }

            val fragment: Fragment = when (item.itemId) {
                R.id.nav_iisu_browser -> IisuBrowserFragment()
                R.id.nav_icons -> IconsFragment()
                R.id.nav_community_db -> CommunityDbFragment()
                R.id.nav_music -> MusicFragment()
                else -> return@setOnItemSelectedListener false
            }
            loadFragment(fragment)
            true
        }
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .setCustomAnimations(
                R.anim.fragment_fade_enter,
                R.anim.fragment_fade_exit
            )
            .replace(R.id.fragment_container, fragment)
            .commit()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == STORAGE_PERMISSION_CODE) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                Toast.makeText(this, "Storage permission granted", Toast.LENGTH_SHORT).show()
                // Reload fragment now that we have permission
                reloadCurrentFragment()
            } else {
                Toast.makeText(this, "Storage permission required to access iiSU files", Toast.LENGTH_LONG).show()
            }
        }
    }

    // Storage permission callback is now handled by manageStorageLauncher (ActivityResult API)
    // The old onActivityResult method is no longer needed for storage permissions
    private fun onStoragePermissionResult() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (Environment.isExternalStorageManager()) {
                Toast.makeText(this, "Storage access granted", Toast.LENGTH_SHORT).show()
                Log.d(TAG, "MANAGE_EXTERNAL_STORAGE granted, reloading fragment")
                // Reload fragment now that we have permission
                reloadCurrentFragment()
            } else {
                Toast.makeText(this, "Storage access required to manage iiSU files", Toast.LENGTH_LONG).show()
            }
        }
    }

    // ==================== In-App Updater ====================

    private val updateChecker = UpdateChecker()

    /**
     * Check for updates. If [silent], only shows dialog when an update is found.
     * If not silent (manual check), also shows "up to date" or error messages.
     */
    fun checkForUpdates(silent: Boolean = true) {
        lifecycleScope.launch {
            try {
                if (silent && !updateChecker.shouldCheckForUpdates(this@MainActivity)) {
                    return@launch
                }

                val currentVersion = BuildConfig.VERSION_NAME
                val info = withContext(Dispatchers.IO) {
                    updateChecker.checkForUpdates(currentVersion)
                }
                updateChecker.saveLastCheckTime(this@MainActivity)

                if (info != null && info.isUpdateAvailable) {
                    showUpdateDialog(info)
                } else if (!silent) {
                    if (info != null) {
                        com.google.android.material.dialog.MaterialAlertDialogBuilder(this@MainActivity)
                            .setTitle("Up to Date")
                            .setMessage("iiSU Asset Tool v${BuildConfig.VERSION_NAME} is the latest version.")
                            .setPositiveButton("OK", null)
                            .show()
                    } else {
                        Toast.makeText(
                            this@MainActivity,
                            "Could not check for updates. Check your internet connection.",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Update check failed", e)
                if (!silent) {
                    Toast.makeText(
                        this@MainActivity,
                        "Update check failed: ${e.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }
    }

    private fun showUpdateDialog(info: UpdateChecker.UpdateInfo) {
        val dialogView = layoutInflater.inflate(R.layout.dialog_update_available, null)

        val textNewVersion = dialogView.findViewById<android.widget.TextView>(R.id.textNewVersion)
        val textCurrentVersion = dialogView.findViewById<android.widget.TextView>(R.id.textCurrentVersion)
        val textChangelog = dialogView.findViewById<android.widget.TextView>(R.id.textChangelog)
        val textDownloadSize = dialogView.findViewById<android.widget.TextView>(R.id.textDownloadSize)
        val progressDownload = dialogView.findViewById<com.google.android.material.progressindicator.LinearProgressIndicator>(R.id.progressDownload)
        val textProgressLabel = dialogView.findViewById<android.widget.TextView>(R.id.textProgressLabel)

        textNewVersion.text = "v${info.latestVersion}"
        textCurrentVersion.text = "You have v${info.currentVersion}"

        // Format changelog — convert markdown bullets to plain text
        val changelog = info.changelog
            .replace(Regex("^## (.+)$", RegexOption.MULTILINE), "$1:")
            .replace(Regex("^# (.+)$", RegexOption.MULTILINE), "$1:")
            .replace(Regex("^[*-] ", RegexOption.MULTILINE), "• ")
        textChangelog.text = changelog

        if (info.downloadSize > 0) {
            textDownloadSize.text = "Download size: ${updateChecker.formatSize(info.downloadSize)}"
            textDownloadSize.visibility = View.VISIBLE
        }

        val dialog = com.google.android.material.dialog.MaterialAlertDialogBuilder(this)
            .setView(dialogView)
            .setPositiveButton("Update Now", null)  // null to prevent auto-dismiss
            .setNeutralButton("View on GitHub") { _, _ ->
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(info.releaseUrl))
                startActivity(intent)
            }
            .setNegativeButton("Later", null)
            .create()

        dialog.show()

        // Override positive button to handle download
        dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            if (info.downloadUrl.isNullOrEmpty()) {
                Toast.makeText(this, "No APK available. Opening release page.", Toast.LENGTH_SHORT).show()
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(info.releaseUrl))
                startActivity(intent)
                dialog.dismiss()
                return@setOnClickListener
            }

            // Start download
            it.isEnabled = false
            (it as? android.widget.Button)?.text = "Downloading..."
            dialog.getButton(android.app.AlertDialog.BUTTON_NEGATIVE).isEnabled = false
            progressDownload.visibility = View.VISIBLE
            textProgressLabel.visibility = View.VISIBLE

            lifecycleScope.launch {
                val updatesDir = File(getExternalFilesDir(null), "updates")
                val outputFile = File(updatesDir, "iiSU_Asset_Tool_Android.apk")

                val success = updateChecker.downloadApk(
                    info.downloadUrl,
                    outputFile
                ) { downloaded, total ->
                    runOnUiThread {
                        if (total > 0) {
                            val pct = (downloaded * 100 / total).toInt()
                            progressDownload.progress = pct
                            textProgressLabel.text = "${updateChecker.formatSize(downloaded)} / ${updateChecker.formatSize(total)} ($pct%)"
                        }
                    }
                }

                withContext(Dispatchers.Main) {
                    if (success) {
                        dialog.dismiss()
                        installApk(outputFile)
                    } else {
                        it.isEnabled = true
                        (it as? android.widget.Button)?.text = "Retry"
                        dialog.getButton(android.app.AlertDialog.BUTTON_NEGATIVE).isEnabled = true
                        progressDownload.visibility = View.GONE
                        textProgressLabel.text = "Download failed. Please try again."
                    }
                }
            }
        }
    }

    private fun installApk(apkFile: File) {
        try {
            val uri = FileProvider.getUriForFile(
                this,
                "${BuildConfig.APPLICATION_ID}.fileprovider",
                apkFile
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK
            }
            startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to install APK", e)
            Toast.makeText(this, "Failed to install update: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun reloadCurrentFragment() {
        debugIisuPaths()
        // Reload the current fragment to re-check iiSU status
        val currentFragmentId = binding.navigationRail.selectedItemId
        val fragment: Fragment = when (currentFragmentId) {
            R.id.nav_iisu_browser -> IisuBrowserFragment()
            R.id.nav_icons -> IconsFragment()
            R.id.nav_community_db -> CommunityDbFragment()
            R.id.nav_music -> MusicFragment()
            else -> {
                // Default to checking iiSU again
                // Prevent the navigation listener from creating a duplicate fragment
                isSettingUpNavigation = true
                val defaultFragment = if (IisuDirectoryManager.isIisuInstalled()) {
                    binding.navigationRail.selectedItemId = R.id.nav_iisu_browser
                    IisuBrowserFragment()
                } else {
                    binding.navigationRail.selectedItemId = R.id.nav_icons
                    IconsFragment()
                }
                isSettingUpNavigation = false
                defaultFragment
            }
        }
        loadFragment(fragment)
    }
}
