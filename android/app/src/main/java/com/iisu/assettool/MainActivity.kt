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
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.iisu.assettool.databinding.ActivityMainBinding
import com.iisu.assettool.ui.DotGridDrawable
import com.iisu.assettool.ui.IconGeneratorFragment
import com.iisu.assettool.ui.CustomImageFragment
import com.iisu.assettool.ui.IisuBrowserFragment
import com.iisu.assettool.ui.SettingsFragment
import com.iisu.assettool.util.IisuDirectoryManager
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

    companion object {
        private const val TAG = "MainActivity"
        private const val STORAGE_PERMISSION_CODE = 100
        private const val MANAGE_STORAGE_CODE = 101
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupNavigation()
        applyDotGridBackground()
        loadSavedCustomAssetDirectory()
        checkStoragePermissions()

        // Load default fragment only if we have permissions
        if (savedInstanceState == null) {
            loadDefaultFragment()
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

        // Start with iiSU Browser if iiSU is installed, otherwise Icon Generator
        if (IisuDirectoryManager.isIisuInstalled()) {
            Log.d(TAG, "iiSU detected - loading browser")
            loadFragment(IisuBrowserFragment())
            binding.navigationRail.selectedItemId = R.id.nav_iisu_browser
        } else {
            Log.d(TAG, "iiSU not detected - loading icon generator")
            loadFragment(IconGeneratorFragment())
            binding.navigationRail.selectedItemId = R.id.nav_icon_generator
        }
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
                    startActivityForResult(intent, MANAGE_STORAGE_CODE)
                } catch (e: Exception) {
                    val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                    startActivityForResult(intent, MANAGE_STORAGE_CODE)
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
            val fragment: Fragment = when (item.itemId) {
                R.id.nav_iisu_browser -> IisuBrowserFragment()
                R.id.nav_icon_generator -> IconGeneratorFragment()
                R.id.nav_custom_image -> CustomImageFragment()
                R.id.nav_settings -> SettingsFragment()
                else -> return@setOnItemSelectedListener false
            }
            loadFragment(fragment)
            true
        }
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
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

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == MANAGE_STORAGE_CODE) {
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
    }

    private fun reloadCurrentFragment() {
        debugIisuPaths()
        // Reload the current fragment to re-check iiSU status
        val currentFragmentId = binding.navigationRail.selectedItemId
        val fragment: Fragment = when (currentFragmentId) {
            R.id.nav_iisu_browser -> IisuBrowserFragment()
            R.id.nav_icon_generator -> IconGeneratorFragment()
            R.id.nav_custom_image -> CustomImageFragment()
            R.id.nav_settings -> SettingsFragment()
            else -> {
                // Default to checking iiSU again
                if (IisuDirectoryManager.isIisuInstalled()) {
                    binding.navigationRail.selectedItemId = R.id.nav_iisu_browser
                    IisuBrowserFragment()
                } else {
                    IconGeneratorFragment()
                }
            }
        }
        loadFragment(fragment)
    }
}
