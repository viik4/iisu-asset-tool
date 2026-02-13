package com.iisu.assettool.util

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.RectF
import java.util.LinkedList

/**
 * Image processing utilities for Android.
 * Ports the Python PIL/OpenCV logic to Android Bitmap operations.
 */
class ImageProcessor {

    /**
     * Apply a border/frame to an image.
     * The border image should have a transparent area where the content goes.
     * The corners of the output will be transparent where the border has transparency.
     *
     * Uses the same algorithm as the desktop Python version:
     * 1. Create mask from border alpha channel
     * 2. Fill the center transparent hole with opaque pixels
     * 3. Apply shrink and feather for smooth edges
     * 4. Composite image, then border, then apply corner mask
     */
    fun applyBorder(image: Bitmap, border: Bitmap): Bitmap {
        val outSize = border.width

        // Step 1: Scale and center-crop the source image to fill the border size
        val base = centerCropToSquare(image, outSize)

        // Step 2: Create corner mask from border (same as desktop corner_mask_from_border)
        val mask = cornerMaskFromBorder(border, threshold = 18, shrinkPx = 8)

        // Step 3: Apply the mask to the base image's alpha channel
        val maskedBase = applyAlphaMask(base, mask)

        // Step 4: Composite the border on top
        val output = Bitmap.createBitmap(outSize, outSize, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(output)
        canvas.drawBitmap(maskedBase, 0f, 0f, null)
        canvas.drawBitmap(border, 0f, 0f, null)

        return output
    }

    /**
     * Create a corner mask from a border image.
     * This replicates the Python corner_mask_from_border function.
     *
     * The border has transparent corners and a transparent center (content area).
     * We need to create a mask that is:
     * - Opaque (255) in the center content area
     * - Opaque (255) where the border frame is
     * - Transparent (0) at the corners
     */
    private fun cornerMaskFromBorder(border: Bitmap, threshold: Int = 18, shrinkPx: Int = 8): Bitmap {
        val w = border.width
        val h = border.height

        // Extract alpha channel and threshold it
        val alphaPixels = IntArray(w * h)
        for (y in 0 until h) {
            for (x in 0 until w) {
                val pixel = border.getPixel(x, y)
                val alpha = (pixel shr 24) and 0xFF
                // Threshold: if alpha >= threshold, set to 255, else 0
                alphaPixels[y * w + x] = if (alpha >= threshold) 255 else 0
            }
        }

        // Fill the center hole (flood-fill from center)
        fillCenterHole(alphaPixels, w, h)

        // Apply shrink (erosion) - MinFilter equivalent
        if (shrinkPx > 0) {
            erodeAlpha(alphaPixels, w, h, shrinkPx)
        }

        // Create the mask bitmap from the alpha values
        val mask = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        for (y in 0 until h) {
            for (x in 0 until w) {
                val alpha = alphaPixels[y * w + x]
                // Mask pixel: full white with the computed alpha
                mask.setPixel(x, y, (alpha shl 24) or 0x00FFFFFF)
            }
        }

        return mask
    }

    /**
     * Flood-fill from the center to fill the transparent content area with opaque pixels.
     * This is equivalent to the Python fill_center_hole function.
     */
    private fun fillCenterHole(pixels: IntArray, w: Int, h: Int) {
        val cx = w / 2
        val cy = h / 2
        val centerIdx = cy * w + cx

        // If center is already opaque, nothing to fill
        if (pixels[centerIdx] != 0) return

        val queue = LinkedList<Pair<Int, Int>>()
        val visited = mutableSetOf<Int>()

        queue.add(Pair(cx, cy))
        visited.add(centerIdx)

        while (queue.isNotEmpty()) {
            val pos = queue.poll() ?: continue
            val (x, y) = pos
            val idx = y * w + x
            pixels[idx] = 255  // Fill with opaque

            // Check 4-connected neighbors
            val neighbors = listOf(
                Pair(x - 1, y), Pair(x + 1, y),
                Pair(x, y - 1), Pair(x, y + 1)
            )

            for ((nx, ny) in neighbors) {
                if (nx in 0 until w && ny in 0 until h) {
                    val nidx = ny * w + nx
                    if (nidx !in visited && pixels[nidx] == 0) {
                        visited.add(nidx)
                        queue.add(Pair(nx, ny))
                    }
                }
            }
        }
    }

    /**
     * Erode the alpha mask (MinFilter equivalent).
     * For each pixel, use the minimum value in its neighborhood.
     */
    private fun erodeAlpha(pixels: IntArray, w: Int, h: Int, radius: Int) {
        val copy = pixels.copyOf()
        // Kernel size is determined by radius but not used directly in loop
        // val kernelSize = 2 * radius + 1

        for (y in 0 until h) {
            for (x in 0 until w) {
                var minVal = 255
                for (ky in -radius..radius) {
                    for (kx in -radius..radius) {
                        val nx = (x + kx).coerceIn(0, w - 1)
                        val ny = (y + ky).coerceIn(0, h - 1)
                        minVal = minOf(minVal, copy[ny * w + nx])
                    }
                }
                pixels[y * w + x] = minVal
            }
        }
    }

    /**
     * Apply an alpha mask to a bitmap.
     * Multiplies the bitmap's alpha channel by the mask's alpha channel.
     */
    private fun applyAlphaMask(bitmap: Bitmap, mask: Bitmap): Bitmap {
        val w = bitmap.width
        val h = bitmap.height
        val output = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)

        for (y in 0 until h) {
            for (x in 0 until w) {
                val srcPixel = bitmap.getPixel(x, y)
                val maskPixel = mask.getPixel(x, y)

                val srcAlpha = (srcPixel shr 24) and 0xFF
                val maskAlpha = (maskPixel shr 24) and 0xFF

                // Multiply alphas
                val newAlpha = (srcAlpha * maskAlpha) / 255

                // Combine with original RGB
                val newPixel = (newAlpha shl 24) or (srcPixel and 0x00FFFFFF)
                output.setPixel(x, y, newPixel)
            }
        }

        return output
    }

