package com.iisu.assettool.util

import android.content.Context
import android.graphics.*
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream

/**
 * Icon generator that applies iiSU-style borders to artwork.
 * Ports the functionality from the desktop Python app.
 */
class IconGenerator(private val context: Context) {

    companion object {
        private const val TAG = "IconGenerator"
        const val DEFAULT_OUTPUT_SIZE = 256
        const val HIGH_RES_OUTPUT_SIZE = 1024

        // Border file mapping (platform name -> border file)
        private val BORDER_MAP = mapOf(
            "nes" to "NES.png",
            "snes" to "SNES.png",
            "n64" to "N64.png",
            "gamecube" to "Gamecube.png", "gc" to "Gamecube.png",
            "wii" to "Wii.png",
            "wiiu" to "Wii_U.png",
            "switch" to "Switch.png",
            "gb" to "Game_Boy.png",
            "gbc" to "Game_Boy_Color.png",
            "gba" to "Game_Boy_Advance.png",
            "nds" to "NINTENDO_DS.png",
            "3ds" to "NINTENDO_3DS.png", "n3ds" to "NINTENDO_3DS.png",
            "psx" to "PSX.png", "ps1" to "PSX.png",
            "ps2" to "PS2.png",
            "ps3" to "PS3.png",
            "ps4" to "PS4.png",
            "psp" to "PSP.png",
            "psvita" to "PS_Vita.png",
            "xbox" to "Xbox.png",
            "xbox360" to "XBOX_360.png",
            "genesis" to "GENESIS.png", "megadrive" to "GENESIS.png",
            "saturn" to "Saturn.png",
            "dreamcast" to "Dreamcast.png",
            "gamegear" to "Game_Gear.png",
            "mastersystem" to "border.png", // fallback
            "android" to "Android.png"
        )
    }

    /**
     * Generate an icon with iiSU border overlay.
     *
     * @param artworkBitmap The source artwork
     * @param platform The platform (used to select the appropriate border)
     * @param outputSize The output size (default 256x256)
     * @param centering Centering tuple (0.5, 0.5 = center)
     * @param customBorderPath Optional path to a custom border image (overrides platform border)
     * @return The composited icon with border, or null on failure
     */
    fun generateIconWithBorder(
        artworkBitmap: Bitmap,
        platform: String,
        outputSize: Int = DEFAULT_OUTPUT_SIZE,
        centering: Pair<Float, Float> = Pair(0.5f, 0.5f),
        customBorderPath: String? = null
    ): Bitmap? {
        try {
            // 1. Center crop the artwork to square
            val croppedArtwork = centerCropToSquare(artworkBitmap, outputSize, centering)

            // 2. Load the border (custom or platform-specific)
            val borderBitmap = if (customBorderPath != null) {
                loadCustomBorder(customBorderPath, outputSize)
            } else {
                loadBorderForPlatform(platform, outputSize)
            }

            if (borderBitmap == null) {
                Log.w(TAG, "No border found for platform: $platform, returning cropped artwork")
                return croppedArtwork
            }

            // 3. Create corner mask from border alpha
            val cornerMask = createCornerMaskFromBorder(borderBitmap)

            // 4. Apply corner mask to artwork
            val maskedArtwork = applyMaskToImage(croppedArtwork, cornerMask)

            // 5. Composite border on top
            return compositeImages(maskedArtwork, borderBitmap)

        } catch (e: Exception) {
            Log.e(TAG, "Failed to generate icon with border", e)
            return null
        }
    }

    /**
     * Load a custom border image from a file path.
     */
    private fun loadCustomBorder(path: String, size: Int): Bitmap? {
        return try {
            val file = File(path)
            if (!file.exists()) {
                Log.w(TAG, "Custom border file not found: $path")
                return null
            }

            val border = BitmapFactory.decodeFile(path)
            if (border == null) {
                Log.w(TAG, "Failed to decode custom border: $path")
                return null
            }

            // Scale to target size if needed
            if (border.width != size || border.height != size) {
                Bitmap.createScaledBitmap(border, size, size, true)
            } else {
                border
            }
        } catch (e: Exception) {
            Log.e(TAG, "Could not load custom border: $path", e)
            null
        }
    }

    /**
     * Center crop an image to a square of the specified size.
     */
    fun centerCropToSquare(
        source: Bitmap,
        targetSize: Int,
        centering: Pair<Float, Float> = Pair(0.5f, 0.5f)
    ): Bitmap {
        val minDim = minOf(source.width, source.height)

        // Calculate crop region based on centering
        val cropX = ((source.width - minDim) * centering.first).toInt()
        val cropY = ((source.height - minDim) * centering.second).toInt()

        // Crop to square
        val cropped = Bitmap.createBitmap(source, cropX, cropY, minDim, minDim)

        // Scale to target size
        return Bitmap.createScaledBitmap(cropped, targetSize, targetSize, true)
    }

