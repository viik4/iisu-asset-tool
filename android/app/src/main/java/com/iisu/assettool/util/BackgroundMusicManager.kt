package com.iisu.assettool.util

import android.content.Context
import android.media.MediaPlayer
import android.util.Log
import com.iisu.assettool.R
import com.iisu.assettool.ui.SettingsFragment

/**
 * Singleton manager for background music playback.
 *
 * Plays the iiSU OST (audio.mp3) from res/raw when enabled in settings.
 * Music by Thaddeus Silva.
 */
object BackgroundMusicManager {
    private const val TAG = "BackgroundMusicManager"

    private var mediaPlayer: MediaPlayer? = null
    private var isInitialized = false
    private var isPaused = false
    private var preDuckVolume: Int? = null  // Original volume before ducking

    /**
     * Initialize and start background music if enabled in settings.
     * Should be called from MainActivity.onCreate()
     */
    fun initialize(context: Context) {
        if (isInitialized) {
            Log.d(TAG, "Already initialized")
            return
        }

        val enabled = SettingsFragment.isMusicEnabled(context)
        if (!enabled) {
            Log.d(TAG, "Music is disabled in settings")
            return
        }

        try {
            // Check if raw resource exists - try audio.mp3 first, then audio.wav
            var resId = context.resources.getIdentifier("audio", "raw", context.packageName)
            var audioFormat = "mp3"

            if (resId == 0) {
                // Try wav format
                resId = context.resources.getIdentifier("audio_wav", "raw", context.packageName)
                audioFormat = "wav"
            }

            if (resId == 0) {
                Log.w(TAG, "No audio file found in res/raw (tried audio.mp3 and audio_wav.wav) - background music disabled")
                return
            }

            mediaPlayer = MediaPlayer.create(context, resId)?.apply {
                isLooping = true

                // Set initial volume from settings
                val volume = SettingsFragment.getMusicVolume(context)
                setVolumePercent(volume)

                start()
                Log.d(TAG, "Background music started (format: $audioFormat)")
            }

            isInitialized = true
            isPaused = false
        } catch (e: Exception) {
            Log.e(TAG, "Error initializing background music", e)
            release()
        }
    }

    /**
     * Set volume as a percentage (0-100)
     */
    fun setVolumePercent(percent: Int) {
        val volume = percent.coerceIn(0, 100) / 100f
        mediaPlayer?.setVolume(volume, volume)
        Log.d(TAG, "Volume set to $percent%")
    }

    /**
     * Pause playback (e.g., when app goes to background)
     */
    fun pause() {
        if (mediaPlayer?.isPlaying == true) {
            mediaPlayer?.pause()
            isPaused = true
            Log.d(TAG, "Background music paused")
        }
    }

    /**
     * Resume playback (e.g., when app returns to foreground)
     */
    fun resume(context: Context) {
        val enabled = SettingsFragment.isMusicEnabled(context)

        if (!enabled) {
            // Music was disabled while paused - release resources
            if (isInitialized) {
                release()
            }
            return
        }

        if (!isInitialized) {
            // Music was enabled while paused - initialize
            initialize(context)
            return
        }

        if (isPaused && mediaPlayer != null) {
            // Update volume in case it changed
            val volume = SettingsFragment.getMusicVolume(context)
            setVolumePercent(volume)

            mediaPlayer?.start()
            isPaused = false
            Log.d(TAG, "Background music resumed")
        }
    }

    /**
     * Stop and release media player resources
     */
    fun release() {
        try {
            mediaPlayer?.stop()
            mediaPlayer?.release()
        } catch (e: Exception) {
            Log.e(TAG, "Error releasing media player", e)
        }
        mediaPlayer = null
        isInitialized = false
        isPaused = false
        Log.d(TAG, "Background music released")
    }

    /**
     * Toggle music on/off based on settings.
     * Call this when the music enabled setting changes.
     */
    fun toggleMusic(context: Context, enabled: Boolean) {
        if (enabled) {
            if (!isInitialized) {
                initialize(context)
            } else if (isPaused) {
                resume(context)
            }
        } else {
            release()
        }
    }

    /**
     * Check if music is currently playing
     */
    fun isPlaying(): Boolean {
        return mediaPlayer?.isPlaying == true
    }

    /**
     * Duck (lower) the background music volume for preview playback.
     * Saves the current volume and drops to ~20% of it (minimum 5%).
     * Call unduck() to restore the original volume.
     */
    fun duck(context: Context) {
        if (!isPlaying()) return
        if (preDuckVolume != null) return  // Already ducked

        val currentVolume = SettingsFragment.getMusicVolume(context)
        preDuckVolume = currentVolume
        val duckedVolume = maxOf(5, currentVolume / 5)
        setVolumePercent(duckedVolume)
        Log.d(TAG, "Ducked music from $currentVolume% to $duckedVolume%")
    }

    /**
     * Restore background music volume after ducking.
     */
    fun unduck() {
        preDuckVolume?.let { originalVolume ->
            setVolumePercent(originalVolume)
            Log.d(TAG, "Unducked music, restored to $originalVolume%")
        }
        preDuckVolume = null
    }
}
