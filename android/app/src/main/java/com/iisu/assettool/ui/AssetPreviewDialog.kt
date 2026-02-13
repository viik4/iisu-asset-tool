package com.iisu.assettool.ui

import android.app.Dialog
import android.content.Context
import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.Window
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.tabs.TabLayout
import com.iisu.assettool.R
import com.iisu.assettool.util.GameInfo
import java.io.File

/**
 * Dialog for previewing existing assets (icon, hero, logo) for a game.
 * Allows viewing each asset type in a tabbed interface.
 */
class AssetPreviewDialog(
    context: Context,
    private val game: GameInfo,
    private val onGenerateIcon: (() -> Unit)? = null,
    private val onGenerateHero: (() -> Unit)? = null,
    private val onGenerateLogo: (() -> Unit)? = null,
    private val onUploadIcon: (() -> Unit)? = null,
    private val onUploadHero: (() -> Unit)? = null,
    private val onUploadLogo: (() -> Unit)? = null
) : Dialog(context, R.style.Theme_IisuAssetTool_Dialog) {

    private lateinit var tabLayout: TabLayout
    private lateinit var imagePreview: ImageView
    private lateinit var textAssetInfo: TextView
    private lateinit var textNoAsset: TextView
    private lateinit var btnGenerate: MaterialButton
    private lateinit var btnUpload: MaterialButton

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestWindowFeature(Window.FEATURE_NO_TITLE)
        setContentView(R.layout.dialog_asset_preview)

        // Set dialog width to 90% of screen width
        window?.setLayout(
            (context.resources.displayMetrics.widthPixels * 0.9).toInt(),
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        )

        setupViews()
        setupTabs()

        // Show icon by default
        showAsset(AssetType.ICON)
    }

    private fun setupViews() {
        tabLayout = findViewById(R.id.tabLayoutAssets)
        imagePreview = findViewById(R.id.imagePreview)
        textAssetInfo = findViewById(R.id.textAssetInfo)
        textNoAsset = findViewById(R.id.textNoAsset)
        btnGenerate = findViewById(R.id.btnGenerate)
        btnUpload = findViewById(R.id.btnUpload)

        // Set game title
        findViewById<TextView>(R.id.textGameTitle).text = game.displayName

        // Close button
        findViewById<MaterialButton>(R.id.btnClose).setOnClickListener {
            dismiss()
        }
    }

    private fun setupTabs() {
        // Add tabs for each asset type
        tabLayout.addTab(tabLayout.newTab().setText("Icon"))
        tabLayout.addTab(tabLayout.newTab().setText("Hero"))
        tabLayout.addTab(tabLayout.newTab().setText("Logo"))

        // Set indicator color based on asset availability
        updateTabIndicators()

        tabLayout.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab?) {
                when (tab?.position) {
                    0 -> showAsset(AssetType.ICON)
                    1 -> showAsset(AssetType.HERO)
                    2 -> showAsset(AssetType.LOGO)
                }
            }

            override fun onTabUnselected(tab: TabLayout.Tab?) {}
            override fun onTabReselected(tab: TabLayout.Tab?) {}
        })
    }

    private fun updateTabIndicators() {
        // Color tabs based on asset availability
        for (i in 0 until tabLayout.tabCount) {
            val tab = tabLayout.getTabAt(i)
            val hasAsset = when (i) {
                0 -> game.hasIcon
                1 -> game.hasHero
                2 -> game.hasLogo
                else -> false
            }
            // Tab text color will indicate status
            tab?.view?.let { tabView ->
                val textView = tabView.findViewById<TextView>(android.R.id.text1)
                textView?.setTextColor(
                    context.getColor(
                        if (hasAsset) R.color.accent_cyan else R.color.accent_magenta
                    )
                )
            }
        }
    }

    private fun showAsset(assetType: AssetType) {
        val (file, hasAsset, generateCallback, uploadCallback) = when (assetType) {
            AssetType.ICON -> Quadruple(game.iconFile, game.hasIcon, onGenerateIcon, onUploadIcon)
            AssetType.HERO -> Quadruple(game.heroFile, game.hasHero, onGenerateHero, onUploadHero)
            AssetType.LOGO -> Quadruple(game.logoFile, game.hasLogo, onGenerateLogo, onUploadLogo)
        }

        if (hasAsset && file != null && file.exists()) {
            // Show the asset
            val bitmap = BitmapFactory.decodeFile(file.absolutePath)
            if (bitmap != null) {
                imagePreview.setImageBitmap(bitmap)
                imagePreview.visibility = View.VISIBLE
                textNoAsset.visibility = View.GONE

                // Show asset info
                val fileSize = formatFileSize(file.length())
                val dimensions = "${bitmap.width} x ${bitmap.height}"
                textAssetInfo.text = "$dimensions | $fileSize"
                textAssetInfo.visibility = View.VISIBLE
            } else {
                showNoAsset(assetType)
            }
        } else {
            showNoAsset(assetType)
        }

        // Configure generate button
        btnGenerate.text = if (hasAsset) "Search" else "Search"
        btnGenerate.setOnClickListener {
            generateCallback?.invoke()
            dismiss()
        }
        btnGenerate.visibility = if (generateCallback != null) View.VISIBLE else View.GONE

        // Configure upload button
        btnUpload.setOnClickListener {
            uploadCallback?.invoke()
            dismiss()
        }
        btnUpload.visibility = if (uploadCallback != null) View.VISIBLE else View.GONE
    }

    private data class Quadruple<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)

    private fun showNoAsset(assetType: AssetType) {
        imagePreview.setImageResource(R.drawable.ic_missing_icon)
        imagePreview.visibility = View.VISIBLE
        textNoAsset.text = "No ${assetType.displayName.lowercase()} available"
        textNoAsset.visibility = View.VISIBLE
        textAssetInfo.visibility = View.GONE
    }

    private fun formatFileSize(bytes: Long): String {
        return when {
            bytes >= 1024 * 1024 -> String.format("%.1f MB", bytes / (1024.0 * 1024.0))
            bytes >= 1024 -> String.format("%.1f KB", bytes / 1024.0)
            else -> "$bytes B"
        }
    }

    enum class AssetType(val displayName: String) {
        ICON("Icon"),
        HERO("Hero"),
        LOGO("Logo")
    }

    companion object {
        fun show(
            context: Context,
            game: GameInfo,
            onGenerateIcon: (() -> Unit)? = null,
            onGenerateHero: (() -> Unit)? = null,
            onGenerateLogo: (() -> Unit)? = null,
            onUploadIcon: (() -> Unit)? = null,
            onUploadHero: (() -> Unit)? = null,
            onUploadLogo: (() -> Unit)? = null
        ) {
            AssetPreviewDialog(
                context = context,
                game = game,
                onGenerateIcon = onGenerateIcon,
                onGenerateHero = onGenerateHero,
                onGenerateLogo = onGenerateLogo,
                onUploadIcon = onUploadIcon,
                onUploadHero = onUploadHero,
                onUploadLogo = onUploadLogo
            ).show()
        }
    }
}