    /**
     * Load the border image for a platform from assets.
     */
    private fun loadBorderForPlatform(platform: String, size: Int): Bitmap? {
        val borderFile = BORDER_MAP[platform.lowercase()] ?: "border.png"

        return try {
            val inputStream: InputStream = context.assets.open("borders/$borderFile")
            val border = BitmapFactory.decodeStream(inputStream)
            inputStream.close()

            // Scale to target size if needed
            if (border.width != size || border.height != size) {
                Bitmap.createScaledBitmap(border, size, size, true)
            } else {
                border
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not load border: $borderFile", e)
            // Try loading the default border
            try {
                val inputStream: InputStream = context.assets.open("borders/border.png")
                val border = BitmapFactory.decodeStream(inputStream)
                inputStream.close()
                Bitmap.createScaledBitmap(border, size, size, true)
            } catch (e2: Exception) {
                Log.e(TAG, "Could not load default border", e2)
                null
            }
        }
    }

    /**
     * Create a corner mask from the border's alpha channel.
     * This masks out the corners where the border has transparency.
     */
    private fun createCornerMaskFromBorder(border: Bitmap): Bitmap {
        val size = border.width
        val mask = Bitmap.createBitmap(size, size, Bitmap.Config.ALPHA_8)
        // Canvas created for potential future drawing operations
        @Suppress("UNUSED_VARIABLE")
        val canvas = Canvas(mask)

        // Extract alpha channel from border
        val pixels = IntArray(size * size)
        border.getPixels(pixels, 0, size, 0, 0, size, size)

        // Create mask where border has alpha > threshold
        val threshold = 18
        val maskPixels = IntArray(size * size)
        for (i in pixels.indices) {
            val alpha = (pixels[i] ushr 24) and 0xFF
            // Where border is opaque (has content), we want to KEEP the artwork
            // So we need the inverse - where border alpha is LOW, we mask OUT
            maskPixels[i] = if (alpha >= threshold) {
                0xFFFFFFFF.toInt() // White = keep
            } else {
                0x00000000 // Black = mask out
            }
        }

        // For the corner mask, we actually want to fill in the center
        // The border is typically a frame, so we fill the center hole
        val filledMask = fillCenterHole(maskPixels, size)

        val maskBitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        maskBitmap.setPixels(filledMask, 0, size, 0, 0, size, size)

        // Convert to grayscale alpha mask
        val grayMask = Bitmap.createBitmap(size, size, Bitmap.Config.ALPHA_8)
        val grayCanvas = Canvas(grayMask)
        val paint = Paint()
        paint.colorFilter = ColorMatrixColorFilter(ColorMatrix().apply {
            setSaturation(0f)
        })
        grayCanvas.drawBitmap(maskBitmap, 0f, 0f, paint)

        return maskBitmap
    }

    /**
     * Fill the center hole of a frame mask using flood fill.
     */
    private fun fillCenterHole(pixels: IntArray, size: Int): IntArray {
        val result = pixels.copyOf()
        val centerX = size / 2
        val centerY = size / 2
        val centerIndex = centerY * size + centerX

        // If center is already filled, return as-is
        if ((result[centerIndex] ushr 24) > 128) {
            return result
        }

        // Flood fill from center
        val visited = mutableSetOf<Int>()
        val queue = ArrayDeque<Int>()
        queue.add(centerIndex)
        visited.add(centerIndex)

        while (queue.isNotEmpty()) {
            val idx = queue.removeFirst()
            val x = idx % size
            val y = idx / size

            // Fill this pixel
            result[idx] = 0xFFFFFFFF.toInt()

            // Check neighbors
            val neighbors = listOf(
                Pair(x - 1, y), Pair(x + 1, y),
                Pair(x, y - 1), Pair(x, y + 1)
            )

            for ((nx, ny) in neighbors) {
                if (nx in 0 until size && ny in 0 until size) {
                    val nIdx = ny * size + nx
                    if (nIdx !in visited && (pixels[nIdx] ushr 24) < 128) {
                        visited.add(nIdx)
                        queue.add(nIdx)
                    }
                }
            }
        }

        return result
    }

    /**
     * Apply a mask to an image (multiply alpha channels).
     */
    private fun applyMaskToImage(image: Bitmap, mask: Bitmap): Bitmap {
        val result = Bitmap.createBitmap(image.width, image.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(result)

        // Draw the image
        canvas.drawBitmap(image, 0f, 0f, null)

        // Apply mask using DST_IN mode
        val paint = Paint()
        paint.xfermode = PorterDuffXfermode(PorterDuff.Mode.DST_IN)
        canvas.drawBitmap(mask, 0f, 0f, paint)

        return result
    }

    /**
     * Composite two images (draw overlay on top of base).
     */
    private fun compositeImages(base: Bitmap, overlay: Bitmap): Bitmap {
        val result = Bitmap.createBitmap(base.width, base.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(result)

        canvas.drawBitmap(base, 0f, 0f, null)
        canvas.drawBitmap(overlay, 0f, 0f, null)

        return result
    }

    /**
     * Save a bitmap to a file.
     */
    fun saveBitmap(bitmap: Bitmap, file: File, format: Bitmap.CompressFormat = Bitmap.CompressFormat.PNG, quality: Int = 100): Boolean {
        return try {
            FileOutputStream(file).use { out ->
                bitmap.compress(format, quality, out)
            }
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save bitmap", e)
            false
        }
    }

    /**
     * Get the border file name for a platform.
     */
    fun getBorderFileName(platform: String): String? {
        return BORDER_MAP[platform.lowercase()]
    }

    /**
     * Check if a border exists for a platform.
     */
    fun hasBorderForPlatform(platform: String): Boolean {
        val borderFile = BORDER_MAP[platform.lowercase()] ?: return false
        return try {
            context.assets.open("borders/$borderFile").close()
            true
        } catch (e: Exception) {
            false
        }
    }
}
