package com.iisu.assettool.util

import android.annotation.SuppressLint
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.RecyclerView
import com.iisu.assettool.R
import java.util.Collections

/**
 * Data class representing an artwork source with its priority and enabled state.
 */
data class ArtworkSource(
    val id: String,
    val displayName: String,
    var enabled: Boolean = true,
    val description: String = ""
) {
    companion object {
        // Default sources in priority order
        fun getDefaultSources(): List<ArtworkSource> = listOf(
            ArtworkSource(
                id = "steamgriddb",
                displayName = "SteamGridDB",
                enabled = true,
                description = "Best for icons, heroes, and logos"
            ),
            ArtworkSource(
                id = "libretro",
                displayName = "Libretro Thumbnails",
                enabled = true,
                description = "Large collection of boxart"
            ),
            ArtworkSource(
                id = "thegamesdb",
                displayName = "TheGamesDB",
                enabled = true,
                description = "Community-driven game database"
            ),
            ArtworkSource(
                id = "igdb",
                displayName = "IGDB",
                enabled = false,
                description = "Requires API key setup"
            )
        )
    }
}

/**
 * RecyclerView adapter for managing artwork source priority with drag-and-drop reordering.
 * Supports enabling/disabling individual sources and drag handle for reordering.
 */
class SourcePriorityAdapter(
    private val onOrderChanged: (List<ArtworkSource>) -> Unit
) : RecyclerView.Adapter<SourcePriorityAdapter.SourceViewHolder>() {

    private val sources = mutableListOf<ArtworkSource>()
    private var itemTouchHelper: ItemTouchHelper? = null

    fun attachToRecyclerView(recyclerView: RecyclerView) {
        val callback = SourceItemTouchHelperCallback()
        itemTouchHelper = ItemTouchHelper(callback)
        itemTouchHelper?.attachToRecyclerView(recyclerView)
    }

    fun setSources(newSources: List<ArtworkSource>) {
        sources.clear()
        sources.addAll(newSources)
        notifyDataSetChanged()
    }

    fun getSources(): List<ArtworkSource> = sources.toList()

    fun getEnabledSources(): List<ArtworkSource> = sources.filter { it.enabled }

    fun getSourceOrder(): List<Map<String, Any>> {
        return sources.map { source ->
            mapOf(
                "id" to source.id,
                "enabled" to source.enabled
            )
        }
    }

    fun enableAll() {
        sources.forEach { it.enabled = true }
        notifyDataSetChanged()
        onOrderChanged(sources.toList())
    }

    fun disableAll() {
        sources.forEach { it.enabled = false }
        notifyDataSetChanged()
        onOrderChanged(sources.toList())
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): SourceViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_source_priority, parent, false)
        return SourceViewHolder(view)
    }

    override fun onBindViewHolder(holder: SourceViewHolder, position: Int) {
        holder.bind(sources[position])
    }

    override fun getItemCount(): Int = sources.size

    private fun moveItem(fromPosition: Int, toPosition: Int) {
        if (fromPosition < toPosition) {
            for (i in fromPosition until toPosition) {
                Collections.swap(sources, i, i + 1)
            }
        } else {
            for (i in fromPosition downTo toPosition + 1) {
                Collections.swap(sources, i, i - 1)
            }
        }
        notifyItemMoved(fromPosition, toPosition)
    }

    private fun onItemMoveComplete() {
        onOrderChanged(sources.toList())
    }

    inner class SourceViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val checkEnabled: CheckBox = itemView.findViewById(R.id.checkSourceEnabled)
        private val textName: TextView = itemView.findViewById(R.id.textSourceName)
        private val textDescription: TextView = itemView.findViewById(R.id.textSourceDescription)
        private val dragHandle: ImageView = itemView.findViewById(R.id.imageDragHandle)

        @SuppressLint("ClickableViewAccessibility")
        fun bind(source: ArtworkSource) {
            textName.text = source.displayName
            textDescription.text = source.description

            // Set checkbox without triggering listener
            checkEnabled.setOnCheckedChangeListener(null)
            checkEnabled.isChecked = source.enabled

            checkEnabled.setOnCheckedChangeListener { _, isChecked ->
                source.enabled = isChecked
                onOrderChanged(sources.toList())
            }

            // Drag handle touch listener
            dragHandle.setOnTouchListener { _, event ->
                if (event.actionMasked == MotionEvent.ACTION_DOWN) {
                    itemTouchHelper?.startDrag(this)
                }
                false
            }

            // Visual feedback for enabled/disabled state
            itemView.alpha = if (source.enabled) 1.0f else 0.6f
        }
    }

    inner class SourceItemTouchHelperCallback : ItemTouchHelper.Callback() {

        override fun getMovementFlags(
            recyclerView: RecyclerView,
            viewHolder: RecyclerView.ViewHolder
        ): Int {
            val dragFlags = ItemTouchHelper.UP or ItemTouchHelper.DOWN
            return makeMovementFlags(dragFlags, 0)
        }

        override fun onMove(
            recyclerView: RecyclerView,
            viewHolder: RecyclerView.ViewHolder,
            target: RecyclerView.ViewHolder
        ): Boolean {
            moveItem(viewHolder.bindingAdapterPosition, target.bindingAdapterPosition)
            return true
        }

        override fun onSwiped(viewHolder: RecyclerView.ViewHolder, direction: Int) {
            // Not used - no swipe functionality
        }

        override fun clearView(recyclerView: RecyclerView, viewHolder: RecyclerView.ViewHolder) {
            super.clearView(recyclerView, viewHolder)
            onItemMoveComplete()
        }

        override fun isLongPressDragEnabled(): Boolean = false // Use drag handle instead
    }
}
