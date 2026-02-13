package com.iisu.assettool.util

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.view.View
import android.view.ViewGroup
import android.view.animation.AnimationUtils
import android.view.animation.LayoutAnimationController
import androidx.recyclerview.widget.RecyclerView
import com.iisu.assettool.R

/**
 * Utility for smooth view animations across the app.
 * Replaces abrupt View.VISIBLE/View.GONE toggles with smooth fades.
 */
object ViewAnimationUtils {

    private const val FADE_DURATION = 200L
    private const val FADE_IN_DURATION = 250L

    /**
     * Fade a view in (from invisible to visible).
     */
    fun fadeIn(view: View, duration: Long = FADE_IN_DURATION) {
        if (view.visibility == View.VISIBLE && view.alpha == 1f) return
        view.alpha = 0f
        view.visibility = View.VISIBLE
        view.animate()
            .alpha(1f)
            .setDuration(duration)
            .setListener(null)
            .start()
    }

    /**
     * Fade a view out (from visible to gone).
     */
    fun fadeOut(view: View, duration: Long = FADE_DURATION, gone: Boolean = true) {
        if (view.visibility == View.GONE || view.visibility == View.INVISIBLE) return
        view.animate()
            .alpha(0f)
            .setDuration(duration)
            .setListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    view.visibility = if (gone) View.GONE else View.INVISIBLE
                    view.alpha = 1f // Reset for next time
                }
            })
            .start()
    }

    /**
     * Crossfade: fade out one view while fading in another.
     */
    fun crossfade(fadeOutView: View, fadeInView: View, duration: Long = FADE_IN_DURATION) {
        fadeIn(fadeInView, duration)
        fadeOut(fadeOutView, duration)
    }

    /**
     * Apply staggered layout animation to a RecyclerView.
     * Items will fade in sequentially when the list is populated.
     */
    fun applyLayoutAnimation(recyclerView: RecyclerView) {
        val context = recyclerView.context
        val animation = AnimationUtils.loadLayoutAnimation(context, R.anim.layout_animation_fall_down)
        recyclerView.layoutAnimation = animation
    }

    /**
     * Re-run layout animation on a RecyclerView (e.g., after data refresh).
     */
    fun runLayoutAnimation(recyclerView: RecyclerView) {
        val context = recyclerView.context
        val animation = AnimationUtils.loadLayoutAnimation(context, R.anim.layout_animation_fall_down)
        recyclerView.layoutAnimation = animation
        recyclerView.adapter?.notifyDataSetChanged()
        recyclerView.scheduleLayoutAnimation()
    }
}
