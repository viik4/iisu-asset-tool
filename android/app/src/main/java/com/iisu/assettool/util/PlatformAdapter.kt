package com.iisu.assettool.util

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AnimationUtils
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.iisu.assettool.R
import com.iisu.assettool.databinding.ItemPlatformBinding
import com.iisu.assettool.ui.PlatformInfo

/**
 * RecyclerView adapter for displaying iiSU platforms in a grid.
 * Shows platform icon, name, ROM count, and missing artwork badge.
 */
class PlatformAdapter(
    private val onPlatformClick: (PlatformInfo) -> Unit
) : ListAdapter<PlatformInfo, PlatformAdapter.PlatformViewHolder>(PlatformDiffCallback()) {

    companion object {
        private const val TAG = "PlatformAdapter"

        // In-memory cache for platform icons loaded from assets
        private val iconCache = mutableMapOf<String, Bitmap?>()

        // Map platform names to asset filenames
        private val platformIconMap = mapOf(
            "nes" to "NES.png",
            "snes" to "SNES.png",
            "sfc" to "SNES.png",
            "n64" to "N64.png",
            "gc" to "GAMECUBE.png",
            "gamecube" to "GAMECUBE.png",
            "wii" to "Wii.png",
            "wiiu" to "Wii_U.png",
            "switch" to "Switch.png",
            "gb" to "Game_Boy.png",
            "gbc" to "Game_Boy_Color.png",
            "gba" to "Game_Boy_Advance.png",
            "nds" to "NINTENDO_DS.png",
            "3ds" to "NINTENDO_3DS.png",
            "n3ds" to "NINTENDO_3DS.png",
            "psx" to "PS1.png",
            "ps1" to "PS1.png",
            "ps2" to "PS2.png",
            "ps3" to "PS3.png",
            "ps4" to "PS4.png",
            "psp" to "PSP.png",
            "psvita" to "PS_VITA.png",
            "vita" to "PS_VITA.png",
            "genesis" to "GENESIS.png",
            "megadrive" to "GENESIS.png",
            "saturn" to "SATURN.png",
            "dreamcast" to "Dreamcast.png",
            "gamegear" to "GAME_GEAR.png",
            "gg" to "GAME_GEAR.png",
            "xbox" to "Xbox.png",
            "xbox360" to "Xbox_360.png",
            "android" to "Android.png",
            "ngpc" to "Neo_Geo_Pocket_Color.png",
            "eshop" to "eshop.png"
        )

        /**
         * Load a platform icon from the app's assets folder (with in-memory cache).
         */
        fun loadPlatformIconFromAssets(context: Context, platformName: String): Bitmap? {
            val normalizedName = platformName.lowercase().replace(" ", "").replace("-", "").replace("_", "")

            // Check cache first
            if (iconCache.containsKey(normalizedName)) {
                return iconCache[normalizedName]
            }

            val assetFileName = platformIconMap[normalizedName]
                ?: platformIconMap.entries.find { normalizedName.contains(it.key) }?.value

            val bitmap = if (assetFileName != null) {
                try {
                    context.assets.open("platform_icons/$assetFileName").use { inputStream ->
                        BitmapFactory.decodeStream(inputStream)
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to load platform icon from assets: $assetFileName", e)
                    null
                }
            } else {
                null
            }

            // Cache the result (even null to avoid repeated file I/O)
            iconCache[normalizedName] = bitmap
            return bitmap
        }
    }

    private var lastAnimatedPosition = -1

    inner class PlatformViewHolder(
        private val binding: ItemPlatformBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(platform: PlatformInfo) {
            val context = binding.root.context

            // Check if this is the special Android Apps platform
            if (platform.name == "__android_apps__") {
                binding.imagePlatformIcon.setImageResource(R.drawable.ic_android_app)
                binding.imagePlatformIcon.setColorFilter(
                    context.getColor(R.color.accent_cyan),
                    android.graphics.PorterDuff.Mode.SRC_IN
                )
            } else if (platform.icon != null) {
                // Clear any color filter
                binding.imagePlatformIcon.clearColorFilter()
                binding.imagePlatformIcon.setImageBitmap(platform.icon)
            } else {
                // Clear any color filter
                binding.imagePlatformIcon.clearColorFilter()
                // Try to load from assets (cached)
                val assetIcon = loadPlatformIconFromAssets(context, platform.name)
                if (assetIcon != null) {
                    binding.imagePlatformIcon.setImageBitmap(assetIcon)
                } else {
                    binding.imagePlatformIcon.setImageResource(R.drawable.ic_iisu_home)
                }
            }

            // Set platform name
            binding.textPlatformName.text = platform.displayName

            // Set game/app count (use "apps" for Android Apps platform)
            val countLabel = if (platform.name == "__android_apps__") "apps" else "games"
            binding.textRomCount.text = "${platform.gameCount} $countLabel"

            // Show missing badge if there are missing assets
            val totalMissing = platform.missingIcons + platform.missingHeroes + platform.missingLogos
            if (totalMissing > 0) {
                binding.textMissingBadge.visibility = View.VISIBLE
                binding.textMissingBadge.text = "$totalMissing missing"
            } else {
                binding.textMissingBadge.visibility = View.GONE
            }

            // Click listener
            binding.root.setOnClickListener {
                onPlatformClick(platform)
            }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): PlatformViewHolder {
        val binding = ItemPlatformBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return PlatformViewHolder(binding)
    }

    override fun onBindViewHolder(holder: PlatformViewHolder, position: Int) {
        holder.bind(getItem(position))

        // Animate items as they appear
        if (position > lastAnimatedPosition) {
            val animation = AnimationUtils.loadAnimation(holder.itemView.context, R.anim.item_fade_in)
            holder.itemView.startAnimation(animation)
            lastAnimatedPosition = position
        }
    }

    override fun onViewDetachedFromWindow(holder: PlatformViewHolder) {
        super.onViewDetachedFromWindow(holder)
        holder.itemView.clearAnimation()
    }

    fun resetAnimations() {
        lastAnimatedPosition = -1
    }
}

class PlatformDiffCallback : DiffUtil.ItemCallback<PlatformInfo>() {
    override fun areItemsTheSame(oldItem: PlatformInfo, newItem: PlatformInfo): Boolean {
        return oldItem.name == newItem.name
    }

    override fun areContentsTheSame(oldItem: PlatformInfo, newItem: PlatformInfo): Boolean {
        return oldItem == newItem
    }
}
