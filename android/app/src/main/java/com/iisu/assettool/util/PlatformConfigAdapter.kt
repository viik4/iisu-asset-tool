package com.iisu.assettool.util

import android.graphics.BitmapFactory
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.iisu.assettool.R
import com.iisu.assettool.databinding.ItemPlatformConfigBinding

/**
 * Data class for platform configuration
 */
data class PlatformConfig(
    val id: String,           // Platform folder name (e.g., "psx", "snes")
    val displayName: String,  // User-friendly name (e.g., "PlayStation")
    val path: String,         // Custom path for ROMs
    val isCustom: Boolean = false  // Whether this is a user-added platform
)

/**
 * RecyclerView adapter for displaying editable platform configurations
 */
class PlatformConfigAdapter(
    private val onEditClick: (PlatformConfig) -> Unit,
    private val onDeleteClick: (PlatformConfig) -> Unit
) : ListAdapter<PlatformConfig, PlatformConfigAdapter.PlatformConfigViewHolder>(PlatformConfigDiffCallback()) {

    inner class PlatformConfigViewHolder(
        private val binding: ItemPlatformConfigBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(platform: PlatformConfig) {
            val context = binding.root.context

            // Load platform icon from assets
            val icon = PlatformAdapter.loadPlatformIconFromAssets(context, platform.id)
            if (icon != null) {
                binding.imagePlatformIcon.setImageBitmap(icon)
            } else {
                binding.imagePlatformIcon.setImageResource(R.drawable.ic_iisu_home)
            }

            // Set platform info
            binding.textPlatformName.text = platform.displayName
            binding.textPlatformPath.text = platform.path

            // Edit button
            binding.btnEditPlatform.setOnClickListener {
                onEditClick(platform)
            }

            // Delete button
            binding.btnDeletePlatform.setOnClickListener {
                onDeleteClick(platform)
            }

            // Row click also triggers edit
            binding.root.setOnClickListener {
                onEditClick(platform)
            }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): PlatformConfigViewHolder {
        val binding = ItemPlatformConfigBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return PlatformConfigViewHolder(binding)
    }

    override fun onBindViewHolder(holder: PlatformConfigViewHolder, position: Int) {
        holder.bind(getItem(position))
    }
}

class PlatformConfigDiffCallback : DiffUtil.ItemCallback<PlatformConfig>() {
    override fun areItemsTheSame(oldItem: PlatformConfig, newItem: PlatformConfig): Boolean {
        return oldItem.id == newItem.id
    }

    override fun areContentsTheSame(oldItem: PlatformConfig, newItem: PlatformConfig): Boolean {
        return oldItem == newItem
    }
}