    /**
     * Center crop and scale image to a square of the given size.
     * Equivalent to Python center_crop_to_square.
     */
    private fun centerCropToSquare(bitmap: Bitmap, size: Int): Bitmap {
        // First crop to square
        val squareBitmap = cropToSquare(bitmap)

        // Then scale to target size
        return Bitmap.createScaledBitmap(squareBitmap, size, size, true)
    }

    /**
     * Create a rounded corner version of the image.
     */
    fun roundCorners(bitmap: Bitmap, cornerRadius: Float): Bitmap {
        val output = Bitmap.createBitmap(
            bitmap.width,
            bitmap.height,
            Bitmap.Config.ARGB_8888
        )

        val canvas = Canvas(output)
        val paint = Paint().apply {
            isAntiAlias = true
        }

        val rect = RectF(0f, 0f, bitmap.width.toFloat(), bitmap.height.toFloat())

        // Draw rounded rect
        canvas.drawRoundRect(rect, cornerRadius, cornerRadius, paint)

        // Set xfermode to draw image only where we drew
        paint.xfermode = PorterDuffXfermode(PorterDuff.Mode.SRC_IN)
        canvas.drawBitmap(bitmap, 0f, 0f, paint)

        return output
    }

    /**
     * Resize an image to specific dimensions.
     */
    fun resize(bitmap: Bitmap, width: Int, height: Int): Bitmap {
        return Bitmap.createScaledBitmap(bitmap, width, height, true)
    }

    /**
     * Create a square version of an image by center cropping.
     */
    fun cropToSquare(bitmap: Bitmap): Bitmap {
        val size = minOf(bitmap.width, bitmap.height)
        val x = (bitmap.width - size) / 2
        val y = (bitmap.height - size) / 2
        return Bitmap.createBitmap(bitmap, x, y, size, size)
    }
}
