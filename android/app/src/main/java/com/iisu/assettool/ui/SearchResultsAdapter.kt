package com.iisu.assettool.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import coil.load
import coil.transform.RoundedCornersTransformation
import com.iisu.assettool.R
import com.iisu.assettool.data.ArtworkResult

/**
 * Adapter for displaying search results in a horizontal RecyclerView.
 * Each item shows a thumbnail of the artwork with the title below.
 */
class SearchResultsAdapter(
    private val onItemClick: (ArtworkResult) -> Unit
) : RecyclerView.Adapter<SearchResultsAdapter.ViewHolder>() {

    private var results: List<ArtworkResult> = emptyList()
    private var selectedPosition: Int = -1

    fun submitList(newResults: List<ArtworkResult>) {
        results = newResults
        selectedPosition = if (newResults.isNotEmpty()) 0 else -1
        notifyDataSetChanged()
    }

    fun getSelectedItem(): ArtworkResult? {
        return if (selectedPosition >= 0 && selectedPosition < results.size) {
            results[selectedPosition]
        } else null
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_search_result, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val result = results[position]
        holder.bind(result, position == selectedPosition)

        holder.itemView.setOnClickListener {
            val oldPosition = selectedPosition
            selectedPosition = holder.bindingAdapterPosition
            notifyItemChanged(oldPosition)
            notifyItemChanged(selectedPosition)
            onItemClick(result)
        }
    }

    override fun getItemCount(): Int = results.size

    class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val imageResult: ImageView = itemView.findViewById(R.id.imageResult)
        private val textResultTitle: TextView = itemView.findViewById(R.id.textResultTitle)

        fun bind(result: ArtworkResult, isSelected: Boolean) {
            // Load thumbnail with rounded corners
            imageResult.load(result.url) {
                crossfade(true)
                transformations(RoundedCornersTransformation(8f))
                placeholder(R.drawable.ic_image_placeholder)
                error(R.drawable.ic_image_placeholder)
            }

            // Show title with source
            textResultTitle.text = result.source

            // Highlight selected item
            val cardView = itemView as? com.google.android.material.card.MaterialCardView
            if (isSelected) {
                cardView?.strokeWidth = itemView.resources.getDimensionPixelSize(R.dimen.card_stroke_selected)
                cardView?.strokeColor = itemView.resources.getColor(R.color.theme_accent, null)
            } else {
                cardView?.strokeWidth = itemView.resources.getDimensionPixelSize(R.dimen.card_stroke_normal)
                cardView?.strokeColor = itemView.resources.getColor(R.color.theme_border_color, null)
            }
        }
    }
}
