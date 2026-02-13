package com.iisu.assettool.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.viewpager2.adapter.FragmentStateAdapter
import com.google.android.material.tabs.TabLayoutMediator
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentIconsBinding

/**
 * Icons Fragment
 *
 * Combines Search (IconGenerator) and Custom functionality into a single tabbed interface.
 * Tab 1: Search - Find artwork for any game
 * Tab 2: Custom - Apply borders to your own images
 */
class IconsFragment : Fragment() {

    private var _binding: FragmentIconsBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentIconsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        setupViewPager()
    }

    private fun setupViewPager() {
        val adapter = IconsPagerAdapter(this)
        binding.viewPager.adapter = adapter

        // Disable swipe by default when scrolling through results
        binding.viewPager.isUserInputEnabled = true

        TabLayoutMediator(binding.tabLayout, binding.viewPager) { tab, position ->
            tab.text = when (position) {
                0 -> getString(R.string.icons_tab_search)
                1 -> getString(R.string.icons_tab_custom)
                else -> ""
            }
        }.attach()
    }

    /**
     * Enable or disable ViewPager swiping.
     * Used by child fragments to prevent accidental tab switches while scrolling.
     */
    fun setSwipeEnabled(enabled: Boolean) {
        _binding?.viewPager?.isUserInputEnabled = enabled
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    /**
     * ViewPager adapter for the Search and Custom tabs
     */
    private inner class IconsPagerAdapter(fragment: Fragment) : FragmentStateAdapter(fragment) {

        override fun getItemCount(): Int = 2

        override fun createFragment(position: Int): Fragment {
            return when (position) {
                0 -> IconGeneratorFragment()
                1 -> CustomImageFragment()
                else -> IconGeneratorFragment()
            }
        }
    }
}
