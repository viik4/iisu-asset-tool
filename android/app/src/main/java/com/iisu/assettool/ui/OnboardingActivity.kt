package com.iisu.assettool.ui

import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.viewpager2.adapter.FragmentStateAdapter
import androidx.viewpager2.widget.ViewPager2
import com.google.android.material.button.MaterialButton
import com.google.android.material.tabs.TabLayout
import com.google.android.material.tabs.TabLayoutMediator
import com.iisu.assettool.R

/**
 * Onboarding activity shown on first launch or after a major version update.
 * Uses ViewPager2 with swipeable pages highlighting new features.
 */
class OnboardingActivity : AppCompatActivity() {

    private lateinit var viewPager: ViewPager2
    private lateinit var dotsIndicator: TabLayout
    private lateinit var btnBack: MaterialButton
    private lateinit var btnNext: MaterialButton
    private lateinit var btnSkip: MaterialButton

    companion object {
        private const val PREFS_NAME = "iisu_asset_tool_prefs"
        private const val PREF_LAST_SEEN_VERSION = "last_seen_version"
        private const val CURRENT_VERSION = "2.0.1"

        fun shouldShowOnboarding(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val lastSeen = prefs.getString(PREF_LAST_SEEN_VERSION, "0.0.0") ?: "0.0.0"
            return compareVersions(lastSeen, CURRENT_VERSION) < 0
        }

        fun markOnboardingComplete(context: Context) {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putString(PREF_LAST_SEEN_VERSION, CURRENT_VERSION).apply()
        }

        private fun compareVersions(v1: String, v2: String): Int {
            val parts1 = v1.split(".").map { it.toIntOrNull() ?: 0 }
            val parts2 = v2.split(".").map { it.toIntOrNull() ?: 0 }
            for (i in 0 until maxOf(parts1.size, parts2.size)) {
                val a = parts1.getOrElse(i) { 0 }
                val b = parts2.getOrElse(i) { 0 }
                if (a != b) return a.compareTo(b)
            }
            return 0
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_onboarding)

        viewPager = findViewById(R.id.viewPager)
        dotsIndicator = findViewById(R.id.dotsIndicator)
        btnBack = findViewById(R.id.btnBack)
        btnNext = findViewById(R.id.btnNext)
        btnSkip = findViewById(R.id.btnSkip)

        setupViewPager()
        setupButtons()
    }

    private fun setupViewPager() {
        viewPager.adapter = OnboardingPagerAdapter(this)

        TabLayoutMediator(dotsIndicator, viewPager) { _, _ -> }.attach()

        viewPager.registerOnPageChangeCallback(
            object : ViewPager2.OnPageChangeCallback() {
                override fun onPageSelected(position: Int) {
                    updateButtons(position)
                }
            }
        )
    }

    private fun setupButtons() {
        btnBack.setOnClickListener {
            val current = viewPager.currentItem
            if (current > 0) viewPager.currentItem = current - 1
        }

        btnNext.setOnClickListener {
            val current = viewPager.currentItem
            if (current < 3) {
                viewPager.currentItem = current + 1
            } else {
                markOnboardingComplete(this)
                finish()
            }
        }

        btnSkip.setOnClickListener {
            markOnboardingComplete(this)
            finish()
        }

        updateButtons(0)
    }

    private fun updateButtons(position: Int) {
        btnBack.visibility = if (position > 0) View.VISIBLE else View.INVISIBLE
        btnNext.text = if (position == 3) "Get Started" else "Next"
    }

    private inner class OnboardingPagerAdapter(activity: AppCompatActivity) :
        FragmentStateAdapter(activity) {
        override fun getItemCount(): Int = 4
        override fun createFragment(position: Int): Fragment =
            OnboardingPageFragment.newInstance(position)
    }
}

/**
 * Single page within the onboarding flow.
 */
class OnboardingPageFragment : Fragment() {

    companion object {
        private const val ARG_PAGE = "page"

        fun newInstance(page: Int): OnboardingPageFragment {
            return OnboardingPageFragment().apply {
                arguments = Bundle().apply { putInt(ARG_PAGE, page) }
            }
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        val view = inflater.inflate(R.layout.fragment_onboarding_page, container, false)
        val page = arguments?.getInt(ARG_PAGE) ?: 0

        val title = view.findViewById<TextView>(R.id.onboardingTitle)
        val subtitle = view.findViewById<TextView>(R.id.onboardingSubtitle)
        val icon = view.findViewById<ImageView>(R.id.onboardingIcon)

        when (page) {
            0 -> {
                title.text = "Welcome to v2.0"
                subtitle.text = "A major update with a new Workshop, shareable per-game links, and full hero & logo support."
                icon.setImageResource(R.drawable.app_logo)
            }
            1 -> {
                title.text = "Workshop"
                subtitle.text = "The Community DB is now the Workshop. Browse, download, and apply icons, heroes, and logos from the community library."
                icon.setImageResource(R.drawable.ic_existing_assets)
            }
            2 -> {
                title.text = "Per-Game Links"
                subtitle.text = "Every game in the Workshop now has its own shareable URL. Send a link to jump straight to any game\u0027s assets."
                icon.setImageResource(R.drawable.ic_icons)
            }
            3 -> {
                title.text = "Ready to Go"
                subtitle.text = "Your library and settings are exactly where you left them. Jump in and start creating!"
                icon.setImageResource(R.drawable.ic_iisu_home)
            }
        }

        return view
    }
}
