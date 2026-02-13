package com.iisu.assettool.ui

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import kotlin.math.max
import kotlin.math.min

/**
 * Custom view for cropping images to a square.
 * Supports touch-based panning and pinch-to-zoom.
 * Shows a square crop overlay and renders the final result to 1024x1024.
 */
class CropImageView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    companion object {
        private const val OUTPUT_SIZE = 1024
        private const val MIN_SCALE = 0.1f
        private const val MAX_SCALE = 5f  // Match slider max value
    }

    // Source image
    private var sourceBitmap: Bitmap? = null
    private var imageWidth = 0
    private var imageHeight = 0

    // Flag to suppress transform callbacks during initialization
    private var suppressCallbacks = false

    // Transform state
    var scale = 1f
        set(value) {
            field = value.coerceIn(MIN_SCALE, MAX_SCALE)
            invalidate()
            if (!suppressCallbacks) {
                onTransformChanged?.invoke()
            }
        }

    var imageRotation = 0f
        set(value) {
            // Normalize rotation to -180..180 range
            var normalized = value
            while (normalized > 180f) normalized -= 360f
            while (normalized < -180f) normalized += 360f
            field = normalized
            invalidate()
            if (!suppressCallbacks) {
                onTransformChanged?.invoke()
            }
        }

    var offsetX = 0f
        private set
    var offsetY = 0f
        private set

    // Callback for transform changes
    var onTransformChanged: (() -> Unit)? = null

    // Drawing
    private val imagePaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    private val overlayPaint = Paint().apply {
        color = Color.parseColor("#80000000")  // Semi-transparent black
        style = Paint.Style.FILL
    }
    private val cropBorderPaint = Paint().apply {
        color = Color.parseColor("#00D4FF")  // Cyan accent
        style = Paint.Style.STROKE
        strokeWidth = 3f
    }
    private val gridPaint = Paint().apply {
        color = Color.parseColor("#40FFFFFF")  // Light grid lines
        style = Paint.Style.STROKE
        strokeWidth = 1f
    }

    // Crop area (square, centered)
    private var cropRect = RectF()
    private var cropSize = 0f

    // Touch handling
    private var lastTouchX = 0f
    private var lastTouchY = 0f
    private var isDragging = false

    private val scaleGestureDetector = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(detector: ScaleGestureDetector): Boolean {
            scale *= detector.scaleFactor
            return true
        }
    })

    fun setImage(bitmap: Bitmap) {
        sourceBitmap = bitmap
        imageWidth = bitmap.width
        imageHeight = bitmap.height

        // Suppress callbacks during initial setup to avoid slider update issues
        suppressCallbacks = true
        try {
            // Initialize scale to a safe default if cropSize isn't set yet
            if (cropSize <= 0) {
                // Use image dimensions to set an initial scale
                scale = 1f
            } else {
                resetTransformInternal()
            }
        } finally {
            suppressCallbacks = false
        }
        invalidate()
        // Now fire the callback once with the final values
        onTransformChanged?.invoke()
    }

    fun resetTransform() {
        resetTransformInternal()
        onTransformChanged?.invoke()
    }

    /**
     * Internal reset without firing the callback - used during initialization
     */
    private fun resetTransformInternal() {
        // Ensure callbacks are suppressed during entire reset
        val wasSuppressed = suppressCallbacks
        suppressCallbacks = true
        try {
            // Calculate scale to fit the image in the crop area (fill mode)
            calculateFillScale()
            // Reset rotation
            imageRotation = 0f
            offsetX = 0f
            offsetY = 0f
            invalidate()
        } finally {
            suppressCallbacks = wasSuppressed
        }
    }

    fun fitToSquare() {
        // Scale so the entire image fits within the crop square
        if (sourceBitmap == null || cropSize <= 0) return

        val rotatedSize = getRotatedImageSize()
        // Prevent division by zero
        if (rotatedSize.first <= 0 || rotatedSize.second <= 0) return

        scale = min(cropSize / rotatedSize.first, cropSize / rotatedSize.second)
        offsetX = 0f
        offsetY = 0f
        invalidate()
        onTransformChanged?.invoke()
    }

    fun fillSquare() {
        // Scale so the image completely fills the crop square
        calculateFillScale()
        offsetX = 0f
        offsetY = 0f
        invalidate()
        onTransformChanged?.invoke()
    }

    private fun calculateFillScale() {
        if (sourceBitmap == null || cropSize <= 0) return

        val rotatedSize = getRotatedImageSize()
        // Prevent division by zero
        if (rotatedSize.first <= 0 || rotatedSize.second <= 0) return

        scale = max(cropSize / rotatedSize.first, cropSize / rotatedSize.second)
    }

    private fun getRotatedImageSize(): Pair<Float, Float> {
        val bitmap = sourceBitmap ?: return Pair(1f, 1f)

        // Calculate the bounding box of the rotated image
        val radians = Math.toRadians(imageRotation.toDouble())
        val cos = Math.abs(Math.cos(radians))
        val sin = Math.abs(Math.sin(radians))

        val rotatedWidth = (bitmap.width * cos + bitmap.height * sin).toFloat()
        val rotatedHeight = (bitmap.width * sin + bitmap.height * cos).toFloat()

        return Pair(rotatedWidth, rotatedHeight)
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)

        // Ensure we have valid dimensions
        if (w <= 0 || h <= 0) return

        // Calculate crop area (centered square)
        val padding = 32f
        cropSize = max(1f, min(w - padding * 2, h - padding * 2))

        val left = (w - cropSize) / 2
        val top = (h - cropSize) / 2
        cropRect.set(left, top, left + cropSize, top + cropSize)

        // Recalculate scale if we have an image
        // Use internal reset to avoid callback during layout
        if (sourceBitmap != null) {
            suppressCallbacks = true
            try {
                resetTransformInternal()
            } finally {
                suppressCallbacks = false
            }
            // Fire callback once after layout is complete
            post { onTransformChanged?.invoke() }
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val bitmap = sourceBitmap ?: return

        // Draw the transformed image
        canvas.save()

        // Move to crop center
        val centerX = cropRect.centerX()
        val centerY = cropRect.centerY()
        canvas.translate(centerX + offsetX, centerY + offsetY)

        // Apply rotation
        canvas.rotate(imageRotation)

        // Apply scale and draw centered
        val scaledWidth = bitmap.width * scale
        val scaledHeight = bitmap.height * scale
        val destRect = RectF(
            -scaledWidth / 2,
            -scaledHeight / 2,
            scaledWidth / 2,
            scaledHeight / 2
        )
        canvas.drawBitmap(bitmap, null, destRect, imagePaint)

        canvas.restore()

        // Draw dark overlay outside crop area
        // Top
        canvas.drawRect(0f, 0f, width.toFloat(), cropRect.top, overlayPaint)
        // Bottom
        canvas.drawRect(0f, cropRect.bottom, width.toFloat(), height.toFloat(), overlayPaint)
        // Left
        canvas.drawRect(0f, cropRect.top, cropRect.left, cropRect.bottom, overlayPaint)
        // Right
        canvas.drawRect(cropRect.right, cropRect.top, width.toFloat(), cropRect.bottom, overlayPaint)

        // Draw crop border
        canvas.drawRect(cropRect, cropBorderPaint)

        // Draw rule of thirds grid
        val thirdW = cropSize / 3
        val thirdH = cropSize / 3
        canvas.drawLine(cropRect.left + thirdW, cropRect.top, cropRect.left + thirdW, cropRect.bottom, gridPaint)
        canvas.drawLine(cropRect.left + thirdW * 2, cropRect.top, cropRect.left + thirdW * 2, cropRect.bottom, gridPaint)
        canvas.drawLine(cropRect.left, cropRect.top + thirdH, cropRect.right, cropRect.top + thirdH, gridPaint)
        canvas.drawLine(cropRect.left, cropRect.top + thirdH * 2, cropRect.right, cropRect.top + thirdH * 2, gridPaint)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        scaleGestureDetector.onTouchEvent(event)

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastTouchX = event.x
                lastTouchY = event.y
                isDragging = true
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (isDragging && event.pointerCount == 1) {
                    val dx = event.x - lastTouchX
                    val dy = event.y - lastTouchY

                    offsetX += dx
                    offsetY += dy

                    lastTouchX = event.x
                    lastTouchY = event.y

                    invalidate()
                    onTransformChanged?.invoke()
                }
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                isDragging = false
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    /**
     * Render the cropped image to a 1024x1024 bitmap
     */
    fun getCroppedBitmap(): Bitmap? {
        val bitmap = sourceBitmap ?: return null

        // Prevent division by zero - cropSize must be positive
        if (cropSize <= 0) {
            // Use a fallback crop size based on image dimensions
            val fallbackCropSize = min(bitmap.width, bitmap.height).toFloat()
            if (fallbackCropSize <= 0) return null

            return getCroppedBitmapWithCropSize(bitmap, fallbackCropSize)
        }

        return getCroppedBitmapWithCropSize(bitmap, cropSize)
    }

    private fun getCroppedBitmapWithCropSize(bitmap: Bitmap, useCropSize: Float): Bitmap? {
        // Create output bitmap
        val output = Bitmap.createBitmap(OUTPUT_SIZE, OUTPUT_SIZE, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(output)

        // Fill with transparent
        canvas.drawColor(Color.TRANSPARENT)

        // Calculate the scale factor from view crop to output
        val outputScale = OUTPUT_SIZE / useCropSize

        // Apply transforms relative to center
        canvas.translate(OUTPUT_SIZE / 2f, OUTPUT_SIZE / 2f)
        canvas.translate(offsetX * outputScale, offsetY * outputScale)
        canvas.rotate(imageRotation)

        // Scale for output resolution
        val finalScale = scale * outputScale
        val scaledWidth = bitmap.width * finalScale
        val scaledHeight = bitmap.height * finalScale

        val destRect = RectF(
            -scaledWidth / 2,
            -scaledHeight / 2,
            scaledWidth / 2,
            scaledHeight / 2
        )

        val highQualityPaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG).apply {
            isFilterBitmap = true
        }
        canvas.drawBitmap(bitmap, null, destRect, highQualityPaint)

        return output
    }
}
