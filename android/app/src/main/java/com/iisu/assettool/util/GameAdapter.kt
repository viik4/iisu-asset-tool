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
import com.iisu.assettool.databinding.ItemGameBinding
import com.iisu.assettool.databinding.ItemGameGridBinding

/**
 * RecyclerView adapter for displaying games in a platform.
 * Shows game icon, name, asset status, and action buttons.
 * Supports both list and grid view modes.
 * Buttons are always enabled - tap to generate/replace artwork.
 */
class GameAdapter(
    private val onGenerateIcon: (GameInfo) -> Unit,
    private val onGenerateHero: ((GameInfo) -> Unit)? = null,
    private val onGenerateLogo: ((GameInfo) -> Unit)? = null,
    private val onLongPress: ((GameInfo, View) -> Unit)? = null  // Long-press callback for context menu with anchor view
) : ListAdapter<GameInfo, RecyclerView.ViewHolder>(GameDiffCallback()) {

    companion object {
        const val VIEW_TYPE_LIST = 0
        const val VIEW_TYPE_GRID = 1
    }

    var viewMode: Int = VIEW_TYPE_LIST
        set(value) {
            if (field != value) {
                field = value
                resetAnimations()
                notifyDataSetChanged()
            }
        }

    private var lastAnimatedPosition = -1

    // List view holder
    inner class ListViewHolder(
        private val binding: ItemGameBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(game: GameInfo) {
            // Set game name (use cleaned display name)
            binding.textGameName.text = game.displayName

            // Long-press callback for context menu - pass the view as anchor
            if (onLongPress != null) {
                binding.root.setOnLongClickListener { view ->
                    onLongPress.invoke(game, view)
                    true
                }
            } else {
                binding.root.setOnLongClickListener(null)
            }

            // Set game icon using Coil for async loading with crossfade
            if (game.hasIcon && game.iconFile != null) {
                binding.imageGameIcon.load(game.iconFile) {
                    crossfade(200)
                    placeholder(R.drawable.ic_missing_icon)
                    error(R.drawable.ic_missing_icon)
                }
            } else {
                binding.imageGameIcon.load(R.drawable.ic_missing_icon)
            }

            // Set icon status - differentiate between app-generated (PNG) and external (JPG)
            if (game.hasIcon) {
                if (game.iconGeneratedByApp) {
                    binding.textIconStatus.text = "Icon: ✓"  // App-generated
                    binding.textIconStatus.setTextColor(
                        binding.root.context.getColor(R.color.accent_cyan)
                    )
                } else {
                    binding.textIconStatus.text = "Icon: ext"  // External/pre-existing
                    binding.textIconStatus.setTextColor(
                        binding.root.context.getColor(R.color.iisu_purple)
                    )
                }
                binding.iconMissingIcon.visibility = View.GONE
            } else {
                binding.textIconStatus.text = "Icon: ✗"
                binding.textIconStatus.setTextColor(
                    binding.root.context.getColor(R.color.accent_magenta)
                )
                binding.iconMissingIcon.visibility = View.VISIBLE
            }

            // Configure icon button - always enabled, shows replace indicator if exists
            binding.btnGenerateIcon.apply {
                isEnabled = true
                alpha = 1.0f
                // Change tint to indicate replace vs generate
                setColorFilter(
                    binding.root.context.getColor(
                        if (game.hasIcon) R.color.iisu_purple else R.color.accent_cyan
                    )
                )
                contentDescription = if (game.hasIcon) "Replace Icon" else "Generate Icon"
                setOnClickListener {
                    onGenerateIcon(game)
                }
            }

            // Set hero status
            binding.textHeroStatus.apply {
                if (game.hasHero) {
                    if (game.heroGeneratedByApp) {
                        text = "Hero: ✓"
                        setTextColor(binding.root.context.getColor(R.color.accent_cyan))
                    } else {
                        text = "Hero: ext"
                        setTextColor(binding.root.context.getColor(R.color.iisu_purple))
                    }
                } else {
                    text = "Hero: ✗"
                    setTextColor(binding.root.context.getColor(R.color.accent_magenta))
                }
            }

            // Set logo status
            binding.textLogoStatus.apply {
                if (game.hasLogo) {
                    if (game.logoGeneratedByApp) {
                        text = "Logo: ✓"
                        setTextColor(binding.root.context.getColor(R.color.accent_cyan))
                    } else {
                        text = "Logo: ext"
                        setTextColor(binding.root.context.getColor(R.color.iisu_purple))
                    }
                } else {
                    text = "Logo: ✗"
                    setTextColor(binding.root.context.getColor(R.color.accent_magenta))
                }
            }

            // Configure hero button - always enabled if callback provided
            binding.btnGenerateHero.apply {
                if (onGenerateHero != null) {
                    visibility = View.VISIBLE
                    isEnabled = true
                    alpha = 1.0f
                    setColorFilter(
                        binding.root.context.getColor(
                            if (game.hasHero) R.color.iisu_purple else R.color.accent_cyan
                        )
                    )
                    contentDescription = if (game.hasHero) "Replace Hero" else "Generate Hero"
                    setOnClickListener { onGenerateHero.invoke(game) }
                } else {
                    visibility = View.GONE
                }
            }

            // Configure logo button - always enabled if callback provided
            binding.btnGenerateLogo.apply {
                if (onGenerateLogo != null) {
                    visibility = View.VISIBLE
                    isEnabled = true
                    alpha = 1.0f
                    setColorFilter(
                        binding.root.context.getColor(
                            if (game.hasLogo) R.color.iisu_purple else R.color.accent_magenta
                        )
                    )
                    contentDescription = if (game.hasLogo) "Replace Logo" else "Generate Logo"
                    setOnClickListener { onGenerateLogo.invoke(game) }
                } else {
                    visibility = View.GONE
                }
            }
        }
    }

    // Grid view holder
    inner class GridViewHolder(
        private val binding: ItemGameGridBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(game: GameInfo) {
            // Set game name (use cleaned display name)
            binding.textGameName.text = game.displayName

            // Long-press callback for context menu - pass the view as anchor
            if (onLongPress != null) {
                binding.root.setOnLongClickListener { view ->
                    onLongPress.invoke(game, view)
                    true
                }
            } else {
                binding.root.setOnLongClickListener(null)
            }

            // Make the icon container square based on its width
            binding.frameIcon.post {
                val width = binding.frameIcon.width
                if (width > 0) {
                    val params = binding.frameIcon.layoutParams
                    params.height = width
                    binding.frameIcon.layoutParams = params
                }
            }

            // Set game icon using Coil for async loading with crossfade
            if (game.hasIcon && game.iconFile != null) {
                binding.imageGameIcon.load(game.iconFile) {
                    crossfade(200)
                    placeholder(R.drawable.ic_missing_icon)
                    error(R.drawable.ic_missing_icon)
                }
            } else {
                binding.imageGameIcon.load(R.drawable.ic_missing_icon)
            }

            // Set compact status indicators (just symbols for grid view)
            // Icon status
            binding.textIconStatus.apply {
                text = if (game.hasIcon) "I" else "X"
                setTextColor(
                    binding.root.context.getColor(
                        when {
                            game.hasIcon && game.iconGeneratedByApp -> R.color.accent_cyan
                            game.hasIcon -> R.color.iisu_purple
                            else -> R.color.accent_magenta
                        }
                    )
                )
            }
            binding.iconMissingIcon.visibility = if (game.hasIcon) View.GONE else View.VISIBLE

            // Hero status
            binding.textHeroStatus.apply {
                text = if (game.hasHero) "H" else "X"
                setTextColor(
                    binding.root.context.getColor(
                        when {
                            game.hasHero && game.heroGeneratedByApp -> R.color.accent_cyan
                            game.hasHero -> R.color.iisu_purple
                            else -> R.color.accent_magenta
                        }
                    )
                )
            }

            // Logo status
            binding.textLogoStatus.apply {
                text = if (game.hasLogo) "L" else "X"
                setTextColor(
                    binding.root.context.getColor(
                        when {
                            game.hasLogo && game.logoGeneratedByApp -> R.color.accent_cyan
                            game.hasLogo -> R.color.iisu_purple
                            else -> R.color.accent_magenta
                        }
                    )
                )
            }

            // Configure icon button
            binding.btnGenerateIcon.apply {
                isEnabled = true
                alpha = 1.0f
                setColorFilter(
                    binding.root.context.getColor(
                        if (game.hasIcon) R.color.iisu_purple else R.color.accent_cyan
                    )
                )
                contentDescription = if (game.hasIcon) "Replace Icon" else "Generate Icon"
                setOnClickListener { onGenerateIcon(game) }
            }

            // Configure hero button
            binding.btnGenerateHero.apply {
                if (onGenerateHero != null) {
                    visibility = View.VISIBLE
                    isEnabled = true
                    alpha = 1.0f
                    setColorFilter(
                        binding.root.context.getColor(
                            if (game.hasHero) R.color.iisu_purple else R.color.accent_cyan
                        )
                    )
                    contentDescription = if (game.hasHero) "Replace Hero" else "Generate Hero"
                    setOnClickListener { onGenerateHero.invoke(game) }
                } else {
                    visibility = View.GONE
                }
            }

            // Configure logo button
            binding.btnGenerateLogo.apply {
                if (onGenerateLogo != null) {
                    visibility = View.VISIBLE
                    isEnabled = true
                    alpha = 1.0f
                    setColorFilter(
                        binding.root.context.getColor(
                            if (game.hasLogo) R.color.iisu_purple else R.color.accent_magenta
                        )
                    )
                    contentDescription = if (game.hasLogo) "Replace Logo" else "Generate Logo"
                    setOnClickListener { onGenerateLogo.invoke(game) }
                } else {
                    visibility = View.GONE
                }
            }
        }
    }

    override fun getItemViewType(position: Int): Int {
        return viewMode
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        return when (viewType) {
            VIEW_TYPE_GRID -> {
                val binding = ItemGameGridBinding.inflate(
                    LayoutInflater.from(parent.context),
                    parent,
                    false
                )
                GridViewHolder(binding)
            }
            else -> {
                val binding = ItemGameBinding.inflate(
                    LayoutInflater.from(parent.context),
                    parent,
                    false
                )
                ListViewHolder(binding)
            }
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        val game = getItem(position)
        when (holder) {
            is ListViewHolder -> holder.bind(game)
            is GridViewHolder -> holder.bind(game)
        }

        // Animate items as they appear (only animate new items scrolling in)
        if (position > lastAnimatedPosition) {
            val animation = AnimationUtils.loadAnimation(holder.itemView.context, R.anim.item_fade_in)
            holder.itemView.startAnimation(animation)
            lastAnimatedPosition = position
        }
    }

    override fun onViewDetachedFromWindow(holder: RecyclerView.ViewHolder) {
        super.onViewDetachedFromWindow(holder)
        holder.itemView.clearAnimation()
    }

    /**
     * Reset animation tracking when list is refreshed.
     */
    fun resetAnimations() {
        lastAnimatedPosition = -1
    }
}

class GameDiffCallback : DiffUtil.ItemCallback<GameInfo>() {
    override fun areItemsTheSame(oldItem: GameInfo, newItem: GameInfo): Boolean {
        return oldItem.folder.absolutePath == newItem.folder.absolutePath
    }

    override fun areContentsTheSame(oldItem: GameInfo, newItem: GameInfo): Boolean {
        return oldItem == newItem
    }
}
