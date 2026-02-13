package com.iisu.assettool.ui

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import coil.load
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.google.android.material.textfield.TextInputEditText
import com.iisu.assettool.R
import com.iisu.assettool.data.AssetServerClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

/**
 * Bottom sheet dialog for uploading assets to the iiSU community asset server.
 *
 * Allows users to select an image file, enter game details, and upload
 * the asset to the community database at assets.iisu.community.
 */
class UploadAssetBottomSheet : BottomSheetDialogFragment() {

    private var client: AssetServerClient? = null
    private var platforms: List<String> = emptyList()
    private var selectedFileUri: Uri? = null
    private var onUploadComplete: (() -> Unit)? = null

    // Views
    private lateinit var imagePreview: android.widget.ImageView
    private lateinit var textNoFileSelected: android.widget.TextView
    private lateinit var textSelectedFilename: android.widget.TextView
    private lateinit var editGameName: TextInputEditText
    private lateinit var spinnerPlatform: MaterialAutoCompleteTextView
    private lateinit var spinnerAssetType: MaterialAutoCompleteTextView
    private lateinit var spinnerVariantNumber: MaterialAutoCompleteTextView
    private lateinit var textUploadStatus: android.widget.TextView
    private lateinit var progressUpload: android.widget.ProgressBar
    private lateinit var btnUploadAsset: MaterialButton
    private lateinit var btnCancelUpload: MaterialButton
    private lateinit var btnSelectFile: MaterialButton
    private lateinit var btnCloseUpload: MaterialButton

