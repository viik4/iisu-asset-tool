package com.iisu.assettool.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentAndroidAppDetailBinding
import com.iisu.assettool.util.AndroidAppInfo
import com.iisu.assettool.util.ArtworkScraper
import com.iisu.assettool.util.GameInfo
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

/**
 * Fragment for viewing and editing assets for a single Android app.
 * Allows generating icon, hero, and logo artwork.
 */
class AndroidAppDetailFragment : Fragment() {

    private var _binding: FragmentAndroidAppDetailBinding? = null
    private val binding get() = _binding!!

    private lateinit var artworkScraper: ArtworkScraper
    private var packageName: String = ""
    private var appInfo: AndroidAppInfo? = null
    private var isScraping: Boolean = false

    // Activity result launchers for picking images
    private val pickIconLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedImage(it, AssetType.ICON) } }

    private val pickHeroLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedImage(it, AssetType.HERO) } }

    private val pickLogoLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { handlePickedImage(it, AssetType.LOGO) } }

    private enum class AssetType { ICON, HERO, LOGO }

    companion object {
        private const val ARG_PACKAGE_NAME = "package_name"
        private const val TAG = "AndroidAppDetailFragment"

        fun newInstance(packageName: String): AndroidAppDetailFragment {
            return AndroidAppDetailFragment().apply {
                arguments = Bundle().apply {
                    putString(ARG_PACKAGE_NAME, packageName)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        arguments?.let {
            packageName = it.getString(ARG_PACKAGE_NAME, "")
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentAndroidAppDetailBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        artworkScraper = ArtworkScraper(requireContext())

        // Load SteamGridDB API key from settings
        val sgdbApiKey = SettingsFragment.getSteamGridDBApiKey(requireContext())
        if (sgdbApiKey != null) {
            artworkScraper.setSteamGridDBApiKey(sgdbApiKey)
        }

        setupUI()
        loadAppInfo()
    }

    private fun setupUI() {
        // Back button
        binding.btnBack.setOnClickListener {
            parentFragmentManager.popBackStack()
        }

        // Generate buttons
        binding.btnGenerateIcon.setOnClickListener {
            generateIcon()
        }

        binding.btnGenerateHero.setOnClickListener {
            generateHero()
        }

        binding.btnGenerateLogo.setOnClickListener {
            generateLogo()
        }

        binding.btnGenerateAll.setOnClickListener {
            generateAllAssets()
        }

        // Upload buttons for local file selection
        binding.btnUploadIcon.setOnClickListener {
            pickIconLauncher.launch("image/*")
        }

        binding.btnUploadHero.setOnClickListener {
            pickHeroLauncher.launch("image/*")
        }

        binding.btnUploadLogo.setOnClickListener {
            pickLogoLauncher.launch("image/*")
        }
    }

    /**
     * Handle a picked image from the gallery
     */
    private fun handlePickedImage(uri: Uri, assetType: AssetType) {
        val app = appInfo ?: return

        viewLifecycleOwner.lifecycleScope.launch {
            setScrapingState(true)

            val success = withContext(Dispatchers.IO) {
                try {
                    val inputStream = requireContext().contentResolver.openInputStream(uri)
                    if (inputStream == null) {
                        Log.e(TAG, "Failed to open input stream for URI: $uri")
                        return@withContext false
                    }

                    val bitmap = BitmapFactory.decodeStream(inputStream)
                    inputStream.close()

                    if (bitmap == null) {
                        Log.e(TAG, "Failed to decode bitmap from URI: $uri")
                        return@withContext false
                    }

                    // Determine the target file based on asset type
                    val targetFile = when (assetType) {
                        AssetType.ICON -> File(app.folder, "icon.png")
                        AssetType.HERO -> File(app.folder, "hero.png")
                        AssetType.LOGO -> File(app.folder, "logo.png")
                    }

                    // Ensure parent directory exists
                    targetFile.parentFile?.mkdirs()

                    // Save the bitmap as PNG
                    FileOutputStream(targetFile).use { out ->
                        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
                    }

                    Log.d(TAG, "Saved ${assetType.name.lowercase()} to ${targetFile.absolutePath}")
                    true
                } catch (e: Exception) {
                    Log.e(TAG, "Error saving ${assetType.name.lowercase()}", e)
                    false
                }
            }

            if (_binding == null) return@launch
            setScrapingState(false)

            val assetName = assetType.name.lowercase().replaceFirstChar { it.uppercase() }
            if (success) {
                Toast.makeText(requireContext(), "$assetName saved!", Toast.LENGTH_SHORT).show()
                refreshAppInfo()
            } else {
                Toast.makeText(requireContext(), "Failed to save $assetName", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun loadAppInfo() {
        viewLifecycleOwner.lifecycleScope.launch {
            val apps = withContext(Dispatchers.IO) {
                IisuDirectoryManager.getAndroidApps()
            }

            appInfo = apps.find { it.packageName == packageName }

            if (_binding == null) return@launch

            appInfo?.let { app ->
                updateUI(app)
            } ?: run {
                Toast.makeText(requireContext(), "App not found: $packageName", Toast.LENGTH_SHORT).show()
                parentFragmentManager.popBackStack()
            }
        }
    }

    private fun updateUI(app: AndroidAppInfo) {
        // Header info
        binding.textAppName.text = app.displayName
        binding.textPackageName.text = app.packageName

        // App icon in header
        if (app.iconFile != null && app.iconFile.exists()) {
            try {
                val bitmap = BitmapFactory.decodeFile(app.iconFile.absolutePath)
                if (bitmap != null) {
                    binding.imageAppIcon.setImageBitmap(bitmap)
                }
            } catch (e: Exception) {
                binding.imageAppIcon.setImageResource(R.drawable.ic_android_app)
            }
        } else {
            binding.imageAppIcon.setImageResource(R.drawable.ic_android_app)
        }

        // Asset status
        val missingCount = app.missingCount
        binding.textAssetStatus.text = if (missingCount > 0) {
            "$missingCount missing assets"
        } else {
            "All assets present"
        }
        binding.textAssetStatus.setTextColor(
            if (missingCount > 0) resources.getColor(R.color.accent_cyan, null)
            else resources.getColor(R.color.status_success, null)
        )

        // Icon preview
        if (app.hasIcon && app.iconFile != null) {
            try {
                val bitmap = BitmapFactory.decodeFile(app.iconFile.absolutePath)
                if (bitmap != null) {
                    binding.imageIconPreview.setImageBitmap(bitmap)
                }
            } catch (e: Exception) {
                binding.imageIconPreview.setImageResource(R.drawable.ic_icons)
            }
            binding.textIconStatus.text = "Present"
            binding.textIconStatus.setTextColor(resources.getColor(R.color.status_success, null))
        } else {
            binding.imageIconPreview.setImageResource(R.drawable.ic_icons)
            binding.textIconStatus.text = "Missing"
            binding.textIconStatus.setTextColor(resources.getColor(R.color.accent_cyan, null))
        }

        // Hero preview
        if (app.hasHero && app.heroFile != null) {
            try {
                val bitmap = BitmapFactory.decodeFile(app.heroFile.absolutePath)
                if (bitmap != null) {
                    binding.imageHeroPreview.setImageBitmap(bitmap)
                }
            } catch (e: Exception) {
                binding.imageHeroPreview.setImageResource(R.drawable.ic_hero)
            }
            binding.textHeroStatus.text = "Present"
            binding.textHeroStatus.setTextColor(resources.getColor(R.color.status_success, null))
        } else {
            binding.imageHeroPreview.setImageResource(R.drawable.ic_hero)
            binding.textHeroStatus.text = "Missing"
            binding.textHeroStatus.setTextColor(resources.getColor(R.color.accent_cyan, null))
        }

        // Logo preview
        if (app.hasLogo && app.logoFile != null) {
            try {
                val bitmap = BitmapFactory.decodeFile(app.logoFile.absolutePath)
                if (bitmap != null) {
                    binding.imageLogoPreview.setImageBitmap(bitmap)
                }
            } catch (e: Exception) {
                binding.imageLogoPreview.setImageResource(R.drawable.ic_logo)
            }
            binding.textLogoStatus.text = "Present"
            binding.textLogoStatus.setTextColor(resources.getColor(R.color.status_success, null))
        } else {
            binding.imageLogoPreview.setImageResource(R.drawable.ic_logo)
            binding.textLogoStatus.text = "Missing"
            binding.textLogoStatus.setTextColor(resources.getColor(R.color.accent_cyan, null))
        }
    }

    /**
     * Convert AndroidAppInfo to GameInfo for use with existing artwork scraper
     */
    private fun toGameInfo(app: AndroidAppInfo): GameInfo {
        return GameInfo(
            name = app.displayName,
            folder = app.folder,
            hasIcon = app.hasIcon,
            hasHero = app.hasHero,
            hasLogo = app.hasLogo,
            iconFile = app.iconFile,
            heroFile = app.heroFile,
            logoFile = app.logoFile
        )
    }

    private fun generateIcon() {
        val app = appInfo ?: return
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(requireContext(), "Searching for icons...", Toast.LENGTH_SHORT).show()
        setScrapingState(true)

        val gameInfo = toGameInfo(app)
        val squareOnly = SettingsFragment.isSquareIconsOnly(requireContext())

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchIconOptions(gameInfo, "android", squareOnly)

            if (_binding == null) return@launch
            setScrapingState(false)

            if (searchResult.options.isEmpty()) {
                Toast.makeText(requireContext(), "No icons found for ${app.displayName}", Toast.LENGTH_SHORT).show()
                return@launch
            }

            // Show picker dialog
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.ICON,
                    searchResult = searchResult
                ) { selectedOption ->
                    viewLifecycleOwner.lifecycleScope.launch iconSave@{
                        setScrapingState(true)
                        val success = artworkScraper.saveIconFromOption(selectedOption, gameInfo, "android")
                        setScrapingState(false)

                        if (_binding == null) return@iconSave

                        if (success) {
                            Toast.makeText(requireContext(), "Icon saved!", Toast.LENGTH_SHORT).show()
                            refreshAppInfo()
                        } else {
                            Toast.makeText(requireContext(), "Failed to save icon", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
        }
    }

    private fun generateHero() {
        val app = appInfo ?: return
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(requireContext(), "Searching for heroes...", Toast.LENGTH_SHORT).show()
        setScrapingState(true)

        val gameInfo = toGameInfo(app)

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchHeroOptions(gameInfo, "android")

            if (_binding == null) return@launch
            setScrapingState(false)

            if (searchResult.options.isEmpty()) {
                Toast.makeText(requireContext(), "No heroes found for ${app.displayName}", Toast.LENGTH_SHORT).show()
                return@launch
            }

            // Show picker dialog
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.HERO,
                    searchResult = searchResult
                ) { selectedOption ->
                    viewLifecycleOwner.lifecycleScope.launch heroSave@{
                        setScrapingState(true)
                        val success = artworkScraper.saveHeroFromOption(selectedOption, gameInfo)
                        setScrapingState(false)

                        if (_binding == null) return@heroSave

                        if (success) {
                            Toast.makeText(requireContext(), "Hero saved!", Toast.LENGTH_SHORT).show()
                            refreshAppInfo()
                        } else {
                            Toast.makeText(requireContext(), "Failed to save hero", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
        }
    }

    private fun generateLogo() {
        val app = appInfo ?: return
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(requireContext(), "Searching for logos...", Toast.LENGTH_SHORT).show()
        setScrapingState(true)

        val gameInfo = toGameInfo(app)

        viewLifecycleOwner.lifecycleScope.launch {
            val searchResult = artworkScraper.searchLogoOptions(gameInfo, "android")

            if (_binding == null) return@launch
            setScrapingState(false)

            if (searchResult.options.isEmpty()) {
                Toast.makeText(requireContext(), "No logos found for ${app.displayName}", Toast.LENGTH_SHORT).show()
                return@launch
            }

            // Show picker dialog
            withContext(Dispatchers.Main) {
                if (_binding == null) return@withContext

                ArtworkPickerDialog.show(
                    context = requireContext(),
                    artworkType = ArtworkPickerDialog.ArtworkType.LOGO,
                    searchResult = searchResult
                ) { selectedOption ->
                    viewLifecycleOwner.lifecycleScope.launch logoSave@{
                        setScrapingState(true)
                        val success = artworkScraper.saveLogoFromOption(selectedOption, gameInfo)
                        setScrapingState(false)

                        if (_binding == null) return@logoSave

                        if (success) {
                            Toast.makeText(requireContext(), "Logo saved!", Toast.LENGTH_SHORT).show()
                            refreshAppInfo()
                        } else {
                            Toast.makeText(requireContext(), "Failed to save logo", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
        }
    }

    private fun generateAllAssets() {
        val app = appInfo ?: return
        if (isScraping) {
            Toast.makeText(requireContext(), "Scraping in progress...", Toast.LENGTH_SHORT).show()
            return
        }

        Toast.makeText(requireContext(), "Generating all assets...", Toast.LENGTH_SHORT).show()
        setScrapingState(true)

        val gameInfo = toGameInfo(app)

        viewLifecycleOwner.lifecycleScope.launch {
            // Generate icon
            val iconSuccess = withContext(Dispatchers.IO) {
                artworkScraper.scrapeIcon(gameInfo, "android")
            }

            if (_binding == null) return@launch

            // Generate hero
            val heroSuccess = withContext(Dispatchers.IO) {
                artworkScraper.scrapeHero(gameInfo, "android")
            }

            if (_binding == null) return@launch

            // Generate logo
            val logoSuccess = withContext(Dispatchers.IO) {
                artworkScraper.scrapeLogo(gameInfo, "android")
            }

            if (_binding == null) return@launch

            setScrapingState(false)

            val successCount = listOf(iconSuccess, heroSuccess, logoSuccess).count { it }
            Toast.makeText(
                requireContext(),
                "Generated $successCount/3 assets for ${app.displayName}",
                Toast.LENGTH_LONG
            ).show()

            refreshAppInfo()
        }
    }

    private fun setScrapingState(scraping: Boolean) {
        isScraping = scraping

        if (_binding == null) return

        binding.progressBar.visibility = if (scraping) View.VISIBLE else View.GONE

        val enabled = !scraping
        binding.btnGenerateIcon.isEnabled = enabled
        binding.btnGenerateHero.isEnabled = enabled
        binding.btnGenerateLogo.isEnabled = enabled
        binding.btnGenerateAll.isEnabled = enabled
        binding.btnUploadIcon.isEnabled = enabled
        binding.btnUploadHero.isEnabled = enabled
        binding.btnUploadLogo.isEnabled = enabled

        binding.btnGenerateIcon.alpha = if (enabled) 1.0f else 0.5f
        binding.btnGenerateHero.alpha = if (enabled) 1.0f else 0.5f
        binding.btnGenerateLogo.alpha = if (enabled) 1.0f else 0.5f
        binding.btnGenerateAll.alpha = if (enabled) 1.0f else 0.5f
        binding.btnUploadIcon.alpha = if (enabled) 1.0f else 0.5f
        binding.btnUploadHero.alpha = if (enabled) 1.0f else 0.5f
        binding.btnUploadLogo.alpha = if (enabled) 1.0f else 0.5f
    }

    private fun refreshAppInfo() {
        viewLifecycleOwner.lifecycleScope.launch {
            val apps = withContext(Dispatchers.IO) {
                IisuDirectoryManager.getAndroidApps()
            }

            appInfo = apps.find { it.packageName == packageName }

            if (_binding == null) return@launch

            appInfo?.let { app ->
                updateUI(app)
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
