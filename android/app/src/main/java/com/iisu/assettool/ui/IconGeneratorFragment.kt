package com.iisu.assettool.ui

import android.content.ContentValues
import android.graphics.Bitmap
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import coil.load
import com.iisu.assettool.R
import com.iisu.assettool.data.ArtworkScraper
import com.iisu.assettool.data.Platform
import com.iisu.assettool.databinding.FragmentIconGeneratorBinding
import com.iisu.assettool.util.ImageProcessor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.OutputStream

/**
 * Icon Generator Fragment
 *
 * Touch-friendly interface for searching and generating game icons.
 * Features:
 * - Large search input with clear button
 * - Platform selector dropdown
 * - Grid view of search results with large touch targets
 * - Preview with swipe gestures
 * - One-tap save to gallery
 */
class IconGeneratorFragment : Fragment() {

    private var _binding: FragmentIconGeneratorBinding? = null
    private val binding get() = _binding!!

    private val artworkScraper = ArtworkScraper()
    private var currentBitmap: Bitmap? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentIconGeneratorBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Load SteamGridDB API key from settings
        val sgdbApiKey = SettingsFragment.getSteamGridDBApiKey(requireContext())
        if (sgdbApiKey != null) {
            artworkScraper.setSteamGridDBApiKey(sgdbApiKey)
        }

        setupPlatformSpinner()
        setupSearchButton()
        setupSaveButton()
    }

    private fun setupPlatformSpinner() {
        val platforms = Platform.values().map { it.displayName }
        val adapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_dropdown_item,
            platforms
        )
        binding.spinnerPlatform.adapter = adapter
    }

    private fun setupSearchButton() {
        binding.buttonSearch.setOnClickListener {
            val query = binding.editTextSearch.text.toString().trim()
            if (query.isNotEmpty()) {
                searchArtwork(query)
            } else {
                Toast.makeText(context, "Please enter a search term", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun setupSaveButton() {
        binding.buttonSave.setOnClickListener {
            currentBitmap?.let { bitmap ->
                saveToGallery(bitmap)
            } ?: Toast.makeText(context, "No image to save", Toast.LENGTH_SHORT).show()
        }
    }

    private fun searchArtwork(query: String) {
        val selectedPlatform = Platform.values()[binding.spinnerPlatform.selectedItemPosition]

        binding.progressBar.visibility = View.VISIBLE
        binding.buttonSearch.isEnabled = false

        lifecycleScope.launch {
            try {
                val results = withContext(Dispatchers.IO) {
                    artworkScraper.searchIcons(query, selectedPlatform)
                }

                if (results.isNotEmpty()) {
                    // Load first result as preview
                    val firstResult = results.first()
                    binding.imagePreview.load(firstResult.url) {
                        crossfade(true)
                        listener(
                            onSuccess = { _, result ->
                                currentBitmap = (result.drawable as? android.graphics.drawable.BitmapDrawable)?.bitmap
                                binding.buttonSave.isEnabled = true
                            }
                        )
                    }
                    binding.textResultCount.text = "${results.size} results found"
                } else {
                    Toast.makeText(context, R.string.error_no_results, Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Toast.makeText(context, R.string.error_network, Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressBar.visibility = View.GONE
                binding.buttonSearch.isEnabled = true
            }
        }
    }

    private fun saveToGallery(bitmap: Bitmap) {
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    val filename = "iiSU_Icon_${System.currentTimeMillis()}.png"
                    val contentValues = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, filename)
                        put(MediaStore.MediaColumns.MIME_TYPE, "image/png")
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/iiSU Asset Tool")
                        }
                    }

                    val resolver = requireContext().contentResolver
                    val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, contentValues)

                    uri?.let {
                        val outputStream: OutputStream? = resolver.openOutputStream(it)
                        outputStream?.use { stream ->
                            bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream)
                        }
                    }
                }
                Toast.makeText(context, R.string.success_saved, Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(context, "Failed to save image", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