    // File picker launcher
    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                onFileSelected(uri)
            }
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View? {
        return inflater.inflate(R.layout.bottom_sheet_upload_asset, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupViews(view)
        setupDropdowns()
        setupButtons()
    }

    private fun setupViews(view: View) {
        imagePreview = view.findViewById(R.id.imageUploadPreview)
        textNoFileSelected = view.findViewById(R.id.textNoFileSelected)
        textSelectedFilename = view.findViewById(R.id.textSelectedFilename)
        editGameName = view.findViewById(R.id.editGameName)
        spinnerPlatform = view.findViewById(R.id.spinnerUploadPlatform)
        spinnerAssetType = view.findViewById(R.id.spinnerAssetType)
        spinnerVariantNumber = view.findViewById(R.id.spinnerVariantNumber)
        textUploadStatus = view.findViewById(R.id.textUploadStatus)
        progressUpload = view.findViewById(R.id.progressUpload)
        btnUploadAsset = view.findViewById(R.id.btnUploadAsset)
        btnCancelUpload = view.findViewById(R.id.btnCancelUpload)
        btnSelectFile = view.findViewById(R.id.btnSelectFile)
        btnCloseUpload = view.findViewById(R.id.btnCloseUpload)
    }

    private fun setupDropdowns() {
        // Platform dropdown
        if (platforms.isNotEmpty()) {
            val platformAdapter = ArrayAdapter(
                requireContext(),
                android.R.layout.simple_spinner_dropdown_item,
                platforms
            )
            spinnerPlatform.setAdapter(platformAdapter)
            if (platforms.isNotEmpty()) {
                spinnerPlatform.setText(platforms.first(), false)
            }
        }

        // Asset type dropdown
        val assetTypes = listOf("icon")
        val typeAdapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_dropdown_item,
            assetTypes
        )
        spinnerAssetType.setAdapter(typeAdapter)
        spinnerAssetType.setText("icon", false)

        // Variant number dropdown
        val variantNumbers = (1..10).map { it.toString() }
        val variantAdapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_dropdown_item,
            variantNumbers
        )
        spinnerVariantNumber.setAdapter(variantAdapter)
        spinnerVariantNumber.setText("1", false)
    }

    private fun setupButtons() {
        btnSelectFile.setOnClickListener {
            openFilePicker()
        }

        // Also allow tapping the preview area to select file
        imagePreview.setOnClickListener {
            openFilePicker()
        }

        btnUploadAsset.setOnClickListener {
            performUpload()
        }

        btnCancelUpload.setOnClickListener {
            dismiss()
        }

        btnCloseUpload.setOnClickListener {
            dismiss()
        }
    }

    private fun openFilePicker() {
        val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
            type = "image/*"
            addCategory(Intent.CATEGORY_OPENABLE)
        }
        filePickerLauncher.launch(Intent.createChooser(intent, "Select Asset Image"))
    }

    private fun onFileSelected(uri: Uri) {
        selectedFileUri = uri

        // Show preview
        imagePreview.load(uri) {
            crossfade(true)
            placeholder(R.drawable.ic_image_placeholder)
        }
        textNoFileSelected.visibility = View.GONE

        // Show filename
        val filename = getFileName(uri)
        textSelectedFilename.text = filename
        textSelectedFilename.visibility = View.VISIBLE

        // Enable upload button
        btnUploadAsset.isEnabled = true
    }

    private fun getFileName(uri: Uri): String {
        var name = "unknown"
        context?.contentResolver?.query(uri, null, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex >= 0) {
                    name = cursor.getString(nameIndex)
                }
            }
        }
        return name
    }

    private fun performUpload() {
        val uri = selectedFileUri ?: return
        val gameName = editGameName.text?.toString()?.trim()
        val platform = spinnerPlatform.text?.toString()?.trim()
        val assetType = spinnerAssetType.text?.toString()?.trim()
        val variantNumber = spinnerVariantNumber.text?.toString()?.trim()?.toIntOrNull() ?: 1

        // Validation
        if (gameName.isNullOrEmpty()) {
            editGameName.error = "Game name is required"
            return
        }
        if (platform.isNullOrEmpty()) {
            Toast.makeText(context, "Please select a platform", Toast.LENGTH_SHORT).show()
            return
        }
        if (assetType.isNullOrEmpty()) {
            Toast.makeText(context, "Please select an asset type", Toast.LENGTH_SHORT).show()
            return
        }

        val serverClient = client ?: return

        // Disable UI during upload
        btnUploadAsset.isEnabled = false
        btnCancelUpload.isEnabled = false
        textUploadStatus.text = "Uploading..."
        textUploadStatus.visibility = View.VISIBLE
        progressUpload.visibility = View.VISIBLE

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                // Copy URI content to temp file
                val tempFile = withContext(Dispatchers.IO) {
                    val filename = getFileName(uri)
                    val tempDir = requireContext().cacheDir
                    val file = File(tempDir, "upload_$filename")
                    requireContext().contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(file).use { output ->
                            input.copyTo(output)
                        }
                    }
                    file
                }

                // Perform upload
                val result = withContext(Dispatchers.IO) {
                    serverClient.uploadAsset(
                        file = tempFile,
                        gameName = gameName,
                        platform = platform,
                        assetType = assetType,
                        variantNumber = variantNumber
                    )
                }

                // Clean up temp file
                withContext(Dispatchers.IO) {
                    tempFile.delete()
                }

                if (result.success) {
                    textUploadStatus.text = "Upload successful!"
                    textUploadStatus.setTextColor(
                        requireContext().getColor(R.color.status_success)
                    )
                    Toast.makeText(context, result.message, Toast.LENGTH_SHORT).show()

                    // Notify parent and dismiss
                    onUploadComplete?.invoke()
                    dismiss()
                } else {
                    textUploadStatus.text = "Upload failed: ${result.message}"
                    textUploadStatus.setTextColor(
                        requireContext().getColor(R.color.status_error)
                    )
                    btnUploadAsset.isEnabled = true
                    btnCancelUpload.isEnabled = true
                }

            } catch (e: Exception) {
                android.util.Log.e("UploadAssetBottomSheet", "Upload error: ${e.message}", e)
                textUploadStatus.text = "Error: ${e.message}"
                textUploadStatus.setTextColor(
                    requireContext().getColor(R.color.status_error)
                )
                btnUploadAsset.isEnabled = true
                btnCancelUpload.isEnabled = true
            } finally {
                progressUpload.visibility = View.GONE
            }
        }
    }

    companion object {
        const val TAG = "UploadAssetBottomSheet"

        /**
         * Create and show the upload bottom sheet.
         *
         * @param client The AssetServerClient to use for uploading
         * @param platforms List of available platform names
         * @param onUploadComplete Callback when upload completes successfully
         */
        fun show(
            fragment: androidx.fragment.app.Fragment,
            client: AssetServerClient,
            platforms: List<String>,
            onUploadComplete: () -> Unit = {}
        ) {
            val bottomSheet = UploadAssetBottomSheet().apply {
                this.client = client
                this.platforms = platforms
                this.onUploadComplete = onUploadComplete
            }
            bottomSheet.show(fragment.childFragmentManager, TAG)
        }
    }
}
