package com.iisu.assettool.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.DocumentsContract
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.documentfile.provider.DocumentFile
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentSettingsOutputBinding
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

/**
 * Output Options settings tab.
 * Contains: Export format, Custom Border, Asset Directory
 */
class SettingsOutputFragment : Fragment() {

    private var _binding: FragmentSettingsOutputBinding? = null
    private val binding get() = _binding!!

    private companion object {
        const val CUSTOM_BORDER_FILENAME = "custom_border.png"
    }

    // Border picker launcher
    private val borderPickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                copyBorderToInternalStorage(uri)
            }
        }
    }

    // Directory picker launcher
    private val directoryPickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                handleDirectorySelection(uri)
            }
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsOutputBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupExportFormat()
        setupCustomBorder()
        setupAssetDirectory()
    }

    private fun setupExportFormat() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Load current format
        val currentFormat = prefs.getString(
            SettingsFragment.PREF_EXPORT_FORMAT,
            SettingsFragment.DEFAULT_EXPORT_FORMAT
        )

        when (currentFormat) {
            "PNG" -> binding.radioFormatPng.isChecked = true
            "JPEG" -> binding.radioFormatJpeg.isChecked = true
        }

        // Show JPEG quality if JPEG is selected
        binding.layoutJpegQuality.visibility = if (currentFormat == "JPEG") View.VISIBLE else View.GONE

        // Load JPEG quality
        val jpegQuality = prefs.getInt(
            SettingsFragment.PREF_JPEG_QUALITY,
            SettingsFragment.DEFAULT_JPEG_QUALITY
        )
        binding.sliderJpegQuality.value = jpegQuality.toFloat()
        binding.textJpegQuality.text = "$jpegQuality%"

        // Format selection listener
        binding.radioGroupExportFormat.setOnCheckedChangeListener { _, checkedId ->
            val format = when (checkedId) {
                R.id.radioFormatPng -> "PNG"
                R.id.radioFormatJpeg -> "JPEG"
                else -> "PNG"
            }
            prefs.edit().putString(SettingsFragment.PREF_EXPORT_FORMAT, format).apply()
            binding.layoutJpegQuality.visibility = if (format == "JPEG") View.VISIBLE else View.GONE
        }

        // JPEG quality slider
        binding.sliderJpegQuality.addOnChangeListener { _, value, _ ->
            val quality = value.toInt()
            binding.textJpegQuality.text = "$quality%"
            prefs.edit().putInt(SettingsFragment.PREF_JPEG_QUALITY, quality).apply()
        }
    }

    private fun setupCustomBorder() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Load custom border state
        val useCustomBorder = prefs.getBoolean(
            SettingsFragment.PREF_USE_CUSTOM_BORDER,
            SettingsFragment.DEFAULT_USE_CUSTOM_BORDER
        )
        binding.switchUseCustomBorder.isChecked = useCustomBorder
        binding.layoutCustomBorder.visibility = if (useCustomBorder) View.VISIBLE else View.GONE

        // Load border preview
        updateBorderPreview()

        // Toggle custom border
        binding.rowUseCustomBorder.setOnClickListener {
            binding.switchUseCustomBorder.toggle()
            val enabled = binding.switchUseCustomBorder.isChecked
            prefs.edit().putBoolean(SettingsFragment.PREF_USE_CUSTOM_BORDER, enabled).apply()
            binding.layoutCustomBorder.visibility = if (enabled) View.VISIBLE else View.GONE
        }

        // Select border button
        binding.btnSelectCustomBorder.setOnClickListener {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "image/*"
            }
            borderPickerLauncher.launch(intent)
        }

        // Clear border button
        binding.btnClearCustomBorder.setOnClickListener {
            clearCustomBorder()
        }
    }

    private fun updateBorderPreview() {
        val borderFile = File(requireContext().filesDir, CUSTOM_BORDER_FILENAME)
        if (borderFile.exists()) {
            val bitmap = BitmapFactory.decodeFile(borderFile.absolutePath)
            binding.imageCustomBorderPreview.setImageBitmap(bitmap)
            binding.textCustomBorderPath.text = getString(R.string.settings_border_set)
        } else {
            binding.imageCustomBorderPreview.setImageResource(R.drawable.ic_image_placeholder)
            binding.textCustomBorderPath.text = getString(R.string.settings_no_border)
        }
    }

    private fun copyBorderToInternalStorage(uri: Uri) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    requireContext().contentResolver.openInputStream(uri)?.use { input ->
                        val outputFile = File(requireContext().filesDir, CUSTOM_BORDER_FILENAME)
                        FileOutputStream(outputFile).use { output ->
                            input.copyTo(output)
                        }
                    }
                }
                updateBorderPreview()
                Toast.makeText(requireContext(), R.string.settings_border_saved, Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(requireContext(), R.string.settings_border_error, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun clearCustomBorder() {
        val borderFile = File(requireContext().filesDir, CUSTOM_BORDER_FILENAME)
        if (borderFile.exists()) {
            borderFile.delete()
        }
        updateBorderPreview()
    }

    private fun setupAssetDirectory() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Load current directory
        updateAssetDirectoryDisplay()

        // Select directory button
        binding.btnSelectAssetDir.setOnClickListener {
            openDirectoryPicker()
        }

        // Reset directory button
        binding.btnClearAssetDir.setOnClickListener {
            prefs.edit().remove(SettingsFragment.PREF_CUSTOM_ASSET_DIR).apply()
            updateAssetDirectoryDisplay()
            Toast.makeText(requireContext(), R.string.settings_dir_reset, Toast.LENGTH_SHORT).show()
        }
    }

    private fun updateAssetDirectoryDisplay() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        val customDir = prefs.getString(SettingsFragment.PREF_CUSTOM_ASSET_DIR, null)
        if (customDir != null) {
            binding.textCustomAssetDir.text = customDir
        } else {
            val defaultDir = IisuDirectoryManager.getIisuRoot()
            binding.textCustomAssetDir.text = defaultDir.absolutePath
        }
    }

    private fun openDirectoryPicker() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)

            // Try to start in a sensible location
            val downloadsUri = Uri.parse("content://com.android.externalstorage.documents/document/primary:Download")
            putExtra(DocumentsContract.EXTRA_INITIAL_URI, downloadsUri)
        }
        directoryPickerLauncher.launch(intent)
    }

    private fun handleDirectorySelection(uri: Uri) {
        // Take persistable permission
        requireContext().contentResolver.takePersistableUriPermission(
            uri,
            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        )

        // Get the actual path for display
        val documentFile = DocumentFile.fromTreeUri(requireContext(), uri)
        val displayPath = documentFile?.name ?: uri.lastPathSegment ?: uri.toString()

        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Store the URI string
        prefs.edit().putString(SettingsFragment.PREF_CUSTOM_ASSET_DIR, uri.toString()).apply()

        binding.textCustomAssetDir.text = displayPath
        Toast.makeText(requireContext(), R.string.settings_dir_set, Toast.LENGTH_SHORT).show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
