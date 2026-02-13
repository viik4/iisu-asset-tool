"""
KHInsider Soundbyte Scraper for iiSU Asset Tool

Scrapes video game music from downloads.khinsider.com for use as
soundbytes (hover music) in iiSU Launcher.

Results are returned in the order from KHInsider (sorted by popularity).
Uses fuzzy matching similar to artwork scraping.

Optimized for speed with connection pooling and caching.
"""

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Try to use lxml for faster parsing, fallback to html.parser
try:
    import lxml
    HTML_PARSER = 'lxml'
except ImportError:
    HTML_PARSER = 'html.parser'

from bs4 import BeautifulSoup, SoupStrainer


# Constants
KHINSIDER_BASE_URL = "https://downloads.khinsider.com"
KHINSIDER_SEARCH_URL = f"{KHINSIDER_BASE_URL}/search"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Request headers
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# Timeouts (connect, read) - reduced for speed
TIMEOUT = (3, 8)


@dataclass
class SoundbyteTrack:
    """Represents a single track from an album."""
    title: str
    track_number: int
    duration: str  # Format: "M:SS" or "MM:SS"
    download_url: str  # Direct link to track page (not the MP3 itself)
    preview_url: Optional[str] = None  # For streaming preview
    file_size: Optional[str] = None

    @property
    def duration_seconds(self) -> int:
        """Convert duration string to seconds."""
        try:
            parts = self.duration.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, IndexError):
            pass
        return 0


