package com.iisu.assettool.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.appcompat.app.AppCompatDelegate
import androidx.fragment.app.Fragment
import com.google.android.material.slider.Slider
import com.iisu.assettool.BuildConfig
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentSettingsDisplayBinding
import com.iisu.assettool.util.BackgroundMusicManager

/**
 * Display Options settings tab.
 * Contains: Theme selection, Background Music controls, About section
 */
class SettingsDisplayFragment : Fragment() {

    private var _binding: FragmentSettingsDisplayBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsDisplayBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupThemeSelection()
        setupMusicControls()
        setupAboutSection()
    }

    private fun setupThemeSelection() {
        // Set current theme selection
        when (AppCompatDelegate.getDefaultNightMode()) {
            AppCompatDelegate.MODE_NIGHT_YES -> binding.radioThemeDark.isChecked = true
            AppCompatDelegate.MODE_NIGHT_NO -> binding.radioThemeLight.isChecked = true
            else -> binding.radioThemeSystem.isChecked = true
        }

        binding.radioGroupTheme.setOnCheckedChangeListener { _, checkedId ->
            val mode = when (checkedId) {
                R.id.radioThemeDark -> AppCompatDelegate.MODE_NIGHT_YES
                R.id.radioThemeLight -> AppCompatDelegate.MODE_NIGHT_NO
                else -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            }
            AppCompatDelegate.setDefaultNightMode(mode)
        }
    }

    private fun setupMusicControls() {
        val context = requireContext()

        // Set initial state
        val musicEnabled = SettingsFragment.isMusicEnabled(context)
        val volume = SettingsFragment.getMusicVolume(context)

        binding.switchMusicEnabled.isChecked = musicEnabled
        binding.sliderVolume.value = volume.toFloat()
        binding.textVolumePercent.text = "$volume%"

        // Show/hide volume slider based on enabled state
        updateVolumeSliderVisibility(musicEnabled)

        // Music enabled switch listener
        binding.switchMusicEnabled.setOnCheckedChangeListener { _, isChecked ->
            SettingsFragment.setMusicEnabled(context, isChecked)
            updateVolumeSliderVisibility(isChecked)

            // Toggle music playback
            BackgroundMusicManager.toggleMusic(context, isChecked)
        }

        // Volume slider listener
        binding.sliderVolume.addOnChangeListener { _, value, fromUser ->
            if (fromUser) {
                val volumeInt = value.toInt()
                binding.textVolumePercent.text = "$volumeInt%"
                SettingsFragment.setMusicVolume(context, volumeInt)

                // Update playback volume in real-time
                BackgroundMusicManager.setVolumePercent(volumeInt)
            }
        }

        // Also update when slider stops
        binding.sliderVolume.addOnSliderTouchListener(object : Slider.OnSliderTouchListener {
            override fun onStartTrackingTouch(slider: Slider) {}

            override fun onStopTrackingTouch(slider: Slider) {
                val volumeInt = slider.value.toInt()
                SettingsFragment.setMusicVolume(context, volumeInt)
                BackgroundMusicManager.setVolumePercent(volumeInt)
            }
        })
    }

    private fun updateVolumeSliderVisibility(enabled: Boolean) {
        binding.layoutVolumeSlider.alpha = if (enabled) 1f else 0.5f
        binding.sliderVolume.isEnabled = enabled
    }

    private fun setupAboutSection() {
        binding.textVersion.text = getString(R.string.settings_version, BuildConfig.VERSION_NAME)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
