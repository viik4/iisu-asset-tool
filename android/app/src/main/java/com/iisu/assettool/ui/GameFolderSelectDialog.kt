package com.iisu.assettool.ui

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.textfield.TextInputLayout
import com.iisu.assettool.R
import com.iisu.assettool.util.AndroidAppInfo
import com.iisu.assettool.util.GameCache
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Dialog to select a game folder from the iiSU library.
 * Used by both the Community DB tab (for applying assets) and the Music tab (for soundbytes).
 *
 * Loads games one platform at a time to avoid scanning the entire library.
 * Includes a console/platform dropdown to switch between platforms.
 */
class GameFolderSelectDialog private constructor(
    private val context: Context,
    private val suggestedName: String,
    private val suggestedPlatform: String,
    private val mode: Mode,
    private val coroutineScope: CoroutineScope,
    private val onGameSelected: (GameInfo) -> Unit
) {
    enum class Mode {
        /** Selecting a game to apply assets (icon/hero/logo) to */
        ASSETS,
        /** Selecting a game to add a soundbyte to */
        SOUNDBYTE
    }

    private var dialog: AlertDialog? = null
    private var adapter: GameListAdapter? = null
    private var allGames: List<GameWithPlatform> = emptyList()
    private var filterText: String = ""
    private var availablePlatforms: List<String> = emptyList()
    private var currentPlatform: String? = null

    data class GameWithPlatform(
        val game: GameInfo,
        val platform: String,
        val hasMusic: Boolean,
        val assetStatus: String  // e.g. "I/H/L" or ""
    )

    companion object {
        /** Virtual platform name for Android apps (stored in a separate directory) */
        const val ANDROID_APPS_PLATFORM = "Android Apps"

        /**
         * Show the game folder selection dialog.
         *
         * @param context The context
         * @param suggestedName Optional game name to suggest (for filtering)
         * @param suggestedPlatform Optional platform name to pre-select (loads only that console's games first)
         * @param mode Whether selecting for assets or soundbytes
         * @param coroutineScope Scope for coroutines
         * @param onGameSelected Callback when a game is selected
         */
        fun show(
            context: Context,
            suggestedName: String = "",
            suggestedPlatform: String = "",
            mode: Mode = Mode.SOUNDBYTE,
            coroutineScope: CoroutineScope,
            onGameSelected: (GameInfo) -> Unit
        ) {
            GameFolderSelectDialog(context, suggestedName, suggestedPlatform, mode, coroutineScope, onGameSelected).showDialog()
        }
    }

    private fun showDialog() {
        val dialogView = LayoutInflater.from(context)
            .inflate(R.layout.dialog_game_folder_select, null)

        val recyclerGames = dialogView.findViewById<RecyclerView>(R.id.recyclerGames)
        val editFilter = dialogView.findViewById<EditText>(R.id.editFilter)
        val textLoading = dialogView.findViewById<TextView>(R.id.textLoading)
        val textEmpty = dialogView.findViewById<TextView>(R.id.textEmpty)
        val textDescription = dialogView.findViewById<TextView>(R.id.textDescription)
        val layoutPlatformSelect = dialogView.findViewById<TextInputLayout>(R.id.layoutPlatformSelect)
        val spinnerPlatform = dialogView.findViewById<AutoCompleteTextView>(R.id.spinnerPlatform)

        // Update description based on mode
        textDescription?.text = when (mode) {
            Mode.ASSETS -> "Select a game to apply these assets to:"
            Mode.SOUNDBYTE -> "Select a game to add the soundbyte to:"
        }

        adapter = GameListAdapter(mode) { gameWithPlatform ->
            dialog?.dismiss()
            onGameSelected(gameWithPlatform.game)
        }

        recyclerGames.layoutManager = LinearLayoutManager(context)
        recyclerGames.adapter = adapter

        // Set up filter
        editFilter.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: android.text.Editable?) {
                filterText = s?.toString()?.lowercase() ?: ""
                applyFilter(textEmpty)
            }
        })

        // Pre-fill filter with suggested name
        if (suggestedName.isNotEmpty()) {
            editFilter.setText(suggestedName)
        }

        // Platform spinner change handler
        spinnerPlatform.setOnItemClickListener { _, _, position, _ ->
            if (position < availablePlatforms.size) {
                val selected = availablePlatforms[position]
                if (selected != currentPlatform) {
                    currentPlatform = selected
                    loadGamesForPlatform(selected, textLoading, textEmpty)
                }
            }
        }

        val title = when (mode) {
            Mode.ASSETS -> "Select Target Game"
            Mode.SOUNDBYTE -> "Select Game"
        }

        dialog = MaterialAlertDialogBuilder(context)
            .setTitle(title)
            .setView(dialogView)
            .setNegativeButton("Cancel", null)
            .create()

        dialog?.show()

        // Load platforms first, then games for the best-match platform
        loadPlatforms(layoutPlatformSelect, spinnerPlatform, textLoading, textEmpty)
    }

    /**
     * Load available platforms, then auto-select the best match and load its games.
     */
    private fun loadPlatforms(
        layoutPlatformSelect: TextInputLayout,
        spinnerPlatform: AutoCompleteTextView,
        textLoading: TextView,
        textEmpty: TextView
    ) {
        textLoading.visibility = View.VISIBLE
        textLoading.text = "Scanning library..."

        coroutineScope.launch {
            try {
                val platforms = withContext(Dispatchers.IO) {
                    val consolePlatforms = IisuDirectoryManager.getPlatformsWithRoms().sorted()

                    // Check if Android apps directory exists and has content
                    val androidAppsDir = IisuDirectoryManager.getAndroidAppsDir()
                    val hasAndroidApps = androidAppsDir.exists() && androidAppsDir.isDirectory &&
                        (androidAppsDir.listFiles()?.any { it.isDirectory && !it.name.startsWith(".") } == true)

                    if (hasAndroidApps) {
                        consolePlatforms + ANDROID_APPS_PLATFORM
                    } else {
                        consolePlatforms
                    }
                }

                withContext(Dispatchers.Main) {
                    availablePlatforms = platforms

                    if (platforms.isEmpty()) {
                        textLoading.visibility = View.GONE
                        textEmpty.visibility = View.VISIBLE
                        textEmpty.text = "No platforms found in iiSU library"
                        layoutPlatformSelect.visibility = View.GONE
                        return@withContext
                    }

                    // Populate platform dropdown
                    val platformAdapter = ArrayAdapter(
                        context,
                        android.R.layout.simple_spinner_dropdown_item,
                        platforms
                    )
                    spinnerPlatform.setAdapter(platformAdapter)

                    // Find best matching platform for suggestedPlatform
                    val matchedPlatform = if (suggestedPlatform.isNotEmpty()) {
                        findMatchingPlatform(suggestedPlatform, platforms)
                    } else {
                        null
                    }

                    val selectedPlatform = matchedPlatform ?: platforms.first()
                    currentPlatform = selectedPlatform
                    spinnerPlatform.setText(selectedPlatform, false)

                    // Load games for the selected platform
                    loadGamesForPlatform(selectedPlatform, textLoading, textEmpty)
                }

            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    textLoading.visibility = View.GONE
                    textEmpty.visibility = View.VISIBLE
                    textEmpty.text = "Error loading library: ${e.message}"
                }
            }
        }
    }

    /**
     * Load games for a single platform. Fast because it only scans one folder.
     * For "Android Apps", loads from the separate Android apps directory instead.
     */
    private fun loadGamesForPlatform(platform: String, textLoading: TextView, textEmpty: TextView) {
        textLoading.visibility = View.VISIBLE
        textLoading.text = "Loading $platform..."
        adapter?.submitList(emptyList())

        coroutineScope.launch {
            try {
                val gamesList = if (platform == ANDROID_APPS_PLATFORM) {
                    // Load Android apps and convert to GameWithPlatform
                    withContext(Dispatchers.IO) {
                        val apps = IisuDirectoryManager.getAndroidApps()
                        apps.map { app ->
                            val hasMusic = listOf("mp3", "ogg", "flac", "wav").any { ext ->
                                File(app.folder, "music.$ext").exists()
                            }

                            val statusParts = mutableListOf<String>()
                            if (app.hasIcon) statusParts.add("I")
                            if (app.hasHero) statusParts.add("H")
                            if (app.hasLogo) statusParts.add("L")
                            val assetStatus = if (statusParts.isNotEmpty()) statusParts.joinToString("/") else ""

                            // Wrap AndroidAppInfo as a GameInfo so the rest of the dialog works
                            val gameInfo = GameInfo(
                                name = app.packageName,
                                folder = app.folder,
                                hasIcon = app.hasIcon,
                                hasHero = app.hasHero,
                                hasLogo = app.hasLogo,
                                iconFile = app.iconFile,
                                heroFile = app.heroFile,
                                logoFile = app.logoFile
                            )

                            GameWithPlatform(
                                game = gameInfo,
                                platform = ANDROID_APPS_PLATFORM,
                                hasMusic = hasMusic,
                                assetStatus = assetStatus
                            )
                        }
                    }
                } else {
                    // Load console games
                    val games = withContext(Dispatchers.IO) {
                        GameCache.getGamesForPlatform(platform, forceRefresh = false, deepSearch = false)
                    }

                    // Build the display list — batch music checks in IO context
                    withContext(Dispatchers.IO) {
                        games.map { game ->
                            val hasMusic = listOf("mp3", "ogg", "flac", "wav").any { ext ->
                                File(game.folder, "music.$ext").exists()
                            }

                            val statusParts = mutableListOf<String>()
                            if (game.hasIcon) statusParts.add("I")
                            if (game.hasHero) statusParts.add("H")
                            if (game.hasLogo) statusParts.add("L")
                            val assetStatus = if (statusParts.isNotEmpty()) statusParts.joinToString("/") else ""

                            GameWithPlatform(
                                game = game,
                                platform = platform,
                                hasMusic = hasMusic,
                                assetStatus = assetStatus
                            )
                        }
                    }
                }

                allGames = gamesList.sortedBy { it.game.displayName.lowercase() }

                withContext(Dispatchers.Main) {
                    textLoading.visibility = View.GONE
                    applyFilter(textEmpty)
                }

            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    textLoading.visibility = View.GONE
                    textEmpty.visibility = View.VISIBLE
                    textEmpty.text = "Error loading games: ${e.message}"
                }
            }
        }
    }

    /**
     * Find a matching platform folder for the given DB/suggested platform name.
     */
    private fun findMatchingPlatform(dbPlatform: String, platforms: List<String>): String? {
        val normalized = dbPlatform.lowercase().replace(Regex("[^a-z0-9]"), "")

        // Direct match
        platforms.find { it.equals(dbPlatform, ignoreCase = true) }?.let { return it }

        // Android apps match
        if (normalized == "android" || normalized == "androidapps") {
            platforms.find { it == ANDROID_APPS_PLATFORM }?.let { return it }
        }

        // Common mappings
        val mappings = mapOf(
            "3ds" to listOf("n3ds", "3ds"),
            "n3ds" to listOf("n3ds", "3ds"),
            "eshop" to listOf("n3ds", "3ds", "wiiu", "switch"),
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

        mappings[normalized]?.forEach { mapped ->
            platforms.find { it.equals(mapped, ignoreCase = true) }?.let { return it }
        }

        // Fuzzy match
        platforms.find { folder ->
            val normalizedFolder = folder.lowercase().replace(Regex("[^a-z0-9]"), "")
            normalized.contains(normalizedFolder) || normalizedFolder.contains(normalized)
        }?.let { return it }

        return null
    }

    private fun applyFilter(textEmpty: TextView) {
        val filtered = if (filterText.isEmpty()) {
            allGames
        } else {
            allGames.filter { gameWithPlatform ->
                gameWithPlatform.game.displayName.lowercase().contains(filterText) ||
                    gameWithPlatform.platform.lowercase().contains(filterText)
            }
        }

        adapter?.submitList(filtered)

        textEmpty.visibility = if (filtered.isEmpty() && allGames.isNotEmpty()) {
            textEmpty.text = "No games match your search"
            View.VISIBLE
        } else if (allGames.isEmpty()) {
            textEmpty.text = "No games found for this console"
            View.VISIBLE
        } else {
            View.GONE
        }
    }

    /**
     * RecyclerView adapter for game list
     */
    private class GameListAdapter(
        private val mode: Mode,
        private val onGameClick: (GameWithPlatform) -> Unit
    ) : RecyclerView.Adapter<GameListAdapter.ViewHolder>() {

        private var games: List<GameWithPlatform> = emptyList()

        fun submitList(newGames: List<GameWithPlatform>) {
            games = newGames
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_game_folder, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            holder.bind(games[position])
        }

        override fun getItemCount() = games.size

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            private val textGameName: TextView = view.findViewById(R.id.textGameName)
            private val textPlatform: TextView = view.findViewById(R.id.textPlatform)
            private val iconMusic: ImageView = view.findViewById(R.id.iconMusic)
            private val textAssetStatus: TextView? = view.findViewById(R.id.textAssetStatus)

            fun bind(gameWithPlatform: GameWithPlatform) {
                textGameName.text = gameWithPlatform.game.displayName
                textPlatform.text = gameWithPlatform.platform

                when (mode) {
                    Mode.SOUNDBYTE -> {
                        // Show music icon if game already has music
                        iconMusic.visibility = if (gameWithPlatform.hasMusic) View.VISIBLE else View.GONE
                        textAssetStatus?.visibility = View.GONE
                    }
                    Mode.ASSETS -> {
                        // Show asset status (I/H/L) instead of music icon
                        iconMusic.visibility = View.GONE
                        if (gameWithPlatform.assetStatus.isNotEmpty()) {
                            textAssetStatus?.visibility = View.VISIBLE
                            textAssetStatus?.text = gameWithPlatform.assetStatus
                        } else {
                            textAssetStatus?.visibility = View.GONE
                        }
                    }
                }

                itemView.setOnClickListener {
                    onGameClick(gameWithPlatform)
                }
            }
        }
    }
}
