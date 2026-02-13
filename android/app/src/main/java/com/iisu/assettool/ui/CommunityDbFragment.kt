package com.iisu.assettool.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import coil.load
import coil.request.CachePolicy
import com.iisu.assettool.R
import com.iisu.assettool.data.AssetServerClient
import com.iisu.assettool.data.Platform
import com.iisu.assettool.databinding.FragmentCommunityDbBinding
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Community Database Fragment
 *
 * Browse and download pre-themed assets from the iiSU community asset server.
 * Assets are already styled with appropriate borders - just pick and apply.
 */
class CommunityDbFragment : Fragment() {

    private var _binding: FragmentCommunityDbBinding? = null
    private val binding get() = _binding!!

    private lateinit var client: AssetServerClient

    // Cached data
    private var platforms: MutableMap<String, String> = mutableMapOf() // name -> platform id
    private var currentPlatform: String? = null
    private var currentGames: MutableList<GameEntry> = mutableListOf()
    private var isScanning = false

    private lateinit var gameAdapter: CommunityGameAdapter

    data class GameEntry(
        val id: Int,
        val name: String,
        val platformName: String,
        val variantNumber: Int,
        val assetCount: Int,
        val iconUrl: String? = null,
        val assets: List<AssetServerClient.Asset> = emptyList()
    )

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentCommunityDbBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        client = AssetServerClient()

        setupGameGrid()
        setupPlatformSpinner()
        setupRefreshButton()
        setupSearchInput()
        setupUploadButton()

