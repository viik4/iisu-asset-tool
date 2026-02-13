package com.iisu.assettool.ui

import android.app.Dialog
import android.content.Context
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import androidx.recyclerview.widget.LinearLayoutManager
import com.iisu.assettool.data.GameSearchResult
import com.iisu.assettool.databinding.DialogGameSearchBinding
import com.iisu.assettool.util.ArtworkScraper
import com.iisu.assettool.util.GameInfo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Dialog for searching and selecting a game from SteamGridDB.
 * Used in the iiSU Browser to let users manually search for the correct game
 * when the folder name doesn't match the game title well.
 *
 * @param context The context
 * @param gameInfo The current game info (for pre-filling search)
 * @param artworkScraper The scraper instance (must have API key set)
 * @param onGameSelected Callback when user selects a game
 */
class GameSearchDialog(
    context: Context,
    private val gameInfo: GameInfo,
    private val artworkScraper: ArtworkScraper,
    private val onGameSelected: (GameSearchResult) -> Unit
) : Dialog(context) {

    private lateinit var binding: DialogGameSearchBinding
    private lateinit var adapter: GameSearchAdapter
    private var selectedGame: GameSearchResult? = null
    private val dialogScope = CoroutineScope(Dispatchers.Main + Job())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestWindowFeature(Window.FEATURE_NO_TITLE)

        binding = DialogGameSearchBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Set dialog to nearly fullscreen for better readability
        window?.setLayout(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )

        setupUI()
    }

    private fun setupUI() {
        // Set title
        binding.textTitle.text = "Search Game"
        binding.textSubtitle.text = "Search for \"${gameInfo.displayName}\" to get accurate artwork"

        // Pre-fill search with cleaned game name
        binding.editTextSearch.setText(gameInfo.searchName)

        // Setup adapter
        adapter = GameSearchAdapter { game ->
            selectedGame = game
            binding.btnSelect.isEnabled = true
        }

        binding.recyclerResults.apply {
            layoutManager = LinearLayoutManager(context)
            adapter = this@GameSearchDialog.adapter
        }

        // Search button
        binding.btnSearch.setOnClickListener {
            performSearch()
        }

        // Handle keyboard search action
        binding.editTextSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                performSearch()
                true
            } else {
                false
            }
        }

        // Cancel button
        binding.btnCancel.setOnClickListener {
            dismiss()
        }

        // Select button
        binding.btnSelect.setOnClickListener {
            selectedGame?.let { game ->
                onGameSelected(game)
                dismiss()
            }
        }
    }

    private fun performSearch() {
        val query = binding.editTextSearch.text.toString().trim()
        if (query.isEmpty()) return

        // Hide keyboard
        val imm = context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(binding.editTextSearch.windowToken, 0)

        // Check if this looks like a SteamGridDB ID or URL
        val isIdSearch = isLikelySteamGridDBId(query)

        // Show loading, hide results
        binding.progressBar.visibility = View.VISIBLE
        binding.recyclerResults.visibility = View.GONE
        binding.textResultsLabel.visibility = View.GONE
        binding.textNoResults.visibility = View.GONE
        binding.spacer.visibility = View.VISIBLE
        binding.btnSearch.isEnabled = false

        dialogScope.launch {
            try {
                val results = withContext(Dispatchers.IO) {
                    artworkScraper.searchGames(query)
                }

                binding.progressBar.visibility = View.GONE
                binding.btnSearch.isEnabled = true

                if (results.isNotEmpty()) {
                    adapter.submitList(results)
                    binding.recyclerResults.visibility = View.VISIBLE
                    binding.textResultsLabel.visibility = View.VISIBLE

                    // Show different label for ID search vs name search
                    binding.textResultsLabel.text = if (isIdSearch && results.size == 1) {
                        "Found Game by ID:"
                    } else {
                        "Search Results (${results.size}):"
                    }

                    binding.textNoResults.visibility = View.GONE
                    binding.spacer.visibility = View.GONE  // Hide spacer when results shown
                } else {
                    adapter.submitList(emptyList())
                    binding.recyclerResults.visibility = View.GONE
                    binding.textResultsLabel.visibility = View.GONE
                    binding.textNoResults.text = if (isIdSearch) {
                        "Game not found with that ID. Check the SteamGridDB URL/ID and try again."
                    } else {
                        "No games found. Try a different search term."
                    }
                    binding.textNoResults.visibility = View.VISIBLE
                    binding.spacer.visibility = View.VISIBLE  // Show spacer when no results
                }
            } catch (e: Exception) {
                binding.progressBar.visibility = View.GONE
                binding.btnSearch.isEnabled = true
                binding.textNoResults.text = "Search failed: ${e.message}"
                binding.textNoResults.visibility = View.VISIBLE
                binding.recyclerResults.visibility = View.GONE
                binding.textResultsLabel.visibility = View.GONE
                binding.spacer.visibility = View.VISIBLE  // Show spacer on error
            }
        }
    }

    /**
     * Check if the query looks like a SteamGridDB ID or URL
     */
    private fun isLikelySteamGridDBId(query: String): Boolean {
        val trimmed = query.trim()
        // Check if it's a number
        if (trimmed.toIntOrNull() != null) return true
        // Check if it contains steamgriddb
        if (trimmed.contains("steamgriddb", ignoreCase = true)) return true
        // Check for sgdb: shorthand
        if (trimmed.startsWith("sgdb:", ignoreCase = true)) return true
        return false
    }

    override fun dismiss() {
        dialogScope.cancel()
        super.dismiss()
    }

    companion object {
        /**
         * Show the game search dialog.
         * @param context The context
         * @param gameInfo The current game info
         * @param artworkScraper The scraper instance (must have API key set)
         * @param onGameSelected Callback when user selects a game
         */
        fun show(
            context: Context,
            gameInfo: GameInfo,
            artworkScraper: ArtworkScraper,
            onGameSelected: (GameSearchResult) -> Unit
        ): GameSearchDialog {
            val dialog = GameSearchDialog(context, gameInfo, artworkScraper, onGameSelected)
            dialog.show()
            return dialog
        }
    }
}