@dataclass
class SoundbyteAlbum:
    """Represents an album/soundtrack from KHInsider."""
    title: str
    url: str
    game_name: str  # Cleaned game name for matching
    platform: Optional[str] = None
    year: Optional[str] = None
    track_count: int = 0
    is_gamerip: bool = False
    tags: List[str] = field(default_factory=list)
    tracks: List[SoundbyteTrack] = field(default_factory=list)
    cover_url: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Display name with platform and year if available."""
        parts = [self.title]
        if self.platform:
            parts.append(f"[{self.platform}]")
        if self.year:
            parts.append(f"({self.year})")
        return " ".join(parts)


@dataclass
class SoundbyteSearchResult:
    """Results from a soundbyte search."""
    query: str
    albums: List[SoundbyteAlbum] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def has_results(self) -> bool:
        return len(self.albums) > 0

    @property
    def gamerip_albums(self) -> List[SoundbyteAlbum]:
        """Return only gamerip-tagged albums."""
        return [a for a in self.albums if a.is_gamerip]


class KHInsiderScraper:
    """
    Scraper for KHInsider video game music database.

    Optimized for speed with:
    - Connection pooling
    - Session reuse
    - Caching
    - Parallel requests for album details
    - Faster HTML parsing
    """

    def __init__(self):
        self.session = self._create_session()
        self._cache: Dict[str, SoundbyteAlbum] = {}  # URL -> album cache
        self._search_cache: Dict[str, SoundbyteSearchResult] = {}  # query -> results

    def _create_session(self) -> requests.Session:
        """Create optimized session with connection pooling."""
        session = requests.Session()
        session.headers.update(HEADERS)

        # Configure retry strategy
        retry = Retry(
            total=2,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504],
        )

        # Mount adapter with connection pooling
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        return session

    def search_game(self, game_name: str, platform: Optional[str] = None,
                    gamerip_only: bool = False) -> SoundbyteSearchResult:
        """
        Search for game soundtracks by name.

        Results are returned in the order from KHInsider (sorted by popularity).
        Optimized with caching and faster parsing.
        """
        # Check cache first
        cache_key = f"{game_name}|{platform}"
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        result = SoundbyteSearchResult(query=game_name)

        try:
            # Clean the game name for search
            clean_name = self._clean_game_name(game_name)

            # Perform search
            search_url = f"{KHINSIDER_SEARCH_URL}?search={urllib.parse.quote(clean_name)}"
            response = self.session.get(search_url, timeout=TIMEOUT)
            response.raise_for_status()

            # Parse search results - use SoupStrainer for faster parsing
            # Only parse links and table rows we need
            strainer = SoupStrainer(['a', 'tr', 'td'])
            soup = BeautifulSoup(response.text, HTML_PARSER, parse_only=strainer)

            albums = self._parse_search_results_fast(soup, game_name)

            # Filter by platform if specified
            if platform:
                platform_lower = platform.lower()
                albums = [a for a in albums if self._matches_platform(a, platform_lower)]

            # Keep results in original order from KHInsider (sorted by popularity)
            # Just limit to top 20 for speed and remove duplicates
            seen_urls = set()
            unique_albums = []
            for album in albums:
                if album.url not in seen_urls:
                    seen_urls.add(album.url)
                    unique_albums.append(album)
                    if len(unique_albums) >= 20:
                        break

            result.albums = unique_albums

            # Cache the result
            self._search_cache[cache_key] = result

        except requests.Timeout:
            result.error = "Search timed out - try again"
        except requests.RequestException as e:
            result.error = f"Network error: {str(e)}"
        except Exception as e:
            result.error = f"Error searching: {str(e)}"

        return result

    def get_album_details(self, album: SoundbyteAlbum) -> SoundbyteAlbum:
        """Fetch full album details including track list."""
        if album.url in self._cache:
            cached = self._cache[album.url]
            # Copy cached data to album
            album.tracks = cached.tracks
            album.track_count = cached.track_count
            album.cover_url = cached.cover_url
            return album

        try:
            response = self.session.get(album.url, timeout=TIMEOUT)
            response.raise_for_status()

            # Fast parsing - only get what we need
            soup = BeautifulSoup(response.text, HTML_PARSER)

            # Parse album page
            album = self._parse_album_page_fast(soup, album)

            # Cache the result
            self._cache[album.url] = album

        except Exception as e:
            print(f"Error fetching album details: {e}")

        return album

    def get_album_details_parallel(self, albums: List[SoundbyteAlbum],
                                    max_workers: int = 5) -> List[SoundbyteAlbum]:
        """Fetch details for multiple albums in parallel."""
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_album = {
                executor.submit(self.get_album_details, album): album
                for album in albums
            }

            for future in as_completed(future_to_album):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    album = future_to_album[future]
                    results.append(album)

        return results

    def get_track_download_url(self, track: SoundbyteTrack) -> Optional[str]:
        """Get the actual MP3 download URL for a track."""
        try:
            response = self.session.get(track.download_url, timeout=TIMEOUT)
            response.raise_for_status()

            # Fast regex search first - avoid full parse if possible
            mp3_pattern = re.compile(r'(https?://[^\s"\'<>]+\.mp3)', re.IGNORECASE)
            matches = mp3_pattern.findall(response.text)
            if matches:
                # Prefer the first non-preview URL
                for url in matches:
                    if 'preview' not in url.lower():
                        return url
                return matches[0]

            # Fallback to parsing
            soup = BeautifulSoup(response.text, HTML_PARSER)

            # Look for audio source
            audio_link = soup.select_one('audio source')
            if audio_link and audio_link.get('src'):
                return audio_link['src']

            # Look for download links
            for link in soup.select('a[href$=".mp3"]'):
                href = link.get('href', '')
                if href:
                    return href

        except Exception as e:
            print(f"Error getting download URL: {e}")

        return None

    def _clean_game_name(self, name: str) -> str:
        """Clean game name for search query."""
        # Remove common suffixes/prefixes
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', name)  # Remove parenthetical
        name = re.sub(r'\s*\[[^\]]*\]\s*', ' ', name)  # Remove brackets
        name = re.sub(r'\s*-\s*(USA|Europe|Japan|World|En|Ja|PAL|NTSC).*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s*(v\d+\.\d+|Rev\s*\d+).*$', '', name, flags=re.IGNORECASE)

        # Remove special characters but keep essential ones
        name = re.sub(r'[^\w\s\-\':&]', ' ', name)

        # Normalize whitespace
        name = ' '.join(name.split())

        return name.strip()

    def _parse_search_results_fast(self, soup: BeautifulSoup, query: str) -> List[SoundbyteAlbum]:
        """Parse search results page - optimized for speed."""
        albums = []
        seen_urls = set()  # Avoid duplicates

        # Find all album links directly
        for link in soup.find_all('a', href=re.compile(r'/game-soundtracks/album/')):
            url = link.get('href', '')
            if not url or url in seen_urls:
                continue

            if not url.startswith('http'):
                url = KHINSIDER_BASE_URL + url

            seen_urls.add(url)

            title = link.get_text(strip=True)
            if not title:
                continue

            # Quick gamerip check from URL/title
            is_gamerip = 'gamerip' in url.lower() or 'gamerip' in title.lower()

            # Extract game name
            game_name = self._extract_game_name(title)

            album = SoundbyteAlbum(
                title=title,
                url=url,
                game_name=game_name,
                is_gamerip=is_gamerip
            )
            albums.append(album)

        return albums

    def _parse_album_page_fast(self, soup: BeautifulSoup, album: SoundbyteAlbum) -> SoundbyteAlbum:
        """Parse album detail page - optimized for speed."""
        tracks = []

        # Get album cover quickly
        cover_img = soup.find('img', {'alt': re.compile(r'cover|album', re.I)})
        if not cover_img:
            cover_img = soup.select_one('div#pageContent img')

        if cover_img:
            src = cover_img.get('src', '')
            if src:
                if not src.startswith('http'):
                    src = KHINSIDER_BASE_URL + src
                album.cover_url = src

        # Check for gamerip in page text
        page_text = soup.get_text().lower()
        if 'gamerip' in page_text:
            album.is_gamerip = True
            if 'gamerip' not in album.tags:
                album.tags.append('gamerip')

        # Find track table - look for the songlist table
        track_table = soup.find('table', {'id': 'songlist'})
        if not track_table:
            # Try finding any table with track links
            for table in soup.find_all('table'):
                if table.find('a', href=re.compile(r'/game-soundtracks/')):
                    track_table = table
                    break

        if track_table:
            track_num = 0
            duration_pattern = re.compile(r'^\d{1,2}:\d{2}$')

            for row in track_table.find_all('tr'):
                # Skip header
                if row.find('th'):
                    continue

                cells = row.find_all('td')
                if len(cells) < 2:
                    continue

                # Find track link
                track_link = row.find('a', href=re.compile(r'/game-soundtracks/'))
                if not track_link:
                    continue

                track_num += 1
                track_url = track_link.get('href', '')
                if not track_url.startswith('http'):
                    track_url = KHINSIDER_BASE_URL + track_url

                track_title = track_link.get_text(strip=True)

                # Get duration from cells
                duration = ""
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if duration_pattern.match(text):
                        duration = text
                        break

                track = SoundbyteTrack(
                    title=track_title,
                    track_number=track_num,
                    duration=duration,
                    download_url=track_url
                )
                tracks.append(track)
        else:
            # Fallback: find any MP3 links or track page links
            for i, link in enumerate(soup.find_all('a', href=re.compile(r'\.mp3|/game-soundtracks/')), 1):
                href = link.get('href', '')
                if not href:
                    continue
                if not href.startswith('http'):
                    href = KHINSIDER_BASE_URL + href

                track = SoundbyteTrack(
                    title=link.get_text(strip=True) or f"Track {i}",
                    track_number=i,
                    duration="",
                    download_url=href
                )
                tracks.append(track)

                if i >= 100:  # Limit for safety
                    break

        album.tracks = tracks
        album.track_count = len(tracks)

        return album

    def _extract_game_name(self, title: str) -> str:
        """Extract clean game name from album title."""
        # Remove common soundtrack suffixes - compiled regex for speed
        name = re.sub(
            r'\s*[-:]?\s*(original\s+)?sound(track)?s?|\s*ost|\s*music|\s*gamerip|\s*complete\s+collection|\s*\(gamerip\)',
            '', title, flags=re.IGNORECASE
        )
        return name.strip()

    def _matches_platform(self, album: SoundbyteAlbum, platform: str) -> bool:
        """Check if album matches the given platform."""
        if album.platform:
            return platform in album.platform.lower()
        # Check title for platform hints
        return platform in album.title.lower()


    def clear_cache(self):
        """Clear all caches."""
        self._cache.clear()
        self._search_cache.clear()


def search_soundbytes(game_name: str, platform: Optional[str] = None) -> SoundbyteSearchResult:
    """
    Convenience function to search for game soundbytes.
    Results are returned in order from KHInsider (sorted by popularity).
    """
    scraper = KHInsiderScraper()
    return scraper.search_game(game_name, platform)


# For testing
if __name__ == "__main__":
    import time

    print("Testing KHInsider Scraper (optimized)...")

    start = time.time()
    result = search_soundbytes("Chrono Trigger")
    elapsed = time.time() - start

    print(f"Found {len(result.albums)} albums for 'Chrono Trigger' in {elapsed:.2f}s")

    if result.albums:
        print(f"\nTop result: {result.albums[0].display_name}")
        print(f"URL: {result.albums[0].url}")
        print(f"Is Gamerip: {result.albums[0].is_gamerip}")

        # Test album details
        start = time.time()
        scraper = KHInsiderScraper()
        album = scraper.get_album_details(result.albums[0])
        elapsed = time.time() - start
        print(f"\nFetched album details in {elapsed:.2f}s")
        print(f"Track count: {album.track_count}")
        if album.tracks:
            print(f"First track: {album.tracks[0].title}")
