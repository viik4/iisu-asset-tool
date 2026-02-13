package com.iisu.assettool.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.slider.Slider
import com.iisu.assettool.databinding.ActivityImageCropBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.net.URL

/**
 * Activity for cropping images to a 1024x1024 square.
 * Supports loading from URL or local file path.
 * Returns the path to the cropped image file.
 */
class ImageCropActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_IMAGE_URL = "image_url"
        const val EXTRA_IMAGE_PATH = "image_path"
        const val EXTRA_OUTPUT_PATH = "output_path"
        const val EXTRA_GAME_NAME = "game_name"
        const val RESULT_CROPPED_PATH = "cropped_path"

        fun createIntent(
            context: Context,
            imageUrl: String? = null,
            imagePath: String? = null,
            outputPath: String,
            gameName: String = "Image"
        ): Intent {
            return Intent(context, ImageCropActivity::class.java).apply {
                putExtra(EXTRA_IMAGE_URL, imageUrl)
                putExtra(EXTRA_IMAGE_PATH, imagePath)
                putExtra(EXTRA_OUTPUT_PATH, outputPath)
                putExtra(EXTRA_GAME_NAME, gameName)
            }
        }
    }

    private lateinit var binding: ActivityImageCropBinding
    private var outputPath: String = ""
    private var loadJob: Job? = null
    private val activityScope = CoroutineScope(Dispatchers.Main + Job())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityImageCropBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val imageUrl = intent.getStringExtra(EXTRA_IMAGE_URL)
        val imagePath = intent.getStringExtra(EXTRA_IMAGE_PATH)
        outputPath = intent.getStringExtra(EXTRA_OUTPUT_PATH) ?: ""
        // Game name available for future use (e.g., title display)
        @Suppress("UNUSED_VARIABLE")
        val gameName = intent.getStringExtra(EXTRA_GAME_NAME) ?: "Image"

        if (outputPath.isEmpty()) {
            Toast.makeText(this, "No output path specified", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        setupUI()
        loadImage(imageUrl, imagePath)
    }

    private fun setupUI() {
        // Close button
        binding.btnClose.setOnClickListener {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }

        // Save button
        binding.btnSave.setOnClickListener {
            saveCroppedImage()
        }

        // Zoom slider
        binding.sliderZoom.addOnChangeListener { _, value, fromUser ->
            if (fromUser) {
                binding.cropView.scale = value
            }
            binding.textZoomValue.text = "${(value * 100).toInt()}%"
        }

        // Rotation slider
        binding.sliderRotation.addOnChangeListener { _, value, fromUser ->
            if (fromUser) {
                binding.cropView.imageRotation = value
            }
            binding.textRotationValue.text = "${value.toInt()}°"
        }

        // Crop view transform callbacks
        binding.cropView.onTransformChanged = {
            // Update sliders when crop view changes (safely handle edge cases)
            try {
                val rawZoom = binding.cropView.scale.coerceIn(0.1f, 5f)
                if (rawZoom.isFinite()) {
                    // Round to nearest stepSize (0.1) to match slider constraints
                    val zoomValue = (Math.round(rawZoom * 10) / 10f).coerceIn(0.1f, 5f)
                    binding.sliderZoom.value = zoomValue
                }
                val rawRotation = binding.cropView.imageRotation.coerceIn(-180f, 180f)
                if (rawRotation.isFinite()) {
                    // Round to nearest stepSize (1) to match slider constraints
                    val rotationValue = Math.round(rawRotation).toFloat().coerceIn(-180f, 180f)
                    binding.sliderRotation.value = rotationValue
                }
            } catch (e: Exception) {
                // Ignore slider update errors during initialization
            }
        }

        // Quick action buttons
        binding.btnRotateLeft.setOnClickListener {
            // Setter automatically normalizes to -180..180 range
            binding.cropView.imageRotation -= 90f
        }

        binding.btnRotateRight.setOnClickListener {
            // Setter automatically normalizes to -180..180 range
            binding.cropView.imageRotation += 90f
        }

        binding.btnFitToSquare.setOnClickListener {
            binding.cropView.fitToSquare()
        }

        binding.btnFillSquare.setOnClickListener {
            binding.cropView.fillSquare()
        }

        binding.btnReset.setOnClickListener {
            binding.cropView.resetTransform()
        }
    }

    private fun loadImage(url: String?, path: String?) {
        loadJob = activityScope.launch {
            try {
                val bitmap = withContext(Dispatchers.IO) {
                    when {
                        !path.isNullOrEmpty() -> {
                            // Load from local file with options to handle large images
                            loadBitmapWithSampling(path)
                        }
                        !url.isNullOrEmpty() -> {
                            // Download from URL with sampling for large images
                            downloadBitmapWithSampling(url)
                        }
                        else -> null
                    }
                }

                if (bitmap != null && bitmap.width > 0 && bitmap.height > 0) {
                    binding.cropView.setImage(bitmap)
                } else {
                    Toast.makeText(this@ImageCropActivity, "Failed to load image", Toast.LENGTH_SHORT).show()
                    finish()
                }
            } catch (e: OutOfMemoryError) {
                Toast.makeText(this@ImageCropActivity, "Image too large to process", Toast.LENGTH_SHORT).show()
                finish()
            } catch (e: Exception) {
                Toast.makeText(this@ImageCropActivity, "Error loading image: ${e.message}", Toast.LENGTH_SHORT).show()
                finish()
            }
        }
    }

    private fun saveCroppedImage() {
        activityScope.launch {
            try {
                binding.btnSave.isEnabled = false
                binding.btnSave.text = "Saving..."

                val croppedBitmap = binding.cropView.getCroppedBitmap()
                if (croppedBitmap == null) {
                    Toast.makeText(this@ImageCropActivity, "Failed to crop image", Toast.LENGTH_SHORT).show()
                    binding.btnSave.isEnabled = true
                    binding.btnSave.text = "Save"
                    return@launch
                }

                withContext(Dispatchers.IO) {
                    val outputFile = File(outputPath)
                    outputFile.parentFile?.mkdirs()

                    FileOutputStream(outputFile).use { out ->
                        croppedBitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
                    }

                    croppedBitmap.recycle()
                }

                // Return result
                val resultIntent = Intent().apply {
                    putExtra(RESULT_CROPPED_PATH, outputPath)
                }
                setResult(Activity.RESULT_OK, resultIntent)
                finish()

            } catch (e: Exception) {
                Toast.makeText(this@ImageCropActivity, "Error saving: ${e.message}", Toast.LENGTH_SHORT).show()
                binding.btnSave.isEnabled = true
                binding.btnSave.text = "Save"
            }
        }
    }

    /**
     * Load bitmap with sampling to avoid OutOfMemoryError for large images.
     * Scales down images larger than 4096x4096 while maintaining quality for cropping.
     */
    private fun loadBitmapWithSampling(path: String): Bitmap? {
        // First, get image dimensions without loading full bitmap
        val options = BitmapFactory.Options().apply {
            inJustDecodeBounds = true
        }
        BitmapFactory.decodeFile(path, options)

        val imageWidth = options.outWidth
        val imageHeight = options.outHeight

        // If dimensions are invalid, return null
        if (imageWidth <= 0 || imageHeight <= 0) return null

        // Calculate sample size if image is very large
        var sampleSize = 1
        val maxDimension = 4096 // Max size to keep for quality

        while (imageWidth / sampleSize > maxDimension || imageHeight / sampleSize > maxDimension) {
            sampleSize *= 2
        }

        // Load the bitmap with sampling
        val loadOptions = BitmapFactory.Options().apply {
            inSampleSize = sampleSize
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }

        return BitmapFactory.decodeFile(path, loadOptions)
    }

    /**
     * Download bitmap from URL with sampling to avoid OutOfMemoryError for large images.
     * Downloads to a temp file first to get dimensions, then loads with appropriate sampling.
     */
    private fun downloadBitmapWithSampling(url: String): Bitmap? {
        val tempFile = File(cacheDir, "temp_crop_download_${System.currentTimeMillis()}.tmp")
        try {
            // Download the image to a temp file
            val connection = URL(url).openConnection()
            connection.connectTimeout = 15000
            connection.readTimeout = 30000
            connection.inputStream.use { input ->
                tempFile.outputStream().use { output ->
                    input.copyTo(output)
                }
            }

            // Now load with sampling using the temp file
            val bitmap = loadBitmapWithSampling(tempFile.absolutePath)

            // Clean up temp file
            tempFile.delete()

            return bitmap
        } catch (e: Exception) {
            tempFile.delete()
            // Fallback: try direct stream decode (may fail for large images)
            return try {
                val connection = URL(url).openConnection()
                connection.connectTimeout = 15000
                connection.readTimeout = 30000
                connection.inputStream.use { input ->
                    BitmapFactory.decodeStream(input)
                }
            } catch (e2: Exception) {
                null
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        loadJob?.cancel()
    }
}
