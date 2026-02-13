package com.iisu.assettool.ui

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import coil.load
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.iisu.assettool.R
import com.iisu.assettool.databinding.FragmentMusicBinding
import com.iisu.assettool.util.BackgroundMusicManager
import com.iisu.assettool.util.GameCache
import com.iisu.assettool.util.IisuDirectoryManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.supervisorScope
import kotlinx.coroutines.withContext
import org.jsoup.Jsoup
import java.io.File
import java.io.FileOutputStream
import java.net.URL
import java.net.URLEncoder

/**
 * Music Fragment (Soundbytes)
 *
 * Browse and download game music from KHInsider for use as soundbytes
 * (hover music) in iiSU Launcher.
 */
class MusicFragment : Fragment() {

    private var _binding: FragmentMusicBinding? = null
    private val binding get() = _binding!!

    private val KHINSIDER_BASE_URL = "https://downloads.khinsider.com"
    private val KHINSIDER_SEARCH_URL = "$KHINSIDER_BASE_URL/search"

    private var currentAlbums: MutableList<Album> = mutableListOf()
    private var mediaPlayer: MediaPlayer? = null
    private var isPlaying = false
    private var currentPreviewTrack: Track? = null

    private lateinit var albumAdapter: AlbumAdapter

    // Views for empty state
    private var layoutEmptyState: android.widget.LinearLayout? = null

    data class Album(
        val title: String,
        val url: String,
        val gameName: String,
        val isGamerip: Boolean = false,
        var coverUrl: String? = null,
        var trackCount: Int = 0
    )

    data class Track(
        val title: String,
        val trackNumber: Int,
        val duration: String,
        val pageUrl: String,
        var downloadUrl: String? = null
    )

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentMusicBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Get reference to empty state layout
        layoutEmptyState = view.findViewById(R.id.layoutEmptyState)

        setupAlbumGrid()
        setupPlatformSpinner()
        setupSearchButton()
        setupGameripCheckbox()

