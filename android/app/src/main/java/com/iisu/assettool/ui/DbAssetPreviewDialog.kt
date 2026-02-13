package com.iisu.assettool.ui

import android.app.Dialog
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.View
import android.view.Window
import android.widget.*
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import coil.load
import com.google.android.material.button.MaterialButton
import com.google.android.material.tabs.TabLayout
import com.iisu.assettool.R
import com.iisu.assettool.data.Platform
import com.iisu.assettool.util.GameCache
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.net.URL

/**
 * Dialog for previewing and applying iiSU asset server assets to library games.
 * Shows a side-by-side comparison of current vs server assets with checkboxes
 * to select which assets to apply.
 */
class DbAssetPreviewDialog(
    context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val dbGameName: String,
    private val dbPlatform: String,
    private val dbAssets: List<DbAsset>,
    private val onApplyComplete: (success: Boolean, message: String) -> Unit
) : Dialog(context, R.style.Theme_IisuAssetTool_Dialog) {

    data class DbAsset(
        val filename: String,
        val fileId: String,
        val downloadUrl: String,
        val type: AssetType
    ) {
        enum class AssetType {
            ICON, HERO, LOGO
        }
    }

    // Views
    private lateinit var textDbGameTitle: TextView
    private lateinit var textTargetGameName: TextView
    private lateinit var btnChangeGame: MaterialButton
    private lateinit var textSelectedGamePath: TextView
    private lateinit var tabLayoutAssets: TabLayout
    private lateinit var imageCurrentAsset: ImageView
    private lateinit var imageDbAsset: ImageView
    private lateinit var textNoCurrentAsset: TextView
    private lateinit var textNoDbAsset: TextView
    private lateinit var textCurrentInfo: TextView
    private lateinit var textDbInfo: TextView
    private lateinit var progressDbAsset: ProgressBar
    private lateinit var checkIcon: CheckBox
    private lateinit var checkHero: CheckBox
    private lateinit var checkLogo: CheckBox
    private lateinit var btnApply: MaterialButton
    private lateinit var btnCancel: MaterialButton
    private lateinit var progressApply: ProgressBar

    // State
    private var libraryGames: List<GameInfo> = emptyList()
    private var selectedGame: GameInfo? = null
    private var currentTab = DbAsset.AssetType.ICON

    // Cached DB asset bitmaps
    private val dbBitmapCache = mutableMapOf<DbAsset.AssetType, Bitmap?>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestWindowFeature(Window.FEATURE_NO_TITLE)
        setContentView(R.layout.dialog_db_asset_preview)

        // Set dialog size — 95% width, up to 85% screen height (scrollable if needed)
        val displayMetrics = context.resources.displayMetrics
        val maxHeight = (displayMetrics.heightPixels * 0.85).toInt()
        window?.setLayout(
            (displayMetrics.widthPixels * 0.95).toInt(),
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        )
        // Constrain max height so the dialog doesn't overflow the screen
        window?.decorView?.post {
            val currentHeight = window?.decorView?.height ?: 0
            if (currentHeight > maxHeight) {
                window?.setLayout(
                    (displayMetrics.widthPixels * 0.95).toInt(),
                    maxHeight
                )
            }
        }

        setupViews()
        loadLibraryGames()
        setupTabs()
    }

    private fun setupViews() {
        textDbGameTitle = findViewById(R.id.textDbGameTitle)
        textTargetGameName = findViewById(R.id.textTargetGameName)
        btnChangeGame = findViewById(R.id.btnChangeGame)
        textSelectedGamePath = findViewById(R.id.textSelectedGamePath)
        tabLayoutAssets = findViewById(R.id.tabLayoutAssets)
        imageCurrentAsset = findViewById(R.id.imageCurrentAsset)
        imageDbAsset = findViewById(R.id.imageDbAsset)
        textNoCurrentAsset = findViewById(R.id.textNoCurrentAsset)
        textNoDbAsset = findViewById(R.id.textNoDbAsset)
        textCurrentInfo = findViewById(R.id.textCurrentInfo)
        textDbInfo = findViewById(R.id.textDbInfo)
        progressDbAsset = findViewById(R.id.progressDbAsset)
        checkIcon = findViewById(R.id.checkIcon)
        checkHero = findViewById(R.id.checkHero)
        checkLogo = findViewById(R.id.checkLogo)
        btnApply = findViewById(R.id.btnApply)
        btnCancel = findViewById(R.id.btnCancel)
        progressApply = findViewById(R.id.progressApply)

        // Set title
        textDbGameTitle.text = dbGameName

        // Setup checkbox visibility based on available assets
        val hasIcon = dbAssets.any { it.type == DbAsset.AssetType.ICON }
        val hasHero = dbAssets.any { it.type == DbAsset.AssetType.HERO }
        val hasLogo = dbAssets.any { it.type == DbAsset.AssetType.LOGO }

        checkIcon.isEnabled = hasIcon
        checkIcon.isChecked = hasIcon
        checkHero.isEnabled = hasHero
        checkHero.isChecked = hasHero
        checkLogo.isEnabled = hasLogo
        checkLogo.isChecked = hasLogo

        // Update checkbox text with availability
        checkIcon.text = if (hasIcon) "Icon" else "Icon (not in DB)"
        checkHero.text = if (hasHero) "Hero" else "Hero (not in DB)"
        checkLogo.text = if (hasLogo) "Logo" else "Logo (not in DB)"

        // Close button
        findViewById<MaterialButton>(R.id.btnClose).setOnClickListener {
            dismiss()
        }

        btnCancel.setOnClickListener {
            dismiss()
        }

        btnApply.setOnClickListener {
            applyAssets()
        }

        // Change game button - shows GameFolderSelectDialog for full library browsing
        btnChangeGame.setOnClickListener {
            showGameSelectionDialog()
        }

        // Initially disable apply until game is selected
        btnApply.isEnabled = false
    }

    private fun showGameSelectionDialog() {
        GameFolderSelectDialog.show(
            context = context,
            suggestedName = dbGameName,
            suggestedPlatform = dbPlatform,
            mode = GameFolderSelectDialog.Mode.ASSETS,
            coroutineScope = lifecycleOwner.lifecycleScope
        ) { selectedGame ->
            // Update selected game
            this.selectedGame = selectedGame
            textTargetGameName.text = selectedGame.displayName
            textTargetGameName.setTextColor(context.getColor(R.color.accent_cyan))
            textSelectedGamePath.text = selectedGame.folder.absolutePath
            textSelectedGamePath.visibility = View.VISIBLE
            btnApply.isEnabled = true
            showAssetComparison(currentTab)
        }
    }

    private fun loadLibraryGames() {
        textTargetGameName.text = "Searching library..."
        textTargetGameName.setTextColor(context.getColor(R.color.theme_text_secondary))

        lifecycleOwner.lifecycleScope.launch {
            try {
                if (!IisuDirectoryManager.isIisuInstalled()) {
                    textTargetGameName.text = "iiSU library not found"
                    btnChangeGame.isEnabled = false
                    return@launch
                }

                // Check if this is an Android apps platform
                val isAndroidPlatform = dbPlatform.lowercase().replace(Regex("[^a-z0-9]"), "").let {
                    it == "android" || it == "androidapps"
                }

                if (isAndroidPlatform) {
                    // Load from Android apps directory
                    libraryGames = withContext(Dispatchers.IO) {
                        IisuDirectoryManager.getAndroidApps().map { app ->
                            GameInfo(
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
                    }.sortedBy { it.name.lowercase() }

                    android.util.Log.d("DbAssetPreviewDialog", "Loaded ${libraryGames.size} Android apps (DB platform: $dbPlatform)")
                } else {
                    // Get all available platform folders in the library
                    val availablePlatforms = withContext(Dispatchers.IO) {
                        IisuDirectoryManager.getPlatformsWithRoms()
                    }

                    // Try to find a matching platform folder for the DB platform
                    val matchedPlatformFolder = findMatchingPlatformFolder(dbPlatform, availablePlatforms)

                    if (matchedPlatformFolder != null) {
                        // Load games only from the matched platform
                        libraryGames = withContext(Dispatchers.IO) {
                            GameCache.getGamesForPlatform(matchedPlatformFolder)
                        }.sortedBy { it.name.lowercase() }

                        android.util.Log.d("DbAssetPreviewDialog", "Loaded ${libraryGames.size} games for platform: $matchedPlatformFolder (DB platform: $dbPlatform)")
                    }
                }

                // If no games found for the matched platform, don't scan all platforms.
                // The user can tap "Change" to open the full game selector with platform dropdown.
                if (libraryGames.isEmpty()) {
                    android.util.Log.d("DbAssetPreviewDialog", "No games for platform $dbPlatform — user can tap Change to browse")
                    textTargetGameName.text = "No match found — tap Change"
                    textTargetGameName.setTextColor(context.getColor(R.color.theme_text_secondary))
                    return@launch
                }

                // Try to auto-select matching game
                val matchingGame = findMatchingGame(dbGameName)
                if (matchingGame != null) {
                    selectedGame = matchingGame
                    textTargetGameName.text = matchingGame.displayName
                    textTargetGameName.setTextColor(context.getColor(R.color.accent_cyan))
                    textSelectedGamePath.text = matchingGame.folder.absolutePath
                    textSelectedGamePath.visibility = View.VISIBLE
                    btnApply.isEnabled = true
                    showAssetComparison(currentTab)
                } else {
                    // No auto-match found — prompt user to select
                    textTargetGameName.text = "No match found — tap Change"
                    textTargetGameName.setTextColor(context.getColor(R.color.theme_text_secondary))
                }

            } catch (e: Exception) {
                android.util.Log.e("DbAssetPreviewDialog", "Error loading games: ${e.message}")
                textTargetGameName.text = "Error loading games"
                textTargetGameName.setTextColor(context.getColor(R.color.theme_text_secondary))
            }
        }
    }

    /**
     * Find a matching platform folder in the library for the given DB platform name.
     * Handles various naming conventions (e.g., "3DS" -> "n3ds", "eShop" -> "n3ds", etc.)
     */
    private fun findMatchingPlatformFolder(dbPlatform: String, availablePlatforms: List<String>): String? {
        val normalizedDbPlatform = dbPlatform.lowercase().replace(Regex("[^a-z0-9]"), "")

        // Direct match first
        availablePlatforms.find { it.equals(dbPlatform, ignoreCase = true) }?.let { return it }

        // Common DB platform name mappings to iiSU folder names
        val platformMappings = mapOf(
            "3ds" to listOf("n3ds", "3ds"),
            "n3ds" to listOf("n3ds", "3ds"),
            "eshop" to listOf("n3ds", "3ds", "wiiu", "switch"),  // eShop games could be on multiple platforms
            "ds" to listOf("nds", "ds"),
            "nds" to listOf("nds", "ds"),
            "gamecube" to listOf("gc", "gamecube"),
            "gc" to listOf("gc", "gamecube"),
            "genesis" to listOf("genesis", "megadrive", "md"),
            "megadrive" to listOf("genesis", "megadrive", "md"),
            "mastersystem" to listOf("ms", "mastersystem", "sms"),
            "ms" to listOf("ms", "mastersystem", "sms"),
            "playstation" to listOf("ps1", "psx", "playstation"),
            "ps1" to listOf("ps1", "psx"),
            "psx" to listOf("ps1", "psx"),
            "gameboy" to listOf("gb", "gameboy"),
            "gb" to listOf("gb", "gameboy"),
            "gameboycolor" to listOf("gbc"),
            "gbc" to listOf("gbc"),
            "gameboyadvance" to listOf("gba"),
            "gba" to listOf("gba"),
            "virtualboy" to listOf("vb", "virtualboy"),
            "vb" to listOf("vb", "virtualboy"),
            "gamegear" to listOf("gg", "gamegear"),
            "gg" to listOf("gg", "gamegear"),
            "neogeopocket" to listOf("ngp", "neogeopocket"),
            "ngp" to listOf("ngp"),
            "neogeopocketcolor" to listOf("ngpc", "neogeopocketcolor"),
            "ngpc" to listOf("ngpc"),
            "turbografx" to listOf("tg16", "pce", "turbografx"),
            "tg16" to listOf("tg16", "pce"),
            "pcengine" to listOf("tg16", "pce"),
            "wonderswan" to listOf("ws", "wonderswan"),
            "ws" to listOf("ws"),
            "wonderswancolor" to listOf("wsc", "wonderswancolor"),
            "wsc" to listOf("wsc")
        )

        // Check mappings
        platformMappings[normalizedDbPlatform]?.forEach { mappedFolder ->
            availablePlatforms.find { it.equals(mappedFolder, ignoreCase = true) }?.let { return it }
        }

        // Try Platform enum matching
        val platformEnum = Platform.values().find {
            it.displayName.equals(dbPlatform, ignoreCase = true) ||
            it.iisuFolder.equals(dbPlatform, ignoreCase = true) ||
            it.searchId.equals(dbPlatform, ignoreCase = true) ||
            it.name.replace("_", "").equals(normalizedDbPlatform, ignoreCase = true)
        }
        if (platformEnum != null) {
            availablePlatforms.find { it.equals(platformEnum.iisuFolder, ignoreCase = true) }?.let { return it }
        }

        // Fuzzy match - check if DB platform name is contained in or contains any available platform
        availablePlatforms.find { folder ->
            val normalizedFolder = folder.lowercase().replace(Regex("[^a-z0-9]"), "")
            normalizedDbPlatform.contains(normalizedFolder) || normalizedFolder.contains(normalizedDbPlatform)
        }?.let { return it }

        return null
    }

    private fun findMatchingGame(dbName: String): GameInfo? {
        val normalizedDbName = dbName.lowercase().replace(Regex("[^a-z0-9]"), "")

        return libraryGames.find { game ->
            val normalizedGameName = game.name.lowercase().replace(Regex("[^a-z0-9]"), "")
            normalizedGameName == normalizedDbName ||
            game.name.equals(dbName, ignoreCase = true) ||
            game.displayName.equals(dbName, ignoreCase = true)
        }
    }

    private fun setupTabs() {
        // Add tabs for each asset type
        tabLayoutAssets.addTab(tabLayoutAssets.newTab().setText("Icon"))
        tabLayoutAssets.addTab(tabLayoutAssets.newTab().setText("Hero"))
        tabLayoutAssets.addTab(tabLayoutAssets.newTab().setText("Logo"))

        // Color tabs based on DB asset availability
        updateTabColors()

        // Tab selection listener
        tabLayoutAssets.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab?) {
                currentTab = when (tab?.position) {
                    0 -> DbAsset.AssetType.ICON
                    1 -> DbAsset.AssetType.HERO
                    2 -> DbAsset.AssetType.LOGO
                    else -> DbAsset.AssetType.ICON
                }
                showAssetComparison(currentTab)
            }
            override fun onTabUnselected(tab: TabLayout.Tab?) {}
            override fun onTabReselected(tab: TabLayout.Tab?) {}
        })

        // Show initial comparison
        showAssetComparison(currentTab)
    }

    private fun updateTabColors() {
        val assetTypes = listOf(DbAsset.AssetType.ICON, DbAsset.AssetType.HERO, DbAsset.AssetType.LOGO)
        assetTypes.forEachIndexed { index, type ->
            val tab = tabLayoutAssets.getTabAt(index)
            val hasAsset = dbAssets.any { it.type == type }
            tab?.view?.let { tabView ->
                val textView = tabView.findViewById<TextView>(android.R.id.text1)
                textView?.setTextColor(
                    context.getColor(
                        if (hasAsset) R.color.accent_cyan else R.color.theme_text_secondary
                    )
                )
            }
        }
    }

    private fun showAssetComparison(assetType: DbAsset.AssetType) {
        // Show current asset from library
        showCurrentAsset(assetType)

        // Show DB asset
        showDbAsset(assetType)
    }

    private fun showCurrentAsset(assetType: DbAsset.AssetType) {
        val game = selectedGame

        if (game == null) {
            imageCurrentAsset.setImageResource(R.drawable.ic_image_placeholder)
            // Don't show any text here - the spinner hint already shows "Select a game..."
            textNoCurrentAsset.visibility = View.GONE
            textCurrentInfo.text = ""
            return
        }

        val (file, hasAsset) = when (assetType) {
            DbAsset.AssetType.ICON -> Pair(game.iconFile, game.hasIcon)
            DbAsset.AssetType.HERO -> Pair(game.heroFile, game.hasHero)
            DbAsset.AssetType.LOGO -> Pair(game.logoFile, game.hasLogo)
        }

        if (hasAsset && file != null && file.exists()) {
            val bitmap = BitmapFactory.decodeFile(file.absolutePath)
            if (bitmap != null) {
                imageCurrentAsset.setImageBitmap(bitmap)
                textNoCurrentAsset.visibility = View.GONE
                textCurrentInfo.text = "${bitmap.width}x${bitmap.height}"
            } else {
                showNoCurrentAsset(assetType)
            }
        } else {
            showNoCurrentAsset(assetType)
        }
    }

    private fun showNoCurrentAsset(assetType: DbAsset.AssetType) {
        imageCurrentAsset.setImageResource(R.drawable.ic_image_placeholder)
        textNoCurrentAsset.text = "No ${assetType.name.lowercase()}"
        textNoCurrentAsset.visibility = View.VISIBLE
        textCurrentInfo.text = ""
    }

    private fun showDbAsset(assetType: DbAsset.AssetType) {
        val dbAsset = dbAssets.find { it.type == assetType }

        if (dbAsset == null) {
            imageDbAsset.setImageResource(R.drawable.ic_image_placeholder)
            textNoDbAsset.text = "Not in DB"
            textNoDbAsset.visibility = View.VISIBLE
            textDbInfo.text = ""
            progressDbAsset.visibility = View.GONE
            return
        }

        // Check cache first
        val cachedBitmap = dbBitmapCache[assetType]
        if (cachedBitmap != null) {
            imageDbAsset.setImageBitmap(cachedBitmap)
            textNoDbAsset.visibility = View.GONE
            textDbInfo.text = "${cachedBitmap.width}x${cachedBitmap.height}"
            progressDbAsset.visibility = View.GONE
            return
        }

        // Load from URL
        progressDbAsset.visibility = View.VISIBLE
        textNoDbAsset.visibility = View.GONE
        textDbInfo.text = "Loading..."

        lifecycleOwner.lifecycleScope.launch {
            try {
                val bitmap = withContext(Dispatchers.IO) {
                    loadBitmapFromUrl(dbAsset.downloadUrl)
                }

                if (bitmap != null) {
                    dbBitmapCache[assetType] = bitmap
                    imageDbAsset.setImageBitmap(bitmap)
                    textDbInfo.text = "${bitmap.width}x${bitmap.height}"
                } else {
                    imageDbAsset.setImageResource(R.drawable.ic_image_placeholder)
                    textNoDbAsset.text = "Load failed"
                    textNoDbAsset.visibility = View.VISIBLE
                    textDbInfo.text = ""
                }
            } catch (e: Exception) {
                android.util.Log.e("DbAssetPreviewDialog", "Error loading DB asset: ${e.message}")
                imageDbAsset.setImageResource(R.drawable.ic_image_placeholder)
                textNoDbAsset.text = "Error"
                textNoDbAsset.visibility = View.VISIBLE
                textDbInfo.text = ""
            } finally {
                progressDbAsset.visibility = View.GONE
            }
        }
    }

    private fun loadBitmapFromUrl(url: String): Bitmap? {
        return try {
            android.util.Log.d("DbAssetPreviewDialog", "Loading bitmap from: $url")

            val connection = URL(url).openConnection() as java.net.HttpURLConnection
            connection.connectTimeout = 10_000
            connection.readTimeout = 30_000
            connection.instanceFollowRedirects = true
            connection.setRequestProperty("User-Agent", "iiSU-Asset-Tool-Android/1.0")
            connection.setRequestProperty("Accept", "image/*")

            if (connection.responseCode == java.net.HttpURLConnection.HTTP_OK) {
                connection.inputStream.use { input ->
                    BitmapFactory.decodeStream(input)
                }
            } else {
                android.util.Log.e("DbAssetPreviewDialog", "HTTP error: ${connection.responseCode}")
                null
            }
        } catch (e: Exception) {
            android.util.Log.e("DbAssetPreviewDialog", "Error downloading bitmap: ${e.message}", e)
            null
        }
    }

    private fun applyAssets() {
        val game = selectedGame
        if (game == null) {
            Toast.makeText(context, "Please select a target game", Toast.LENGTH_SHORT).show()
            return
        }

        // Get selected assets to apply
        val assetsToApply = mutableListOf<DbAsset>()
        if (checkIcon.isChecked) {
            dbAssets.find { it.type == DbAsset.AssetType.ICON }?.let { assetsToApply.add(it) }
        }
        if (checkHero.isChecked) {
            dbAssets.find { it.type == DbAsset.AssetType.HERO }?.let { assetsToApply.add(it) }
        }
        if (checkLogo.isChecked) {
            dbAssets.find { it.type == DbAsset.AssetType.LOGO }?.let { assetsToApply.add(it) }
        }

        if (assetsToApply.isEmpty()) {
            Toast.makeText(context, "Please select at least one asset", Toast.LENGTH_SHORT).show()
            return
        }

        // Disable UI during apply
        btnApply.isEnabled = false
        btnCancel.isEnabled = false
        progressApply.visibility = View.VISIBLE

        lifecycleOwner.lifecycleScope.launch {
            try {
                var successCount = 0
                val targetFolder = game.folder

                for (asset in assetsToApply) {
                    val success = withContext(Dispatchers.IO) {
                        downloadAndSaveAsset(asset, targetFolder)
                    }
                    if (success) successCount++
                }

                // Invalidate cache for this platform
                val platformFolder = game.folder.parentFile?.name
                if (platformFolder != null) {
                    GameCache.invalidatePlatform(platformFolder)
                }

                dismiss()
                onApplyComplete(
                    successCount > 0,
                    "Applied $successCount/${assetsToApply.size} assets to ${game.displayName}"
                )

            } catch (e: Exception) {
                android.util.Log.e("DbAssetPreviewDialog", "Error applying assets: ${e.message}")
                Toast.makeText(context, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            } finally {
                btnApply.isEnabled = true
                btnCancel.isEnabled = true
                progressApply.visibility = View.GONE
            }
        }
    }

    /**
     * Map asset type to the correct iiSU filename convention:
     * - Icon  → icon.png
     * - Hero  → hero_1.png (numbered)
     * - Logo  → title.png
     *
     * Preserves the original file extension if it's a known image format,
     * otherwise defaults to .png
     */
    private fun getTargetFilename(asset: DbAsset): String {
        val ext = asset.filename.substringAfterLast('.', "png").lowercase()
        val imageExt = if (ext in listOf("png", "jpg", "jpeg", "webp")) ext else "png"

        return when (asset.type) {
            DbAsset.AssetType.ICON -> "icon.$imageExt"
            DbAsset.AssetType.HERO -> "hero_1.$imageExt"
            DbAsset.AssetType.LOGO -> "title.$imageExt"
        }
    }

    private fun downloadAndSaveAsset(asset: DbAsset, targetFolder: File): Boolean {
        return try {
            val targetFilename = getTargetFilename(asset)
            val targetFile = File(targetFolder, targetFilename)
            val url = URL(asset.downloadUrl)

            android.util.Log.d("DbAssetPreviewDialog",
                "Downloading ${asset.type.name}: ${asset.filename} → $targetFilename")

            url.openStream().use { input ->
                FileOutputStream(targetFile).use { output ->
                    input.copyTo(output)
                }
            }
            true
        } catch (e: Exception) {
            android.util.Log.e("DbAssetPreviewDialog", "Error downloading ${asset.filename}: ${e.message}")
            false
        }
    }

    override fun dismiss() {
        // Clean up cached bitmaps
        dbBitmapCache.values.forEach { it?.recycle() }
        dbBitmapCache.clear()
        super.dismiss()
    }

    companion object {
        /**
         * Show the preview dialog for an iiSU asset server game entry.
         */
        fun show(
            context: Context,
            lifecycleOwner: LifecycleOwner,
            dbGameName: String,
            dbPlatform: String,
            dbAssets: List<DbAsset>,
            onApplyComplete: (success: Boolean, message: String) -> Unit
        ) {
            DbAssetPreviewDialog(
                context = context,
                lifecycleOwner = lifecycleOwner,
                dbGameName = dbGameName,
                dbPlatform = dbPlatform,
                dbAssets = dbAssets,
                onApplyComplete = onApplyComplete
            ).show()
        }
    }
}
