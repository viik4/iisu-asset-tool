package com.iisu.assettool.ui

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.max

/**
 * Custom view for previewing hero image crop position.
 * Displays the full source image with a 16:9 crop window overlay that
 * the user can slide horizontally via [position] (controlled by an external slider)
 * or by dragging directly on the view.
 *
 * The image is scaled so its full height fits the view. If the image is wider
 * than 16:9, the crop window is narrower than the image and can slide left/right.
 */
class HeroCropPreviewView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var sourceBitmap: Bitmap? = null

    /** Horizontal crop position: 0.0 = left edge, 0.5 = center, 1.0 = right edge */
    var position: Float = 0.5f
        set(value) {
            field = value.coerceIn(0f, 1f)
            invalidate()
        }

    /** Callback when position changes from touch dragging */
    var onPositionChanged: ((Float) -> Unit)? = null

    // Paints
    private val imagePaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    private val overlayPaint = Paint().apply {
        color = Color.parseColor("#AA000000")
        style = Paint.Style.FILL
    }
    private val cropBorderPaint = Paint().apply {
        color = Color.parseColor("#00D4FF")
        style = Paint.Style.STROKE
        strokeWidth = 3f
    }

    // Touch tracking
    private var lastTouchX = 0f
    private var isDragging = false
    private var maxSlideRange = 0f // pixels of horizontal travel available

    // Computed rects
    private val imageRect = RectF()
    private val cropRect = RectF()

    fun setImage(bitmap: Bitmap) {
        sourceBitmap = bitmap
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val bitmap = sourceBitmap ?: return
        if (width <= 0 || height <= 0) return

        val srcW = bitmap.width.toFloat()
        val srcH = bitmap.height.toFloat()
        if (srcW <= 0 || srcH <= 0) return

        val viewW = width.toFloat()
        val viewH = height.toFloat()

        // Scale the image so its full height fits the view height
        val displayScale = viewH / srcH
        val displayW = srcW * displayScale
        val displayH = viewH

        // Center the image horizontally
        val imageLeft = (viewW - displayW) / 2f
        imageRect.set(imageLeft, 0f, imageLeft + displayW, displayH)

        // Draw the full source image
        canvas.drawBitmap(bitmap, null, imageRect, imagePaint)

        // Calculate the 16:9 crop window
        val targetAspect = 1920f / 1080f
        val srcAspect = srcW / srcH

        if (srcAspect > targetAspect) {
            // Source is wider than 16:9 — crop window slides horizontally
            val cropWindowW = displayH * targetAspect
            maxSlideRange = displayW - cropWindowW
            val cropLeft = imageLeft + maxSlideRange * position

            cropRect.set(cropLeft, 0f, cropLeft + cropWindowW, displayH)
        } else {
            // Source is 16:9 or narrower — crop window fills the image, no movement
            maxSlideRange = 0f
            cropRect.set(imageLeft, 0f, imageLeft + displayW, displayH)
        }

        // Draw darkened overlay outside the crop window (full view width)
        // Left side
        canvas.drawRect(0f, 0f, cropRect.left, viewH, overlayPaint)
        // Right side
        canvas.drawRect(cropRect.right, 0f, viewW, viewH, overlayPaint)

        // Draw crop border
        canvas.drawRect(cropRect, cropBorderPaint)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (maxSlideRange <= 0) return super.onTouchEvent(event)

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastTouchX = event.x
                isDragging = true
                parent?.requestDisallowInterceptTouchEvent(true)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (isDragging) {
                    val dx = event.x - lastTouchX
                    lastTouchX = event.x

                    // Convert pixel delta to position delta
                    val positionDelta = dx / maxSlideRange
                    position += positionDelta
                    onPositionChanged?.invoke(position)
                }
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                isDragging = false
                parent?.requestDisallowInterceptTouchEvent(false)
                return true
            }
        }
        return super.onTouchEvent(event)
    }
}
