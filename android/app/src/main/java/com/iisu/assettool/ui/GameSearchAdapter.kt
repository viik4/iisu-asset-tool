package com.iisu.assettool.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.card.MaterialCardView
import com.iisu.assettool.R
import com.iisu.assettool.data.GameSearchResult

/**
 * Adapter for displaying game search results in a RecyclerView.
 * Shows game name and release year, allowing user to select which game they want artwork for.
 */
class GameSearchAdapter(
    private val onItemClick: (GameSearchResult) -> Unit
) : RecyclerView.Adapter<GameSearchAdapter.ViewHolder>() {

    private var games: List<GameSearchResult> = emptyList()
    private var selectedPosition: Int = -1

    fun submitList(newGames: List<GameSearchResult>) {
        games = newGames
        selectedPosition = -1
        notifyDataSetChanged()
    }

    fun getSelectedItem(): GameSearchResult? {
        return if (selectedPosition >= 0 && selectedPosition < games.size) {
            games[selectedPosition]
        } else null
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_game_search, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val game = games[position]
        holder.bind(game, position == selectedPosition)

        holder.itemView.setOnClickListener {
            val oldPosition = selectedPosition
            selectedPosition = holder.bindingAdapterPosition
            if (oldPosition >= 0) notifyItemChanged(oldPosition)
            notifyItemChanged(selectedPosition)
            onItemClick(game)
        }
    }

    override fun getItemCount(): Int = games.size

    class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val textGameName: TextView = itemView.findViewById(R.id.textGameName)
        private val textGameYear: TextView = itemView.findViewById(R.id.textGameYear)
        private val textGameTypes: TextView = itemView.findViewById(R.id.textGameTypes)

        fun bind(game: GameSearchResult, isSelected: Boolean) {
            textGameName.text = game.name
            textGameYear.text = game.releaseYear?.toString() ?: ""
            textGameYear.visibility = if (game.releaseYear != null) View.VISIBLE else View.GONE

            // Show game types (steam, origin, etc.)
            if (game.types.isNotEmpty()) {
                textGameTypes.text = game.types.joinToString(", ")
                textGameTypes.visibility = View.VISIBLE
            } else {
                textGameTypes.visibility = View.GONE
            }

            // Highlight selected item
            val cardView = itemView as? MaterialCardView
            if (isSelected) {
                cardView?.strokeWidth = itemView.resources.getDimensionPixelSize(R.dimen.card_stroke_selected)
                cardView?.strokeColor = itemView.resources.getColor(R.color.accent_cyan, null)
            } else {
                cardView?.strokeWidth = itemView.resources.getDimensionPixelSize(R.dimen.card_stroke_normal)
                cardView?.strokeColor = itemView.resources.getColor(R.color.theme_border_color, null)
            }
        }
    }
}
