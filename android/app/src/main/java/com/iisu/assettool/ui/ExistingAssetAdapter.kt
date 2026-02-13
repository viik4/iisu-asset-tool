package com.iisu.assettool.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AnimationUtils
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import coil.load
import com.iisu.assettool.R
import com.iisu.assettool.databinding.ItemExistingAssetBinding
import java.io.File

/**
 * Data class representing an existing asset (icon) in the output directory.
 */
data class ExistingAsset(
    val iconPath: File,
    val gameTitle: String,
    val platformKey: String,
    val platformDisplayName: String,
    var isSelected: Boolean = false,
    val isAndroidApp: Boolean = false,
    val packageName: String? = null
)

/**
 * Adapter for displaying existing assets in a grid layout.
 * Supports selection mode for batch re-scraping operations.
 */
class ExistingAssetAdapter(
    private val onAssetClick: (ExistingAsset) -> Unit,
    private val onAssetLongClick: (ExistingAsset) -> Unit,
    private val onSelectionChanged: (Int) -> Unit
) : ListAdapter<ExistingAsset, ExistingAssetAdapter.AssetViewHolder>(AssetDiffCallback()) {

    private val selectedItems = mutableSetOf<String>() // Using iconPath as key
    private var lastAnimatedPosition = -1

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): AssetViewHolder {
        val binding = ItemExistingAssetBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return AssetViewHolder(binding)
    }

    override fun onBindViewHolder(holder: AssetViewHolder, position: Int) {
        val asset = getItem(position)
        holder.bind(asset)

        // Animate items as they appear
        if (position > lastAnimatedPosition) {
            val animation = AnimationUtils.loadAnimation(holder.itemView.context, R.anim.item_fade_in)
            holder.itemView.startAnimation(animation)
            lastAnimatedPosition = position
        }
    }

    override fun onViewDetachedFromWindow(holder: AssetViewHolder) {
        super.onViewDetachedFromWindow(holder)
        holder.itemView.clearAnimation()
    }

    fun resetAnimations() {
        lastAnimatedPosition = -1
    }

    /**
     * Select all visible items.
     */
    fun selectAll() {
        val newList = currentList.map { asset ->
            selectedItems.add(asset.iconPath.absolutePath)
            asset.copy(isSelected = true)
        }
        submitList(newList)
        onSelectionChanged(selectedItems.size)
    }

    /**
     * Deselect all items.
     */
    fun selectNone() {
        selectedItems.clear()
        val newList = currentList.map { asset ->
            asset.copy(isSelected = false)
        }
        submitList(newList)
        onSelectionChanged(0)
    }

    /**
     * Get all selected assets.
     */
    fun getSelectedAssets(): List<ExistingAsset> {
        return currentList.filter { selectedItems.contains(it.iconPath.absolutePath) }
    }

    /**
     * Get count of selected items.
     */
    fun getSelectedCount(): Int = selectedItems.size

    /**
     * Toggle selection for an item.
     */
    private fun toggleSelection(asset: ExistingAsset, position: Int) {
        val key = asset.iconPath.absolutePath
        if (selectedItems.contains(key)) {
            selectedItems.remove(key)
        } else {
            selectedItems.add(key)
        }

        val newList = currentList.toMutableList()
        newList[position] = asset.copy(isSelected = selectedItems.contains(key))
        submitList(newList)
        onSelectionChanged(selectedItems.size)
    }

    inner class AssetViewHolder(
        private val binding: ItemExistingAssetBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(asset: ExistingAsset) {
            val context = binding.root.context

            // Load icon image using Coil for async loading with crossfade
            if (asset.iconPath.exists()) {
                binding.imageIcon.load(asset.iconPath) {
                    crossfade(200)
                    placeholder(R.drawable.ic_image_placeholder)
                    error(R.drawable.ic_image_placeholder)
                }
            } else {
                binding.imageIcon.load(R.drawable.ic_image_placeholder)
            }

            // Set game title
            binding.textGameTitle.text = asset.gameTitle

            // Set platform badge
            binding.textPlatform.text = asset.platformDisplayName

            // Update selection state
            val isSelected = selectedItems.contains(asset.iconPath.absolutePath)
            binding.iconSelected.visibility = if (isSelected) View.VISIBLE else View.GONE

            // Update card stroke color based on selection
            binding.cardAsset.strokeColor = if (isSelected) {
                ContextCompat.getColor(context, R.color.accent_cyan)
            } else {
                ContextCompat.getColor(context, R.color.theme_border_color)
            }
            binding.cardAsset.isChecked = isSelected

            // Click to toggle selection
            binding.root.setOnClickListener {
                val position = bindingAdapterPosition
                if (position != RecyclerView.NO_POSITION) {
                    toggleSelection(asset, position)
                    onAssetClick(asset)
                }
            }

            // Long click for re-scrape single item
            binding.root.setOnLongClickListener {
                onAssetLongClick(asset)
                true
            }
        }
    }

    class AssetDiffCallback : DiffUtil.ItemCallback<ExistingAsset>() {
        override fun areItemsTheSame(oldItem: ExistingAsset, newItem: ExistingAsset): Boolean {
            return oldItem.iconPath.absolutePath == newItem.iconPath.absolutePath
        }

        override fun areContentsTheSame(oldItem: ExistingAsset, newItem: ExistingAsset): Boolean {
            return oldItem == newItem
        }
    }
}