        // Show empty state initially
        updateEmptyState(true)
    }

    private fun setupAlbumGrid() {
        albumAdapter = AlbumAdapter(
            onAlbumClick = { album -> showAlbumTracks(album) },
            onCoverNeeded = { album, position -> loadAlbumCover(album, position) }
        )

        binding.recyclerAlbums.apply {
            layoutManager = GridLayoutManager(context, 5)
            adapter = albumAdapter
        }
    }

    private fun setupPlatformSpinner() {
        // Platform filter removed - KHInsider doesn't support platform filtering
        // Platform layout is now hidden in XML (visibility="gone")
    }

    private fun setupSearchButton() {
        binding.buttonSearch.setOnClickListener {
            val query = binding.editSearch.text.toString().trim()
            if (query.isNotEmpty()) {
                hideKeyboard()
                searchSoundtracks(query)
            } else {
                Toast.makeText(context, "Enter a game name", Toast.LENGTH_SHORT).show()
            }
        }

        // Also search on Enter key
        binding.editSearch.setOnEditorActionListener { _, _, _ ->
            binding.buttonSearch.performClick()
            true
        }
    }

    private fun hideKeyboard() {
        val imm = context?.getSystemService(Context.INPUT_METHOD_SERVICE) as? android.view.inputmethod.InputMethodManager
        binding.editSearch.clearFocus()
        imm?.hideSoftInputFromWindow(binding.editSearch.windowToken, 0)
    }

    private fun setupGameripCheckbox() {
        // Gamerip filter removed - now using KHInsider's default popularity sorting
        binding.checkboxGamerip.isChecked = false
    }

    private fun updateEmptyState(isEmpty: Boolean) {
        layoutEmptyState?.visibility = if (isEmpty) View.VISIBLE else View.GONE
        binding.recyclerAlbums.visibility = if (isEmpty) View.GONE else View.VISIBLE
    }

    private fun searchSoundtracks(query: String) {
        _binding?.progressBar?.visibility = View.VISIBLE
        _binding?.buttonSearch?.isEnabled = false
        _binding?.textStatus?.text = "Searching for '$query'..."

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val albums = withContext(Dispatchers.IO) {
                    searchKhinsider(query)
                }

                if (_binding == null) return@launch

                currentAlbums = albums.toMutableList()
                albumAdapter.submitList(currentAlbums.toList())

                // Update empty state visibility
                updateEmptyState(albums.isEmpty())

                _binding?.textStatus?.text = if (albums.isEmpty()) {
                    "No results found"
                } else {
                    "${albums.size} album(s) found - loading covers..."
                }

                // Load covers for all albums in parallel
                if (albums.isNotEmpty()) {
                    loadAllAlbumCovers()
                }

            } catch (e: Exception) {
                _binding?.textStatus?.text = "Search failed: ${e.message}"
                context?.let { Toast.makeText(it, "Search failed", Toast.LENGTH_SHORT).show() }
            } finally {
                _binding?.progressBar?.visibility = View.GONE
                _binding?.buttonSearch?.isEnabled = true
            }
        }
    }

    private fun loadAllAlbumCovers() {
        // Load covers for all albums in parallel (like desktop's ThreadPoolExecutor approach)
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val albumsToLoad = currentAlbums.mapIndexedNotNull { index, album ->
                    if (album.coverUrl == null) index to album else null
                }
                if (albumsToLoad.isEmpty()) return@launch

                // Use limited dispatcher to avoid overwhelming the server (like desktop's max_workers=6)
                @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
                val limitedDispatcher = Dispatchers.IO.limitedParallelism(6)

                supervisorScope {
                    for ((index, album) in albumsToLoad) {
                        launch(limitedDispatcher) {
                            try {
                                val coverUrl = fetchAlbumCoverUrl(album.url)
                                if (coverUrl != null) {
                                    withContext(Dispatchers.Main) {
                                        if (_binding != null && index < currentAlbums.size) {
                                            currentAlbums[index] = currentAlbums[index].copy(coverUrl = coverUrl)
                                            albumAdapter.notifyItemChanged(index)
                                        }
                                    }
                                } else {
                                    android.util.Log.w("MusicFragment", "No cover found for: ${album.gameName}")
                                }
                            } catch (e: Exception) {
                                android.util.Log.e("MusicFragment", "Cover load error for ${album.gameName}: ${e.message}")
                            }
                        }
                    }
                }

                // Update status when all covers are done
                withContext(Dispatchers.Main) {
                    if (_binding != null) {
                        _binding?.textStatus?.text = "${currentAlbums.size} album(s) found"
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("MusicFragment", "Error in loadAllAlbumCovers: ${e.message}")
            }
        }
    }

    private fun loadAlbumCover(album: Album, position: Int) {
        if (album.coverUrl != null) return // Already loaded

        viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
            try {
                val coverUrl = fetchAlbumCoverUrl(album.url)
                if (coverUrl != null) {
                    withContext(Dispatchers.Main) {
                        if (_binding != null && position < currentAlbums.size) {
                            currentAlbums[position] = album.copy(coverUrl = coverUrl)
                            albumAdapter.notifyItemChanged(position)
                        }
                    }
                }
            } catch (e: Exception) {
                // Silently fail
            }
        }
    }

    /**
     * Fetch album cover URL from the album page.
     * Mirrors the desktop Python logic from khinsider_scraper.py which works reliably:
     * 1. Find img with alt containing "cover" or "album" (case-insensitive)
     * 2. Fallback to first img inside div#pageContent
     * 3. Skip tiny/UI images
     */
    private fun fetchAlbumCoverUrl(albumUrl: String): String? {
        try {
            val doc = Jsoup.connect(albumUrl)
                .userAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                .header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
                .header("Accept-Language", "en-US,en;q=0.5")
                .timeout(15000)
                .followRedirects(true)
                .get()

            // Strategy 1: Find img with alt containing "cover" or "album" (matches desktop logic)
            val coverImg = doc.select("img[alt~=(?i)(cover|album)]").firstOrNull()
            if (coverImg != null) {
                val src = resolveImageUrl(coverImg)
                if (src != null) {
                    android.util.Log.d("MusicFragment", "Found cover via alt attr: $src")
                    return src
                }
            }

            // Strategy 2: First img inside div#pageContent (desktop fallback)
            val contentImg = doc.selectFirst("div#pageContent img")
            if (contentImg != null) {
                val src = resolveImageUrl(contentImg)
                if (src != null && !isUiImage(src)) {
                    android.util.Log.d("MusicFragment", "Found cover via #pageContent: $src")
                    return src
                }
            }

            // Strategy 3: Scan all images in page content, skip tiny/UI ones
            val allImages = doc.select("div#pageContent img")
            for (img in allImages) {
                val src = resolveImageUrl(img) ?: continue
                if (isUiImage(src)) continue

                // Check dimensions if available - skip tiny images
                val width = img.attr("width").toIntOrNull() ?: 999
                val height = img.attr("height").toIntOrNull() ?: 999
                if (width < 50 || height < 50) continue

                android.util.Log.d("MusicFragment", "Found cover via scan: $src")
                return src
            }

        } catch (e: Exception) {
            android.util.Log.e("MusicFragment", "Error fetching cover from $albumUrl: ${e.message}")
        }
        return null
    }

    /** Resolve an img element to a full URL, preferring abs:src. */
    private fun resolveImageUrl(img: org.jsoup.nodes.Element): String? {
        var src = img.attr("abs:src")
        if (src.isEmpty()) src = img.attr("src")
        if (src.isEmpty()) return null
        if (!src.startsWith("http")) {
            src = "$KHINSIDER_BASE_URL$src"
        }
        return src
    }

    /** Check if a URL looks like a UI/tracking element rather than album art. */
    private fun isUiImage(url: String): Boolean {
        val lower = url.lowercase()
        return lower.contains("icon") || lower.contains("button") ||
                lower.contains("pixel") || lower.contains("ads") ||
                lower.contains("spacer") || lower.contains("1x1") ||
                lower.contains("logo") || lower.contains("banner") ||
                lower.endsWith(".gif")
    }

    private suspend fun searchKhinsider(query: String): List<Album> {
        val albums = mutableListOf<Album>()

        try {
            val searchUrl = "$KHINSIDER_SEARCH_URL?search=${URLEncoder.encode(query, "UTF-8")}"
            val doc = Jsoup.connect(searchUrl)
                .userAgent("Mozilla/5.0")
                .timeout(15000)
                .get()

            // Find album links - KHInsider returns results sorted by popularity
            val links = doc.select("a[href*=/game-soundtracks/album/]")

            for (link in links) {
                val url = link.attr("abs:href")
                val title = link.text().trim()

                if (title.isEmpty()) continue

                val isGamerip = url.contains("gamerip", ignoreCase = true) ||
                               title.contains("gamerip", ignoreCase = true)

                // Extract game name from title
                val gameName = extractGameName(title)

                albums.add(Album(
                    title = title,
                    url = url,
                    gameName = gameName,
                    isGamerip = isGamerip
                ))
            }

        } catch (e: Exception) {
            throw e
        }

        // Keep original order from KHInsider (sorted by popularity) and limit
        return albums
            .distinctBy { it.url }
            .take(20)
    }

    private fun extractGameName(title: String): String {
        return title
            .replace(Regex("\\s*[-:]?\\s*(original\\s+)?sound(track)?s?", RegexOption.IGNORE_CASE), "")
            .replace(Regex("\\s*ost", RegexOption.IGNORE_CASE), "")
            .replace(Regex("\\s*music", RegexOption.IGNORE_CASE), "")
            .replace(Regex("\\s*gamerip", RegexOption.IGNORE_CASE), "")
            .replace(Regex("\\s*\\(gamerip\\)", RegexOption.IGNORE_CASE), "")
            .trim()
    }

    private fun showAlbumTracks(album: Album) {
        _binding?.progressBar?.visibility = View.VISIBLE
        _binding?.textStatus?.text = "Loading tracks..."

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val tracks = withContext(Dispatchers.IO) {
                    fetchAlbumTracks(album)
                }

                if (_binding == null) return@launch
                showTracksDialog(album, tracks)

            } catch (e: Exception) {
                context?.let { Toast.makeText(it, "Failed to load tracks", Toast.LENGTH_SHORT).show() }
            } finally {
                _binding?.progressBar?.visibility = View.GONE
                _binding?.textStatus?.text = "${currentAlbums.size} album(s)"
            }
        }
    }

    private suspend fun fetchAlbumTracks(album: Album): List<Track> {
        val tracks = mutableListOf<Track>()

        try {
            val doc = Jsoup.connect(album.url)
                .userAgent("Mozilla/5.0")
                .timeout(15000)
                .get()

            // Get cover image if not already loaded
            if (album.coverUrl == null) {
                val coverImg = doc.selectFirst("img[alt*=cover], img[alt*=album], div#pageContent img")
                album.coverUrl = coverImg?.attr("abs:src")
            }

            // Find track table
            val trackTable = doc.selectFirst("table#songlist") ?: doc.select("table").find {
                it.selectFirst("a[href*=/game-soundtracks/]") != null
            }

            var trackNum = 0
            val durationPattern = Regex("^\\d{1,2}:\\d{2}$")

            trackTable?.select("tr")?.forEach { row ->
                if (row.selectFirst("th") != null) return@forEach // Skip header

                val trackLink = row.selectFirst("a[href*=/game-soundtracks/]") ?: return@forEach
                trackNum++

                val trackUrl = trackLink.attr("abs:href")
                val trackTitle = trackLink.text().trim()

                // Find duration from cells
                var duration = ""
                row.select("td").forEach { cell ->
                    val text = cell.text().trim()
                    if (durationPattern.matches(text)) {
                        duration = text
                    }
                }

                tracks.add(Track(
                    title = trackTitle,
                    trackNumber = trackNum,
                    duration = duration,
                    pageUrl = trackUrl
                ))
            }

            album.trackCount = tracks.size

        } catch (e: Exception) {
            throw e
        }

        return tracks
    }

    private fun showTracksDialog(album: Album, tracks: List<Track>) {
        val filteredTracks = tracks

        val trackTitles = filteredTracks.map { track ->
            "${track.trackNumber}. ${track.title} [${track.duration}]"
        }

        // Use a full custom Dialog so preview panel is never hidden by MaterialAlertDialog chrome
        val ctx = requireContext()
        val dialog = android.app.Dialog(ctx, R.style.Theme_IisuAssetTool_Dialog)
        dialog.requestWindowFeature(android.view.Window.FEATURE_NO_TITLE)
        dialog.setContentView(R.layout.dialog_track_list)

        // Size: 95% width, up to 85% height
        val dm = ctx.resources.displayMetrics
        val maxHeight = (dm.heightPixels * 0.85).toInt()
        dialog.window?.setLayout(
            (dm.widthPixels * 0.95).toInt(),
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        )
        dialog.window?.decorView?.post {
            val h = dialog.window?.decorView?.height ?: 0
            if (h > maxHeight) {
                dialog.window?.setLayout((dm.widthPixels * 0.95).toInt(), maxHeight)
            }
        }

        val listView = dialog.findViewById<android.widget.ListView>(R.id.listTracks)
        val btnPreview = dialog.findViewById<com.google.android.material.button.MaterialButton>(R.id.btnPreview)
        val btnStop = dialog.findViewById<com.google.android.material.button.MaterialButton>(R.id.btnStop)
        val textPreviewStatus = dialog.findViewById<android.widget.TextView>(R.id.textPreviewStatus)
        val progressPreview = dialog.findViewById<android.widget.ProgressBar>(R.id.progressPreview)
        val layoutSelectedTrack = dialog.findViewById<android.widget.LinearLayout>(R.id.layoutSelectedTrack)
        val textSelectedTitle = dialog.findViewById<android.widget.TextView>(R.id.textSelectedTitle)
        val textSelectedInfo = dialog.findViewById<android.widget.TextView>(R.id.textSelectedInfo)
        val layoutVolume = dialog.findViewById<android.widget.LinearLayout>(R.id.layoutVolume)
        val seekVolume = dialog.findViewById<android.widget.SeekBar>(R.id.seekVolume)
        val textVolumePercent = dialog.findViewById<android.widget.TextView>(R.id.textVolumePercent)
        val btnCancel = dialog.findViewById<com.google.android.material.button.MaterialButton>(R.id.btnCancel)
        val btnDownload = dialog.findViewById<com.google.android.material.button.MaterialButton>(R.id.btnDownload)

        listView.adapter = ArrayAdapter(
            ctx,
            android.R.layout.simple_list_item_single_choice,
            trackTitles
        )
        listView.choiceMode = android.widget.ListView.CHOICE_MODE_SINGLE

        var selectedTrack: Track? = null

        btnPreview.isEnabled = false
        btnStop.visibility = View.GONE
        progressPreview.visibility = View.GONE
        layoutSelectedTrack.visibility = View.GONE

        // Volume slider controls
        seekVolume.setOnSeekBarChangeListener(object : android.widget.SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: android.widget.SeekBar?, progress: Int, fromUser: Boolean) {
                textVolumePercent.text = "$progress%"
                if (fromUser) {
                    mediaPlayer?.let { player ->
                        try {
                            player.setVolume(progress / 100f, progress / 100f)
                        } catch (_: Exception) {}
                    }
                }
            }
            override fun onStartTrackingTouch(seekBar: android.widget.SeekBar?) {}
            override fun onStopTrackingTouch(seekBar: android.widget.SeekBar?) {}
        })

        listView.setOnItemClickListener { _, _, position, _ ->
            selectedTrack = filteredTracks[position]
            btnPreview.isEnabled = true
            btnDownload.isEnabled = true

            // Stop current preview when selecting a different track
            if (isPlaying) {
                stopPreview()
                textPreviewStatus.text = ""
                btnPreview.visibility = View.VISIBLE
                btnStop.visibility = View.GONE
                progressPreview.visibility = View.GONE
                layoutVolume.visibility = View.GONE
            }

            // Update selected track info
            layoutSelectedTrack.visibility = View.VISIBLE
            textSelectedTitle.text = selectedTrack?.title
            textSelectedInfo.text = "Duration: ${selectedTrack?.duration ?: "Unknown"} • Track #${selectedTrack?.trackNumber}"
        }

        btnPreview.setOnClickListener {
            selectedTrack?.let { track ->
                previewTrack(track, textPreviewStatus, btnPreview, btnStop, progressPreview, layoutVolume, seekVolume)
            }
        }

        btnStop.setOnClickListener {
            stopPreview()
            textPreviewStatus.text = ""
            btnPreview.visibility = View.VISIBLE
            btnStop.visibility = View.GONE
            progressPreview.visibility = View.GONE
            layoutVolume.visibility = View.GONE
        }

        btnCancel.setOnClickListener {
            stopPreview()
            dialog.dismiss()
        }

        btnDownload.setOnClickListener {
            selectedTrack?.let { track ->
                stopPreview()
                dialog.dismiss()
                downloadTrack(album, track)
            }
        }

        dialog.setOnDismissListener {
            stopPreview()
        }

        dialog.show()
    }

    private fun previewTrack(track: Track, statusView: android.widget.TextView,
                             previewBtn: View, stopBtn: View,
                             progressBar: android.widget.ProgressBar? = null,
                             volumeLayout: android.widget.LinearLayout? = null,
                             volumeSeekBar: android.widget.SeekBar? = null) {
        statusView.text = "Loading preview..."
        previewBtn.isEnabled = false
        progressBar?.visibility = View.VISIBLE

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val downloadUrl = withContext(Dispatchers.IO) {
                    getTrackDownloadUrl(track.pageUrl)
                }

                if (_binding == null) return@launch

                if (downloadUrl == null) {
                    withContext(Dispatchers.Main) {
                        statusView.text = "Could not load preview URL"
                        previewBtn.isEnabled = true
                        progressBar?.visibility = View.GONE
                    }
                    return@launch
                }

                android.util.Log.d("MusicFragment", "Preview URL: $downloadUrl")

                // Play the audio on main thread
                withContext(Dispatchers.Main) {
                    try {
                        stopPreview() // Stop any existing playback

                        mediaPlayer = MediaPlayer().apply {
                            setAudioAttributes(
                                AudioAttributes.Builder()
                                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                                    .setUsage(AudioAttributes.USAGE_MEDIA)
                                    .build()
                            )

                            setOnPreparedListener { mp ->
                                try {
                                    // Duck background music while previewing
                                    BackgroundMusicManager.duck(requireContext())

                                    // Apply current volume from slider
                                    val vol = (volumeSeekBar?.progress ?: 70) / 100f
                                    mp.setVolume(vol, vol)
                                    mp.start()
                                    this@MusicFragment.isPlaying = true
                                    this@MusicFragment.currentPreviewTrack = track
                                    statusView.text = "Playing: ${track.title}"
                                    previewBtn.visibility = View.GONE
                                    stopBtn.visibility = View.VISIBLE
                                    progressBar?.visibility = View.GONE
                                    // Show volume controls during playback
                                    volumeLayout?.visibility = View.VISIBLE
                                } catch (e: Exception) {
                                    android.util.Log.e("MusicFragment", "Error starting playback: ${e.message}")
                                    statusView.text = "Playback error"
                                    previewBtn.visibility = View.VISIBLE
                                    previewBtn.isEnabled = true
                                    stopBtn.visibility = View.GONE
                                    progressBar?.visibility = View.GONE
                                    volumeLayout?.visibility = View.GONE
                                }
                            }

                            setOnCompletionListener {
                                statusView.text = "Preview finished"
                                previewBtn.visibility = View.VISIBLE
                                previewBtn.isEnabled = true
                                stopBtn.visibility = View.GONE
                                volumeLayout?.visibility = View.GONE
                                this@MusicFragment.isPlaying = false
                                // Restore background music volume when track ends naturally
                                BackgroundMusicManager.unduck()
                            }

                            setOnErrorListener { _, what, extra ->
                                android.util.Log.e("MusicFragment", "MediaPlayer error: what=$what extra=$extra")
                                statusView.text = "Preview error (code: $what)"
                                previewBtn.visibility = View.VISIBLE
                                previewBtn.isEnabled = true
                                stopBtn.visibility = View.GONE
                                volumeLayout?.visibility = View.GONE
                                this@MusicFragment.isPlaying = false
                                true
                            }

                            // Set data source and prepare
                            try {
                                setDataSource(downloadUrl)
                                prepareAsync()
                                statusView.text = "Buffering..."
                            } catch (e: Exception) {
                                android.util.Log.e("MusicFragment", "Error setting data source: ${e.message}")
                                statusView.text = "Cannot play: ${e.message}"
                                previewBtn.visibility = View.VISIBLE
                                previewBtn.isEnabled = true
                                stopBtn.visibility = View.GONE
                            }
                        }
                    } catch (e: Exception) {
                        android.util.Log.e("MusicFragment", "Preview setup error: ${e.message}")
                        statusView.text = "Preview error: ${e.message}"
                        previewBtn.visibility = View.VISIBLE
                        previewBtn.isEnabled = true
                        stopBtn.visibility = View.GONE
                    }
                }

            } catch (e: Exception) {
                android.util.Log.e("MusicFragment", "Preview failed: ${e.message}")
                withContext(Dispatchers.Main) {
                    statusView.text = "Preview failed"
                    previewBtn.isEnabled = true
                }
            }
        }
    }

    private fun stopPreview() {
        try {
            mediaPlayer?.let { player ->
                if (player.isPlaying) {
                    player.stop()
                }
                player.release()
            }
            mediaPlayer = null
            isPlaying = false
            currentPreviewTrack = null

            // Restore background music volume after preview stops
            BackgroundMusicManager.unduck()
        } catch (e: Exception) {
            // Ignore
        }
    }

    private fun downloadTrack(album: Album, track: Track) {
        // Show game folder selection dialog in soundbyte mode
        context?.let { ctx ->
            GameFolderSelectDialog.show(
                context = ctx,
                suggestedName = album.gameName,
                suggestedPlatform = "",
                mode = GameFolderSelectDialog.Mode.SOUNDBYTE,
                coroutineScope = viewLifecycleOwner.lifecycleScope
            ) { selectedGame ->
                // User selected a game, now download the track to that folder
                downloadTrackToGame(album, track, selectedGame)
            }
        }
    }

    private fun downloadTrackToGame(album: Album, track: Track, game: com.iisu.assettool.util.GameInfo) {
        _binding?.progressBar?.visibility = View.VISIBLE
        _binding?.textStatus?.text = "Downloading ${track.title}..."

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                // Get actual download URL
                val downloadUrl = withContext(Dispatchers.IO) {
                    getTrackDownloadUrl(track.pageUrl)
                }

                if (_binding == null) return@launch

                if (downloadUrl == null) {
                    context?.let { Toast.makeText(it, "Could not get download URL", Toast.LENGTH_SHORT).show() }
                    _binding?.progressBar?.visibility = View.GONE
                    return@launch
                }

                // Determine file extension
                val extension = when {
                    downloadUrl.contains(".flac", ignoreCase = true) -> ".flac"
                    downloadUrl.contains(".ogg", ignoreCase = true) -> ".ogg"
                    else -> ".mp3"
                }

                // Check if file already exists
                val targetFile = File(game.folder, "music$extension")
                if (targetFile.exists()) {
                    withContext(Dispatchers.Main) {
                        context?.let { ctx ->
                            MaterialAlertDialogBuilder(ctx)
                                .setTitle("File Exists")
                                .setMessage("This game already has a soundbyte:\n${targetFile.name}\n\nOverwrite it?")
                                .setPositiveButton("Overwrite") { _, _ ->
                                    performDownload(album, track, downloadUrl, targetFile, game)
                                }
                                .setNegativeButton("Cancel") { _, _ ->
                                    _binding?.progressBar?.visibility = View.GONE
                                    _binding?.textStatus?.text = "Download cancelled"
                                }
                                .show()
                        }
                    }
                    return@launch
                }

                // Download the file
                performDownload(album, track, downloadUrl, targetFile, game)

            } catch (e: Exception) {
                _binding?.textStatus?.text = "Download failed: ${e.message}"
                context?.let { Toast.makeText(it, "Download failed: ${e.message}", Toast.LENGTH_SHORT).show() }
                _binding?.progressBar?.visibility = View.GONE
            }
        }
    }

    @Suppress("UNUSED_PARAMETER")
    private fun performDownload(album: Album, track: Track, downloadUrl: String, targetFile: File, game: com.iisu.assettool.util.GameInfo) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    // Delete any existing music files
                    listOf("mp3", "ogg", "flac", "wav").forEach { ext ->
                        val existing = File(game.folder, "music.$ext")
                        if (existing.exists()) existing.delete()
                    }

                    // Download the file
                    val url = URL(downloadUrl)
                    url.openStream().use { input ->
                        FileOutputStream(targetFile).use { output ->
                            input.copyTo(output)
                        }
                    }
                }

                if (_binding == null) return@launch

                _binding?.textStatus?.text = "Saved ${track.title}"
                _binding?.progressBar?.visibility = View.GONE

                // Show detailed success dialog with save location
                context?.let { ctx ->
                    MaterialAlertDialogBuilder(ctx)
                        .setTitle("Download Complete")
                        .setMessage(
                            "Soundbyte saved!\n\n" +
                                "Game: ${game.displayName}\n" +
                                "Track: ${track.title}\n" +
                                "Duration: ${track.duration}\n\n" +
                                "Saved to:\n${targetFile.absolutePath}"
                        )
                        .setPositiveButton("OK", null)
                        .show()
                }

            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    _binding?.textStatus?.text = "Download failed: ${e.message}"
                    _binding?.progressBar?.visibility = View.GONE
                    context?.let { Toast.makeText(it, "Download failed: ${e.message}", Toast.LENGTH_SHORT).show() }
                }
            }
        }
    }

    private suspend fun getTrackDownloadUrl(pageUrl: String): String? {
        try {
            android.util.Log.d("MusicFragment", "Fetching track URL from: $pageUrl")

            val doc = Jsoup.connect(pageUrl)
                .userAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                .timeout(10000)
                .followRedirects(true)
                .get()

            val html = doc.html()

            // Look for direct MP3 download links (KHInsider uses specific patterns)
            // Priority 1: Links with "Click here to download" text
            doc.select("a:contains(Click here to download)").forEach { link ->
                val href = link.attr("abs:href")
                if (href.endsWith(".mp3", true) || href.endsWith(".flac", true) || href.endsWith(".ogg", true)) {
                    android.util.Log.d("MusicFragment", "Found download link: $href")
                    return href
                }
            }

            // Priority 2: Audio element source
            doc.selectFirst("audio source")?.let { source ->
                val src = source.attr("src")
                if (src.isNotEmpty()) {
                    val fullUrl = if (src.startsWith("http")) src else "https://downloads.khinsider.com$src"
                    android.util.Log.d("MusicFragment", "Found audio source: $fullUrl")
                    return fullUrl
                }
            }

            // Priority 3: Direct audio element src
            doc.selectFirst("audio[src]")?.let { audio ->
                val src = audio.attr("src")
                if (src.isNotEmpty()) {
                    val fullUrl = if (src.startsWith("http")) src else "https://downloads.khinsider.com$src"
                    android.util.Log.d("MusicFragment", "Found audio src: $fullUrl")
                    return fullUrl
                }
            }

            // Priority 4: Regex search for MP3 URLs in the page
            // KHInsider hosts files on various CDNs
            val mp3Pattern = Regex("""(https?://[^"'\s<>]+\.(mp3|flac|ogg))""", RegexOption.IGNORE_CASE)
            val matches = mp3Pattern.findAll(html).toList()

            // Filter out preview URLs and find the best match
            for (match in matches) {
                val url = match.groupValues[1]
                // Skip preview/sample files
                if (url.contains("preview", true) || url.contains("sample", true)) continue
                // Prefer vgmsite or similar CDN URLs
                if (url.contains("vgmsite", true) || url.contains("vgmdownloads", true)) {
                    android.util.Log.d("MusicFragment", "Found CDN MP3 URL: $url")
                    return url
                }
            }

            // Return first non-preview match if no CDN found
            for (match in matches) {
                val url = match.groupValues[1]
                if (!url.contains("preview", true) && !url.contains("sample", true)) {
                    android.util.Log.d("MusicFragment", "Found MP3 URL: $url")
                    return url
                }
            }

            // Priority 5: Any MP3 link
            doc.selectFirst("a[href$=.mp3]")?.let { link ->
                val href = link.attr("abs:href")
                if (href.isNotEmpty()) {
                    android.util.Log.d("MusicFragment", "Found MP3 anchor: $href")
                    return href
                }
            }

            android.util.Log.d("MusicFragment", "No audio URL found for $pageUrl")

        } catch (e: Exception) {
            android.util.Log.e("MusicFragment", "Error getting track URL: ${e.message}")
        }

        return null
    }

    override fun onDestroyView() {
        super.onDestroyView()
        stopPreview()
        _binding = null
    }

    // ==================== RecyclerView Adapter ====================

    inner class AlbumAdapter(
        private val onAlbumClick: (Album) -> Unit,
        private val onCoverNeeded: (Album, Int) -> Unit
    ) : RecyclerView.Adapter<AlbumAdapter.ViewHolder>() {

        private var albums: List<Album> = emptyList()

        fun submitList(newAlbums: List<Album>) {
            albums = newAlbums
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_album, parent, false)
            return ViewHolder(view)
        }

        override fun onBindViewHolder(holder: ViewHolder, position: Int) {
            holder.bind(albums[position], position)
        }

        override fun getItemCount() = albums.size

        inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            private val imageCover = view.findViewById<android.widget.ImageView>(R.id.imageCover)
            private val textTitle = view.findViewById<android.widget.TextView>(R.id.textTitle)
            private val textBadge = view.findViewById<android.widget.TextView>(R.id.textBadge)

            fun bind(album: Album, position: Int) {
                textTitle.text = album.gameName

                // Show gamerip badge
                textBadge.visibility = if (album.isGamerip) View.VISIBLE else View.GONE

                // Load cover if available
                if (album.coverUrl != null) {
                    imageCover.load(album.coverUrl) {
                        placeholder(R.drawable.ic_image_placeholder)
                        error(R.drawable.ic_image_placeholder)
                        crossfade(true)
                    }
                } else {
                    imageCover.setImageResource(R.drawable.ic_image_placeholder)
                    // Request cover load if not already loaded
                    onCoverNeeded(album, position)
                }

                itemView.setOnClickListener { onAlbumClick(album) }
            }
        }
    }
}
