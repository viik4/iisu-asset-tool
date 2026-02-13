package com.iisu.assettool.util

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AnimationUtils
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import coil.load
import com.iisu.assettool.R
import com.iisu.assettool.databinding.ItemAndroidAppBinding

/**
 * RecyclerView adapter for displaying Android apps in a grid.
 * Shows app icon, name, package name, and missing artwork badge.
 */
class AndroidAppAdapter(
    private val onAppClick: (AndroidAppInfo) -> Unit,
    private val onLongPress: ((AndroidAppInfo, View) -> Unit)? = null
) : ListAdapter<AndroidAppInfo, AndroidAppAdapter.AndroidAppViewHolder>(AndroidAppDiffCallback()) {

    private var lastAnimatedPosition = -1

    inner class AndroidAppViewHolder(
        private val binding: ItemAndroidAppBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(app: AndroidAppInfo) {
            // Set app icon using Coil for async loading with crossfade
            if (app.iconFile != null && app.iconFile.exists()) {
                binding.imageAppIcon.load(app.iconFile) {
                    crossfade(200)
                    placeholder(R.drawable.ic_android_app)
                    error(R.drawable.ic_android_app)
                }
            } else {
                binding.imageAppIcon.load(R.drawable.ic_android_app)
            }

            // Set app display name
            binding.textAppName.text = app.displayName

            // Set package name as subtitle
            binding.textPackageName.text = app.packageName

            // Show missing badge if there are missing assets
            val missingCount = app.missingCount
            if (missingCount > 0) {
                binding.textMissingBadge.visibility = View.VISIBLE
                binding.textMissingBadge.text = "$missingCount missing"
            } else {
                binding.textMissingBadge.visibility = View.GONE
            }

            // Click listener
            binding.root.setOnClickListener {
                onAppClick(app)
            }

            // Long-press callback for context menu
            if (onLongPress != null) {
                binding.root.setOnLongClickListener { view ->
                    onLongPress.invoke(app, view)
                    true
                }
            } else {
                binding.root.setOnLongClickListener(null)
            }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): AndroidAppViewHolder {
        val binding = ItemAndroidAppBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return AndroidAppViewHolder(binding)
    }

    override fun onBindViewHolder(holder: AndroidAppViewHolder, position: Int) {
        holder.bind(getItem(position))

        // Animate items as they appear
        if (position > lastAnimatedPosition) {
            val animation = AnimationUtils.loadAnimation(holder.itemView.context, R.anim.item_fade_in)
            holder.itemView.startAnimation(animation)
            lastAnimatedPosition = position
        }
    }

    override fun onViewDetachedFromWindow(holder: AndroidAppViewHolder) {
        super.onViewDetachedFromWindow(holder)
        holder.itemView.clearAnimation()
    }

    fun resetAnimations() {
        lastAnimatedPosition = -1
    }
}

class AndroidAppDiffCallback : DiffUtil.ItemCallback<AndroidAppInfo>() {
    override fun areItemsTheSame(oldItem: AndroidAppInfo, newItem: AndroidAppInfo): Boolean {
        return oldItem.packageName == newItem.packageName
    }

    override fun areContentsTheSame(oldItem: AndroidAppInfo, newItem: AndroidAppInfo): Boolean {
        return oldItem == newItem
    }
}