        // Auto-connect on launch
        scanDatabase()
    }

    private fun setupGameGrid() {
        gameAdapter = CommunityGameAdapter(
            onGameClick = { game -> showGameVariants(game) }
        )

        // Use 3 columns for better readability on phone screens
        binding.recyclerGames.apply {
            layoutManager = GridLayoutManager(context, 3)
            adapter = gameAdapter
        }
    }

    private fun setupPlatformSpinner() {
        binding.spinnerPlatform.setOnItemClickListener { _, _, position, _ ->
            // IMPORTANT: Use sorted list to match the adapter order
            val platformNames = platforms.keys.sorted()
            if (position < platformNames.size) {
                currentPlatform = platformNames[position]
                loadGamesForPlatform(currentPlatform!!)
            }
        }
    }

    private fun setupRefreshButton() {
        binding.buttonRefresh.setOnClickListener {
            scanDatabase(force = true)
        }
    }

    private fun setupSearchInput() {
        // Filter in real-time as user types
        binding.editSearch.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: android.text.Editable?) {
                filterGames(s?.toString() ?: "")
            }
        })

        // Also handle keyboard search action
        binding.editSearch.setOnEditorActionListener { _, _, _ ->
            hideKeyboard()
            filterGames(binding.editSearch.text.toString())
            true
        }
    }

    private fun hideKeyboard() {
        val imm = context?.getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as? android.view.inputmethod.InputMethodManager
        binding.editSearch.clearFocus()
        imm?.hideSoftInputFromWindow(binding.editSearch.windowToken, 0)
    }

    private fun setupUploadButton() {
        binding.buttonUpload.setOnClickListener {
            showUploadDialog()
        }
    }

    private fun showUploadDialog() {
        val platformNames = platforms.keys.sorted()
        UploadAssetBottomSheet.show(
            fragment = this,
            client = client,
            platforms = platformNames,
            onUploadComplete = {
                // Refresh the current platform after successful upload
                scanDatabase(force = true)
            }
        )
    }

    @Suppress("UNUSED_PARAMETER")
    private fun scanDatabase(force: Boolean = false) {
        if (isScanning) return
        isScanning = true

        _binding?.progressBar?.visibility = View.VISIBLE
        _binding?.textStatus?.text = "Connecting to asset server..."

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val serverPlatforms = withContext(Dispatchers.IO) {
                    client.getPlatformsWithGames()
                }

                if (_binding == null) return@launch

                platforms = serverPlatforms
                    .associate { it.name to it.id.toString() }
                    .toMutableMap()

                val platformNames = platforms.keys.sorted()
                val adapter = ArrayAdapter(
                    requireContext(),
                    android.R.layout.simple_spinner_dropdown_item,
                    platformNames
                )
                _binding?.spinnerPlatform?.setAdapter(adapter)

                if (platformNames.isNotEmpty()) {
                    _binding?.spinnerPlatform?.setText(platformNames.first(), false)
                    currentPlatform = platformNames.first()
                    loadGamesForPlatform(currentPlatform!!)
                }

                _binding?.textStatus?.text = "${platforms.size} platforms available"

            } catch (e: Exception) {
                android.util.Log.e("CommunityDbFragment", "Scan error: ${e.message}", e)
                _binding?.textStatus?.text = "Connection error - tap refresh to retry"
                context?.let {
                    Toast.makeText(it, "Failed to connect: ${e.message}", Toast.LENGTH_LONG).show()
                }
            } finally {
                _binding?.progressBar?.visibility = View.GONE
                isScanning = false
            }
        }
    }

    private fun loadGamesForPlatform(platform: String) {
        _binding?.progressBar?.visibility = View.VISIBLE
        _binding?.textStatus?.text = "Loading games for $platform..."

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val serverGames = withContext(Dispatchers.IO) {
                    client.getGames(platform)
                }

                if (_binding == null) return@launch

                // Group by game name to handle variants
                val gamesByName = serverGames.groupBy { it.name }
                val gameEntries = gamesByName.map { (name, variants) ->
                    val firstVariant = variants.first()
                    // Find icon URL from first variant's assets
                    val iconAsset = firstVariant.assets.find { it.assetType == "icon" }
                    GameEntry(
                        id = firstVariant.id,
                        name = name,
                        platformName = platform,
                        variantNumber = firstVariant.variantNumber,
                        assetCount = firstVariant.assetCount,
                        iconUrl = iconAsset?.thumbnailUrl,
                        assets = firstVariant.assets
                    )
                }

                currentGames = gameEntries.sortedBy { it.name.lowercase() }.toMutableList()
                gameAdapter.submitList(currentGames.toList())

                val displayPlatform = _binding?.spinnerPlatform?.text?.toString() ?: platform
                _binding?.textStatus?.text = "${currentGames.size} games in $displayPlatform"

            } catch (e: Exception) {
                _binding?.textStatus?.text = "Error loading games"
                context?.let {
                    Toast.makeText(it, "Failed to load games", Toast.LENGTH_SHORT).show()
                }
            } finally {
                _binding?.progressBar?.visibility = View.GONE
            }
        }
    }

    private fun filterGames(query: String) {
        val filtered = if (query.isBlank()) {
            currentGames.toList()
        } else {
            currentGames.filter { it.name.contains(query, ignoreCase = true) }
        }
        gameAdapter.submitList(filtered)
        _binding?.textStatus?.text = "${filtered.size} games"
    }

    private fun showGameVariants(game: GameEntry) {
        showAssetPreviewDialog(game)
    }

    private fun showAssetPreviewDialog(game: GameEntry) {
        _binding?.progressBar?.visibility = View.VISIBLE
        _binding?.textStatus?.text = "Loading assets for ${game.name}..."

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                // Fetch full game data with assets from server
                val serverGame = withContext(Dispatchers.IO) {
                    client.getGame(game.id)
                }

                if (_binding == null) return@launch

                val assets = serverGame?.assets ?: emptyList()

                if (assets.isEmpty()) {
                    context?.let {
                        Toast.makeText(it, "No assets found in database", Toast.LENGTH_SHORT).show()
                    }
                    _binding?.textStatus?.text = "No assets found for ${game.name}"
                    _binding?.progressBar?.visibility = View.GONE
                    return@launch
                }

                // Convert to DbAsset format
                val dbAssets = assets.mapNotNull { asset ->
                    val assetType = when (asset.assetType) {
                        "icon" -> DbAssetPreviewDialog.DbAsset.AssetType.ICON
                        "hero" -> DbAssetPreviewDialog.DbAsset.AssetType.HERO
                        "logo" -> DbAssetPreviewDialog.DbAsset.AssetType.LOGO
                        else -> null
                    }

                    assetType?.let {
                        DbAssetPreviewDialog.DbAsset(
                            filename = asset.filename,
                            fileId = asset.id.toString(),
                            downloadUrl = asset.downloadUrl,
                            type = it
                        )
                    }
                }

                _binding?.progressBar?.visibility = View.GONE
                val displayPlatform = currentPlatform ?: game.platformName
                _binding?.textStatus?.text = "${currentGames.size} games in $displayPlatform"

                context?.let { ctx ->
                    DbAssetPreviewDialog.show(
                        context = ctx,
                        lifecycleOwner = viewLifecycleOwner,
                        dbGameName = game.name,
                        dbPlatform = game.platformName,
                        dbAssets = dbAssets,
                        onApplyComplete = { success, message ->
                            _binding?.textStatus?.text = message
                            if (success) {
                                Toast.makeText(ctx, message, Toast.LENGTH_SHORT).show()
                            }
                        }
                    )
                }

            } catch (e: Exception) {
                _binding?.textStatus?.text = "Error loading assets: ${e.message}"
                context?.let {
                    Toast.makeText(it, "Failed to load assets", Toast.LENGTH_SHORT).show()
                }
                _binding?.progressBar?.visibility = View.GONE
            }
        }
    }

    private fun findOrCreateGameFolder(platform: Platform, gameName: String): File {
        val platformDir = IisuDirectoryManager.getPlatformDir(platform.iisuFolder)

        // Look for existing folder with similar name
        val sluggedName = safeSlug(gameName)
        val normalizedSearch = gameName.lowercase().replace(Regex("[^a-z0-9]"), "")

        val existingFolder = platformDir.listFiles()?.find { folder ->
            if (!folder.isDirectory || folder.name.startsWith(".")) return@find false
            val normalizedFolder = folder.name.lowercase().replace(Regex("[^a-z0-9]"), "")
            folder.name == sluggedName ||
            folder.name.equals(gameName, ignoreCase = true) ||
            normalizedFolder == normalizedSearch
        }

        return existingFolder ?: File(platformDir, sluggedName).apply { mkdirs() }
    }

    private fun safeSlug(name: String): String {
        return name.trim()
            .replace(Regex("[^\\w\\-\\s]"), "")
            .replace(Regex("\\s+"), "_")
            .take(180)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    // ==================== RecyclerView Adapter ====================

    inner class CommunityGameAdapter(
        private val onGameClick: (GameEntry) -> Unit
    ) : RecyclerView.Adapter<CommunityGameAdapter.ViewHolder>() {

        private var games: List<GameEntry> = emptyList()

        fun submitList(newGames: List<GameEntry>) {
            games = newGames
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_game_grid, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            holder.bind(games[position])
        }

        override fun getItemCount() = games.size

        inner class ViewHolder(private val view: View) : RecyclerView.ViewHolder(view) {
            private val imageView = view.findViewById<android.widget.ImageView>(R.id.imageGameIcon)
            private val textName = view.findViewById<android.widget.TextView>(R.id.textGameName)
            private val textIconStatus = view.findViewById<android.widget.TextView>(R.id.textIconStatus)
            private val btnGenerateIcon = view.findViewById<View>(R.id.btnGenerateIcon)

            fun bind(game: GameEntry) {
                textName.text = game.name
                textName.visibility = View.VISIBLE
                // Slightly larger text since we use 3 columns
                textName.textSize = 11f
                textName.maxLines = 2

                // Hide the status row for DB items
                textIconStatus?.parent?.let { parent ->
                    if (parent is View) parent.visibility = View.GONE
                }

                // Hide the action buttons row for DB items
                btnGenerateIcon?.parent?.let { parent ->
                    if (parent is View) parent.visibility = View.GONE
                }

                // Hide missing icon indicator
                view.findViewById<View>(R.id.iconMissingIcon)?.visibility = View.GONE

                // Load thumbnail from server
                if (game.iconUrl != null) {
                    imageView.setPadding(0, 0, 0, 0)
                    imageView.scaleType = android.widget.ImageView.ScaleType.CENTER_CROP
                    imageView.load(game.iconUrl) {
                        crossfade(true)
                        placeholder(R.drawable.ic_image_placeholder)
                        error(R.drawable.ic_image_placeholder)
                        memoryCachePolicy(CachePolicy.ENABLED)
                        diskCachePolicy(CachePolicy.ENABLED)
                    }
                } else {
                    imageView.setImageResource(R.drawable.ic_image_placeholder)
                    imageView.scaleType = android.widget.ImageView.ScaleType.CENTER_INSIDE
                    val paddingPx = (12 * view.context.resources.displayMetrics.density).toInt()
                    imageView.setPadding(paddingPx, paddingPx, paddingPx, paddingPx)
                }

                itemView.setOnClickListener { onGameClick(game) }
            }
        }
    }
}
