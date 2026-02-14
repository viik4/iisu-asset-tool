package com.iisu.assettool.ui

import android.app.Dialog
import android.content.Context
import android.graphics.Bitmap
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.ContextCompat
import com.google.android.material.card.MaterialCardView
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.slider.Slider
import com.iisu.assettool.R
import com.iisu.assettool.databinding.DialogArtworkPickerBinding
import com.iisu.assettool.util.ArtworkOption
import com.iisu.assettool.util.ArtworkSearchResult

/**
 * Dialog for selecting artwork from multiple options.
 * Shows current image (if any), available options with thumbnails,
 * and allows user to select one to save.
 *
 * For icons, supports a filter toggle between "Square Only" (default) and "All Results".
 * When "All Results" is selected, non-square images can be cropped using ImageCropActivity.
 *
 * In bulk generation mode, provides Skip button to skip current game
 * without cancelling the entire operation.
 */
class ArtworkPickerDialog(
    context: Context,
    private val artworkType: ArtworkType,
    private var searchResult: ArtworkSearchResult,
    private val onOptionSelected: (ArtworkOption) -> Unit,
    private val onSkip: (() -> Unit)? = null,
    private val onCancel: (() -> Unit)? = null,
    private val onFilterChanged: ((squareOnly: Boolean) -> Unit)? = null,
    initialSquareOnly: Boolean = true
) : Dialog(context) {

    enum class ArtworkType {
        ICON, HERO, LOGO
    }

    private lateinit var binding: DialogArtworkPickerBinding
    private var selectedOption: ArtworkOption? = null
    private var selectedView: MaterialCardView? = null
    private var wasCancelled = true  // Track if dialog was cancelled vs skipped/saved
    private var isSquareOnlyFilter = initialSquareOnly  // Track current filter state

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestWindowFeature(Window.FEATURE_NO_TITLE)

        binding = DialogArtworkPickerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // Set dialog size based on orientation
        val isLandscape = context.resources.configuration.orientation ==
            android.content.res.Configuration.ORIENTATION_LANDSCAPE

        if (isLandscape) {
            // In landscape, limit height to 85% of screen height
            val displayMetrics = context.resources.displayMetrics
            val maxHeight = (displayMetrics.heightPixels * 0.85).toInt()
            window?.setLayout(
                ViewGroup.LayoutParams.MATCH_PARENT,
                maxHeight
            )
        } else {
            // In portrait, wrap content
            window?.setLayout(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        }

        setupUI()
        displayOptions()
    }

    /**
     * Update the search results and refresh the display.
     * Used when filter changes to show new results.
     */
    fun updateSearchResult(newResult: ArtworkSearchResult) {
        searchResult = newResult
        updateSubtitle()
        displayOptions()
    }

    /**
     * Show loading state while fetching new results.
     */
    fun showLoading() {
        binding.progressBar.visibility = View.VISIBLE
        binding.scrollOptions.visibility = View.GONE
        binding.textNoOptions.visibility = View.GONE
        binding.btnSave.isEnabled = false
        selectedOption = null
        selectedView = null
    }

    private fun updateSubtitle() {
        val optionCount = searchResult.options.size
        val sources = searchResult.options.map { it.source }.distinct()
        if (optionCount > 0) {
            binding.textSubtitle.text = "Found $optionCount option(s) from ${sources.size} source(s)"
        } else {
            binding.textSubtitle.text = "No options found"
        }
    }

    private fun setupUI() {
        // Set title
        val typeText = when (artworkType) {
            ArtworkType.ICON -> "Icon"
            ArtworkType.HERO -> "Hero"
            ArtworkType.LOGO -> "Logo"
        }
        binding.textTitle.text = "Select $typeText for ${searchResult.gameName}"

        // Set subtitle
        updateSubtitle()

        // Setup filter toggle (only for icons)
        setupFilterToggle()

        // Show current image if exists
        if (searchResult.currentImage != null) {
            binding.layoutCurrentImage.visibility = View.VISIBLE
            binding.imageCurrentArtwork.setImageBitmap(searchResult.currentImage)
        } else {
            binding.layoutCurrentImage.visibility = View.GONE
        }

        // Cancel button - stops the entire bulk operation
        binding.btnCancel.setOnClickListener {
            wasCancelled = true
            dismiss()
        }

        // Skip button - visible only in bulk mode, skips current game
        if (onSkip != null) {
            binding.btnSkip?.visibility = View.VISIBLE
            binding.btnSkip?.setOnClickListener {
                wasCancelled = false
                onSkip.invoke()
                dismiss()
            }
        } else {
            binding.btnSkip?.visibility = View.GONE
        }

        // Save button — for heroes, show crop options first
        binding.btnSave.setOnClickListener {
            selectedOption?.let { option ->
                if (artworkType == ArtworkType.HERO) {
                    showHeroCropOptions(option)
                } else {
                    wasCancelled = false
                    onOptionSelected(option)
                    dismiss()
                }
            }
        }

        // Handle dialog dismiss (back button, tap outside)
        setOnDismissListener {
            if (wasCancelled) {
                onCancel?.invoke()
            }
        }
    }

    private fun setupFilterToggle() {
        // Only show filter toggle for icons when callback is provided
        if (artworkType != ArtworkType.ICON || onFilterChanged == null) {
            binding.layoutFilterToggle?.visibility = View.GONE
            return
        }

        binding.layoutFilterToggle?.visibility = View.VISIBLE

        // Set initial state
        binding.chipSquareOnly?.isChecked = isSquareOnlyFilter
        binding.chipAllResults?.isChecked = !isSquareOnlyFilter

        // Handle chip selection changes
        binding.chipGroupFilter?.setOnCheckedStateChangeListener { _, checkedIds ->
            val newSquareOnly = checkedIds.contains(R.id.chipSquareOnly)
            if (newSquareOnly != isSquareOnlyFilter) {
                isSquareOnlyFilter = newSquareOnly
                showLoading()
                @Suppress("UNNECESSARY_SAFE_CALL")
                onFilterChanged?.invoke(newSquareOnly)
            }
        }

        // Info icon click - show tooltip
        binding.iconFilterInfo?.setOnClickListener {
            Toast.makeText(
                context,
                if (isSquareOnlyFilter) {
                    "Showing only square icons (1:1 aspect ratio)"
                } else {
                    "Showing all icons. Non-square images will open a crop editor."
                },
                Toast.LENGTH_LONG
            ).show()
        }
    }

    private fun displayOptions() {
        binding.layoutOptions.removeAllViews()

        if (searchResult.options.isEmpty()) {
            binding.scrollOptions.visibility = View.GONE
            binding.textNoOptions.visibility = View.VISIBLE
            binding.btnSave.isEnabled = false
            return
        }

        binding.scrollOptions.visibility = View.VISIBLE
        binding.textNoOptions.visibility = View.GONE

        val isLandscape = context.resources.configuration.orientation ==
            android.content.res.Configuration.ORIENTATION_LANDSCAPE

        if (isLandscape) {
            // Landscape: horizontal layout inside HorizontalScrollView (handled by XML)
            for (option in searchResult.options) {
                val optionView = createOptionView(option, 1)
                // In landscape, use fixed width for horizontal scroll
                val lp = LinearLayout.LayoutParams(160.dpToPx(), LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                    marginEnd = 8.dpToPx()
                }
                optionView.layoutParams = lp
                binding.layoutOptions.addView(optionView)
            }
        } else {
            // Portrait: grid layout with adaptive columns
            val displayMetrics = context.resources.displayMetrics
            val screenWidthDp = displayMetrics.widthPixels / displayMetrics.density
            // Subtract dialog padding (16dp * 2) to get usable width
            val usableWidthDp = screenWidthDp - 32f
            val cardWidthDp = when (artworkType) {
                ArtworkType.ICON -> 140f   // Compact icon cards
                ArtworkType.HERO -> 220f   // Wide hero cards
                ArtworkType.LOGO -> 160f   // Medium logo cards
            }
            val columns = maxOf(2, (usableWidthDp / cardWidthDp).toInt())

            // Arrange options in grid rows
            var currentRow: LinearLayout? = null
            for ((index, option) in searchResult.options.withIndex()) {
                if (index % columns == 0) {
                    currentRow = LinearLayout(context).apply {
                        orientation = LinearLayout.HORIZONTAL
                        layoutParams = LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.MATCH_PARENT,
                            LinearLayout.LayoutParams.WRAP_CONTENT
                        )
                    }
                    binding.layoutOptions.addView(currentRow)
                }

                val optionView = createOptionView(option, columns)
                currentRow?.addView(optionView)
            }

            // Fill last row with invisible spacers if needed
            val remaining = searchResult.options.size % columns
            if (remaining > 0 && currentRow != null) {
                for (i in 0 until (columns - remaining)) {
                    val spacer = View(context)
                    spacer.layoutParams = LinearLayout.LayoutParams(0, 1, 1f)
                    currentRow.addView(spacer)
                }
            }
        }
    }

    private fun createOptionView(option: ArtworkOption, columns: Int = 1): View {
        val inflater = LayoutInflater.from(context)
        val view = inflater.inflate(R.layout.item_artwork_option, null, false)

        // Use weight-based layout to fill available width evenly
        val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
            marginEnd = 4.dpToPx()
            marginStart = 4.dpToPx()
            bottomMargin = 8.dpToPx()
        }
        view.layoutParams = lp

        val card = view.findViewById<MaterialCardView>(R.id.cardOption)
        val frameThumbnail = view.findViewById<FrameLayout>(R.id.frameThumbnail)
        val thumbnail = view.findViewById<ImageView>(R.id.imageThumbnail)
        val progress = view.findViewById<ProgressBar>(R.id.progressThumbnail)
        val iconSelected = view.findViewById<ImageView>(R.id.iconSelected)
        val textSource = view.findViewById<TextView>(R.id.textSource)
        val textDimensions = view.findViewById<TextView>(R.id.textDimensions)

        // Note: card IS the root view (MaterialCardView), so the weight-based
        // layoutParams set above on `view` already apply to `card` — don't override them.

        // Adjust thumbnail height based on artwork type for better preview
        // Width fills card; height is fixed for consistent grid rows
        val thumbnailHeight = when (artworkType) {
            ArtworkType.ICON -> 90.dpToPx()
            ArtworkType.HERO -> 60.dpToPx()  // ~3:1 aspect ratio for heroes
            ArtworkType.LOGO -> 70.dpToPx()  // Logos are typically wider than tall
        }
        val frameParams = frameThumbnail.layoutParams
        frameParams.width = ViewGroup.LayoutParams.MATCH_PARENT
        frameParams.height = thumbnailHeight
        frameThumbnail.layoutParams = frameParams

        // Use fitCenter for heroes/logos to show full image without cropping
        thumbnail.scaleType = when (artworkType) {
            ArtworkType.ICON -> ImageView.ScaleType.CENTER_CROP
            ArtworkType.HERO -> ImageView.ScaleType.FIT_CENTER
            ArtworkType.LOGO -> ImageView.ScaleType.FIT_CENTER
        }

        // Set source label
        textSource.text = option.source

        // Set dimensions if available
        if (option.width > 0 && option.height > 0) {
            textDimensions.visibility = View.VISIBLE
            textDimensions.text = "${option.width}x${option.height}"
        } else {
            textDimensions.visibility = View.GONE
        }

        // Set thumbnail
        if (option.thumbnail != null) {
            thumbnail.setImageBitmap(option.thumbnail)
            progress.visibility = View.GONE
        } else {
            // Show placeholder
            thumbnail.setImageResource(R.drawable.ic_missing_icon)
            progress.visibility = View.GONE
        }

        // Click handler
        card.setOnClickListener {
            selectOption(option, card, iconSelected)
        }

        return view
    }

    private fun selectOption(option: ArtworkOption, card: MaterialCardView, iconSelected: ImageView) {
        // Deselect previous
        selectedView?.let { prevCard ->
            prevCard.strokeColor = ContextCompat.getColor(context, R.color.surface_variant)
            prevCard.strokeWidth = 2.dpToPx()
            // Hide previous selection indicator
            prevCard.findViewById<ImageView>(R.id.iconSelected)?.visibility = View.GONE
        }

        // Select new
        selectedOption = option
        selectedView = card

        card.strokeColor = ContextCompat.getColor(context, R.color.accent_cyan)
        card.strokeWidth = 3.dpToPx()
        iconSelected.visibility = View.VISIBLE

        // Enable save button
        binding.btnSave.isEnabled = true
    }

    private fun Int.dpToPx(): Int {
        return (this * context.resources.displayMetrics.density).toInt()
    }

    /**
     * Show hero crop options dialog before saving.
     * Lets the user choose: Original, Left/Center/Right presets, or Custom with a slider.
     */
    private fun showHeroCropOptions(option: ArtworkOption) {
        val dimInfo = if (option.width > 0 && option.height > 0) {
            "${option.width}×${option.height}"
        } else {
            "Unknown"
        }

        val options = arrayOf(
            "Use Original ($dimInfo)",
            "Crop Left",
            "Crop Center",
            "Crop Right",
            "Custom Crop..."
        )

        MaterialAlertDialogBuilder(context)
            .setTitle("Hero Crop Position")
            .setItems(options) { _, which ->
                when (which) {
                    0 -> {
                        option.cropMode = ArtworkOption.CropMode.NONE
                        wasCancelled = false
                        onOptionSelected(option)
                        dismiss()
                    }
                    1 -> {
                        option.cropMode = ArtworkOption.CropMode.CROP_LEFT
                        wasCancelled = false
                        onOptionSelected(option)
                        dismiss()
                    }
                    2 -> {
                        option.cropMode = ArtworkOption.CropMode.CROP_CENTER
                        wasCancelled = false
                        onOptionSelected(option)
                        dismiss()
                    }
                    3 -> {
                        option.cropMode = ArtworkOption.CropMode.CROP_RIGHT
                        wasCancelled = false
                        onOptionSelected(option)
                        dismiss()
                    }
                    4 -> {
                        showCustomCropDialog(option)
                    }
                }
            }
            .setNegativeButton("Go Back", null)
            .show()
    }

    /**
     * Show a custom crop dialog with a horizontal slider and live preview.
     * Uses the option's thumbnail for the preview. Supports both slider and
     * direct touch-drag on the preview to adjust position.
     */
    private fun showCustomCropDialog(option: ArtworkOption) {
        val dialogView = LayoutInflater.from(context)
            .inflate(R.layout.dialog_hero_crop_preview, null)

        val previewView = dialogView.findViewById<HeroCropPreviewView>(R.id.heroCropPreview)
        val slider = dialogView.findViewById<Slider>(R.id.sliderPosition)
        val btnLeft = dialogView.findViewById<MaterialButton>(R.id.btnLeft)
        val btnCenter = dialogView.findViewById<MaterialButton>(R.id.btnCenter)
        val btnRight = dialogView.findViewById<MaterialButton>(R.id.btnRight)

        // Track whether the update is from slider or from touch to prevent feedback loops
        var updatingFromTouch = false
        var updatingFromSlider = false

        // Set the thumbnail as preview image
        option.thumbnail?.let { previewView.setImage(it) }

        // Slider updates the preview
        slider.addOnChangeListener { _, value, fromUser ->
            if (fromUser && !updatingFromTouch) {
                updatingFromSlider = true
                previewView.position = value
                updatingFromSlider = false
            }
        }

        // Touch-drag on preview syncs back to slider
        previewView.onPositionChanged = { newPosition ->
            if (!updatingFromSlider) {
                updatingFromTouch = true
                slider.value = newPosition.coerceIn(0f, 1f)
                updatingFromTouch = false
            }
        }

        // Quick position buttons
        btnLeft.setOnClickListener {
            slider.value = 0f
            previewView.position = 0f
        }
        btnCenter.setOnClickListener {
            slider.value = 0.5f
            previewView.position = 0.5f
        }
        btnRight.setOnClickListener {
            slider.value = 1f
            previewView.position = 1f
        }

        MaterialAlertDialogBuilder(context)
            .setView(dialogView)
            .setPositiveButton("Apply") { _, _ ->
                option.cropMode = ArtworkOption.CropMode.CROP_CUSTOM
                option.customHorizontalPosition = previewView.position
                wasCancelled = false
                onOptionSelected(option)
                dismiss()
            }
            .setNegativeButton("Go Back", null)
            .show()
    }

    companion object {
        /**
         * Show the artwork picker dialog.
         */
        fun show(
            context: Context,
            artworkType: ArtworkType,
            searchResult: ArtworkSearchResult,
            onOptionSelected: (ArtworkOption) -> Unit
        ): ArtworkPickerDialog {
            val dialog = ArtworkPickerDialog(context, artworkType, searchResult, onOptionSelected)
            dialog.show()
            return dialog
        }

        /**
         * Show the artwork picker dialog with skip support for bulk operations.
         * @param onSkip Called when user clicks Skip to move to next game
         * @param onCancel Called when user clicks Cancel to stop the bulk operation
         */
        fun showWithSkip(
            context: Context,
            artworkType: ArtworkType,
            searchResult: ArtworkSearchResult,
            onOptionSelected: (ArtworkOption) -> Unit,
            onSkip: () -> Unit,
            onCancel: () -> Unit
        ): ArtworkPickerDialog {
            val dialog = ArtworkPickerDialog(
                context, artworkType, searchResult,
                onOptionSelected, onSkip, onCancel
            )
            dialog.show()
            return dialog
        }

        /**
         * Show the artwork picker dialog with filter support for icons.
         * @param onOptionSelected Called when user selects an option. For non-square images,
         *                         the caller should launch ImageCropActivity.
         * @param initialSquareOnly Initial state of the filter toggle (default true).
         *                          Set to false if showing non-square results initially.
         * @param onFilterChanged Called when user changes the filter (square only vs all results).
         *                        The caller should fetch new results and call updateSearchResult().
         */
        fun showWithFilter(
            context: Context,
            artworkType: ArtworkType,
            searchResult: ArtworkSearchResult,
            initialSquareOnly: Boolean = true,
            onOptionSelected: (ArtworkOption) -> Unit,
            onFilterChanged: (squareOnly: Boolean) -> Unit
        ): ArtworkPickerDialog {
            val dialog = ArtworkPickerDialog(
                context, artworkType, searchResult,
                onOptionSelected, null, null, onFilterChanged, initialSquareOnly
            )
            dialog.show()
            return dialog
        }

        /**
         * Convenience method for showing icon picker with filter toggle support.
         * This is the recommended method for icon selection with interactive filter switching.
         */
        fun showForIconWithFilter(
            context: Context,
            searchResult: ArtworkSearchResult,
            initialSquareOnly: Boolean = true,
            onOptionSelected: (ArtworkOption) -> Unit,
            onSkip: (() -> Unit)? = null,
            onCancel: (() -> Unit)? = null,
            onFilterChanged: (squareOnly: Boolean) -> Unit
        ): ArtworkPickerDialog {
            val dialog = ArtworkPickerDialog(
                context, ArtworkType.ICON, searchResult,
                onOptionSelected, onSkip, onCancel, onFilterChanged, initialSquareOnly
            )
            dialog.show()
            return dialog
        }

        /**
         * Show the artwork picker dialog with both skip and filter support.
         * @param onOptionSelected Called when user selects an option. For non-square images,
         *                         the caller should launch ImageCropActivity.
         * @param initialSquareOnly Initial state of the filter toggle (default true).
         *                          Set to false if showing non-square results initially.
         * @param onSkip Called when user clicks Skip to move to next game
         * @param onCancel Called when user clicks Cancel to stop the bulk operation
         * @param onFilterChanged Called when user changes the filter (square only vs all results).
         *                        The caller should fetch new results and call updateSearchResult().
         */
        fun showWithSkipAndFilter(
            context: Context,
            artworkType: ArtworkType,
            searchResult: ArtworkSearchResult,
            initialSquareOnly: Boolean = true,
            onOptionSelected: (ArtworkOption) -> Unit,
            onSkip: () -> Unit,
            onCancel: () -> Unit,
            onFilterChanged: (squareOnly: Boolean) -> Unit
        ): ArtworkPickerDialog {
            val dialog = ArtworkPickerDialog(
                context, artworkType, searchResult,
                onOptionSelected, onSkip, onCancel, onFilterChanged, initialSquareOnly
            )
            dialog.show()
            return dialog
        }

        /**
         * Check if an artwork option is square (width equals height).
         */
        fun isSquare(option: ArtworkOption): Boolean {
            return option.width > 0 && option.height > 0 && option.width == option.height
        }
    }
}
