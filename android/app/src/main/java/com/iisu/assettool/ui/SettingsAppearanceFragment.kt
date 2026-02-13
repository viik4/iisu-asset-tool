package com.iisu.assettool.ui

import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentSettingsAppearanceBinding

/**
 * Appearance Options settings tab.
 * Contains: API Keys (SteamGridDB, IGDB)
 */
class SettingsAppearanceFragment : Fragment() {

    private var _binding: FragmentSettingsAppearanceBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsAppearanceBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupApiKeys()
    }

    private fun setupApiKeys() {
        val prefs = requireContext().getSharedPreferences(
            SettingsFragment.PREFS_NAME,
            Context.MODE_PRIVATE
        )

        // Load existing API keys
        binding.editSgdbApiKey.setText(prefs.getString(SettingsFragment.PREF_SGDB_API_KEY, ""))
        binding.editIgdbClientId.setText(prefs.getString(SettingsFragment.PREF_IGDB_CLIENT_ID, ""))
        binding.editIgdbClientSecret.setText(prefs.getString(SettingsFragment.PREF_IGDB_CLIENT_SECRET, ""))

        // Save button
        binding.btnSaveApiKey.setOnClickListener {
            val sgdbKey = binding.editSgdbApiKey.text?.toString()?.trim() ?: ""
            val igdbClientId = binding.editIgdbClientId.text?.toString()?.trim() ?: ""
            val igdbClientSecret = binding.editIgdbClientSecret.text?.toString()?.trim() ?: ""

            prefs.edit()
                .putString(SettingsFragment.PREF_SGDB_API_KEY, sgdbKey)
                .putString(SettingsFragment.PREF_IGDB_CLIENT_ID, igdbClientId)
                .putString(SettingsFragment.PREF_IGDB_CLIENT_SECRET, igdbClientSecret)
                .apply()

            Toast.makeText(requireContext(), R.string.settings_keys_saved, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
