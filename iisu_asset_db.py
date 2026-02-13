"""
iiSU Themed Assets Database Client

Fetches pre-themed assets from a public Google Drive folder.
These assets are community-created and already styled for iiSU Launcher.

Folder Structure (mirrors iiSU structure):
├── {PLATFORM}/
│   ├── {GameName}/
│   │   ├── icon.png
│   │   ├── hero_1.png
│   │   ├── title.png
│   │   └── slide_1.png
│   ├── {GameName}_2/
│   │   └── icon.png (alternative variant)
│   └── ...
├── android_apps/
│   └── {package.name}/
│       └── icon.png
└── ...

Folders without _N suffix are treated as variant 1.
The _2, _3, etc. suffixes indicate additional variants for the same game.

Uses gdown-style parsing for Google Drive folder access - works with public folders.
"""

import re
import json
import itertools
import warnings
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import difflib

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


class AssetType(Enum):
    """Types of assets in iiSU structure."""
    ICON = "icon"           # icon.png
    HERO = "hero"           # hero_1.png, hero_2.png, etc.
    LOGO = "logo"           # title.png
    SCREENSHOT = "slide"    # slide_1.png, slide_2.png, etc.
    SOUNDBYTE = "soundbyte" # soundbyte.mp3 (future)


@dataclass
class ThemedAssetFile:
    """A single asset file from the database."""
    filename: str
    asset_type: AssetType
    download_url: str
    file_id: str
    size: Optional[int] = None

    @property
    def is_image(self) -> bool:
        return self.asset_type != AssetType.SOUNDBYTE

    def get_preview_url(self, width: int = 400) -> str:
        """
        Get a URL suitable for previewing this asset.
        Uses Google's thumbnail/direct image URL which is more reliable than uc?export=download.
        """
        # Use lh3.googleusercontent.com for direct image access
        return f"https://lh3.googleusercontent.com/d/{self.file_id}=w{width}"

    def get_thumbnail_url(self, width: int = 200) -> str:
        """Get a thumbnail URL for smaller previews."""
        return f"https://drive.google.com/thumbnail?id={self.file_id}&sz=w{width}"


@dataclass
class ThemedAssetVariant:
    """
    A variant of themed assets for a game (e.g., GameName, GameName_2).
    Each variant is a complete set of themed assets.
    """
    game_name: str          # Clean game name (without _N suffix)
    variant_number: int     # 1, 2, 3, etc.
    folder_name: str        # Full folder name (e.g., "Chrono Trigger" or "Chrono Trigger_2")
    folder_id: str          # Google Drive folder ID
    platform: str           # Platform key (e.g., "SNES")
    assets: List[ThemedAssetFile] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.variant_number > 1:
            return f"{self.game_name} (Variant {self.variant_number})"
        return self.game_name

    @property
    def has_icon(self) -> bool:
        return any(a.asset_type == AssetType.ICON for a in self.assets)

    @property
    def has_hero(self) -> bool:
        return any(a.asset_type == AssetType.HERO for a in self.assets)

    @property
    def has_logo(self) -> bool:
        return any(a.asset_type == AssetType.LOGO for a in self.assets)

    @property
    def has_screenshots(self) -> bool:
        return any(a.asset_type == AssetType.SCREENSHOT for a in self.assets)

    def get_asset(self, asset_type: AssetType) -> Optional[ThemedAssetFile]:
        """Get first asset of given type."""
        for asset in self.assets:
            if asset.asset_type == asset_type:
                return asset
        return None

    def get_assets(self, asset_type: AssetType) -> List[ThemedAssetFile]:
        """Get all assets of given type (for heroes/screenshots with multiple files)."""
        return [a for a in self.assets if a.asset_type == asset_type]


@dataclass
class ThemedGame:
    """
    A game with one or more themed asset variants.
    Groups all variants (GameName, GameName_2, etc.) together.
    """
    game_name: str
    platform: str
    variants: List[ThemedAssetVariant] = field(default_factory=list)

    @property
    def variant_count(self) -> int:
        return len(self.variants)

    @property
    def display_name(self) -> str:
        count = self.variant_count
        if count > 1:
            return f"{self.game_name} ({count} variants)"
        return self.game_name

    def get_variant(self, number: int) -> Optional[ThemedAssetVariant]:
        """Get a specific variant by number."""
        for v in self.variants:
            if v.variant_number == number:
                return v
        return None


@dataclass
class ThemedApp:
    """An Android app with themed assets."""
    package_name: str
    app_name: str  # Derived from package name
    variants: List[ThemedAssetVariant] = field(default_factory=list)

    @property
    def variant_count(self) -> int:
        return len(self.variants)


class IisuAssetDB:
    """
    Client for the iiSU Themed Assets Database (Google Drive).

    Uses gdown-style parsing for public folders.
    """

    # Google Drive URLs
    DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"
    DRIVE_DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"
    # Direct image URL for previews (more reliable than uc?export=download)
    DRIVE_THUMBNAIL_URL = "https://drive.google.com/thumbnail?id={file_id}&sz=w{size}"
    DRIVE_DIRECT_IMAGE_URL = "https://lh3.googleusercontent.com/d/{file_id}=w{size}"

    # Folder MIME type
    FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

    # Headers for requests
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    # Asset filename patterns
    ASSET_PATTERNS = {
        AssetType.ICON: re.compile(r'^icon\.(png|jpg|jpeg)$', re.IGNORECASE),
        AssetType.HERO: re.compile(r'^hero_\d+\.(png|jpg|jpeg)$', re.IGNORECASE),
        AssetType.LOGO: re.compile(r'^title\.(png|jpg|jpeg)$', re.IGNORECASE),
        AssetType.SCREENSHOT: re.compile(r'^slide_\d+\.(png|jpg|jpeg)$', re.IGNORECASE),
        AssetType.SOUNDBYTE: re.compile(r'^soundbyte\.(mp3|ogg|wav)$', re.IGNORECASE),
    }

    # Folder name pattern: "Game Name_2", "Game Name_3", etc.
    VARIANT_PATTERN = re.compile(r'^(.+?)_(\d+)$')

    def __init__(self, folder_id: str, api_key: Optional[str] = None):
        """
        Initialize the database client.

        Args:
            folder_id: Google Drive folder ID (from the shared link)
            api_key: Optional - not used but kept for compatibility
        """
        self.folder_id = folder_id
        self.api_key = api_key
        self.session = self._create_session()

        # Cached data
        self._platforms: Dict[str, str] = {}  # platform_name -> folder_id
        self._games: Dict[str, List[ThemedGame]] = {}  # platform -> games
        self._apps: List[ThemedApp] = []
        self._last_scan: Optional[datetime] = None
        self._scan_cache_minutes = 30

    def _create_session(self) -> requests.Session:
        """Create session with retries and connection pooling."""
        session = requests.Session()
        session.headers.update(self.HEADERS)

        retry = Retry(total=3, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
        session.mount('https://', adapter)

        return session

    @property
    def is_scanned(self) -> bool:
        """Check if database has been scanned."""
        return self._last_scan is not None

    @property
    def needs_refresh(self) -> bool:
        """Check if cache is stale."""
        if not self._last_scan:
            return True
        elapsed = (datetime.now() - self._last_scan).total_seconds() / 60
        return elapsed > self._scan_cache_minutes

    def scan(self, force: bool = False) -> bool:
        """
        Scan the database folder structure.

        Args:
            force: Force rescan even if cache is fresh

        Returns:
            True if scan successful
        """
        if not force and not self.needs_refresh:
            return True

        try:
            # Clear existing data
            self._platforms.clear()
            self._games.clear()
            self._apps.clear()

            # List root folder contents (platform folders)
            root_contents = self._list_folder(self.folder_id)

            if not root_contents:
                raise Exception("Failed to list root folder - folder may be empty or inaccessible")

            for item in root_contents:
                if item['type'] != 'folder':
                    continue

                folder_name = item['name']
                folder_id = item['id']

                if folder_name.lower() == 'android_apps':
                    # Scan Android apps
                    self._scan_apps_folder(folder_id)
                else:
                    # Treat as platform folder
                    self._platforms[folder_name] = folder_id

            # Scan platform folders in parallel for speed
            self._scan_platforms_parallel()

            self._last_scan = datetime.now()
            return True

        except Exception as e:
            print(f"Error scanning database: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _parse_drive_folder_page(self, content: str) -> List[Tuple[str, str, str]]:
        """
        Parse Google Drive folder page to extract file/folder info.

        Uses the same technique as gdown: looks for _DRIVE_ivd JavaScript variable
        which contains encoded folder data.

        Also searches for additional data arrays that may contain more items
        when the folder has pagination.

        Returns:
            List of (id, name, mime_type) tuples
        """
        if not HAS_BS4:
            raise RuntimeError("BeautifulSoup is required for parsing Drive folders")

        soup = BeautifulSoup(content, 'html.parser')
        result = []
        seen_ids = set()

        # Find the script tag with window['_DRIVE_ivd']
        encoded_data = None
        for script in soup.select("script"):
            inner_html = script.decode_contents()

            if "_DRIVE_ivd" in inner_html:
                # Find the encoded array - second JS string after _DRIVE_ivd
                regex_iter = re.compile(r"'((?:[^'\\]|\\.)*)'").finditer(inner_html)
                try:
                    encoded_data = next(itertools.islice(regex_iter, 1, None)).group(1)
                except StopIteration:
                    continue
                break

        if encoded_data is None:
            raise RuntimeError(
                "Cannot retrieve folder information. "
                "The folder may need 'Anyone with the link' permission, "
                "or Google is rate-limiting access."
            )

        # Decode the array
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            decoded = encoded_data.encode("utf-8").decode("unicode_escape")

        folder_arr = json.loads(decoded)
        folder_contents = [] if folder_arr[0] is None else folder_arr[0]

        # Extract id, name, type for each item
        # Format: [id, ?, name, mime_type, ...]
        for entry in folder_contents:
            try:
                file_id = entry[0]
                if file_id in seen_ids:
                    continue
                seen_ids.add(file_id)
                # Name is at index 2, may need unicode decoding
                name = entry[2].encode("raw_unicode_escape").decode("utf-8")
                mime_type = entry[3]
                result.append((file_id, name, mime_type))
            except (IndexError, AttributeError, UnicodeError) as e:
                continue

        # Look for additional data in other script blocks
        # Google sometimes includes more file data in other variables
        for script in soup.select("script"):
            inner_html = script.decode_contents()

            # Skip if it's the main _DRIVE_ivd we already parsed
            if "_DRIVE_ivd" in inner_html:
                continue

            # Look for JSON arrays that might contain file data
            # Pattern: array of arrays with file IDs and names
            json_arrays = re.findall(r'\[\s*\[\s*"([a-zA-Z0-9_-]{20,})"[^\]]*\]', inner_html)
            if not json_arrays:
                continue

            # Try to extract file info from these arrays
            # Look for patterns like: ["fileId","?","filename","mimeType",...]
            array_pattern = re.compile(
                r'\["([a-zA-Z0-9_-]{20,})",[^,]*,"([^"]+)","(application/[^"]+|image/[^"]+)"'
            )
            for match in array_pattern.finditer(inner_html):
                file_id = match.group(1)
                if file_id in seen_ids:
                    continue
                seen_ids.add(file_id)

                name = match.group(2)
                try:
                    name = name.encode("utf-8").decode("unicode_escape")
                except:
                    pass

                mime_type = match.group(3)
                result.append((file_id, name, mime_type))

        return result

    def _list_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        List contents of a Google Drive folder.

        Uses Google Drive API v3 as the primary method for reliable pagination.
        Falls back to gdown-style parsing if API fails.

        For large folders (50+ items), the API method properly handles pagination.
        """
        items = []
        seen_ids = set()  # Avoid duplicates

        # Try API method first - more reliable for pagination
        api_items = self._fetch_via_api(folder_id, seen_ids)
        if api_items:
            return api_items

        # Fallback to gdown-style parsing
        try:
            url = self.DRIVE_FOLDER_URL.format(folder_id=folder_id)
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            # Try the standard gdown parsing
            contents = self._parse_drive_folder_page(response.text)

            for file_id, name, mime_type in contents:
                if file_id in seen_ids:
                    continue
                seen_ids.add(file_id)

                is_folder = mime_type == self.FOLDER_MIME_TYPE

                items.append({
                    'id': file_id,
                    'name': name,
                    'type': 'folder' if is_folder else 'file',
                    'mimeType': mime_type
                })

            # If we got exactly 50 items, there might be more (pagination)
            # Try to get more using the API
            if len(items) >= 50:
                additional = self._fetch_all_folder_items(folder_id, seen_ids)
                items.extend(additional)

        except Exception as e:
            print(f"Error listing folder {folder_id}: {e}")
            import traceback
            traceback.print_exc()

        return items

    def _fetch_via_api(self, folder_id: str, seen_ids: set) -> List[Dict[str, Any]]:
        """
        Fetch folder contents directly via Google Drive API v3.
        This is the most reliable method for large folders with pagination.
        """
        items = []

        # Multiple API keys for fallback (these are public API keys)
        api_keys = [
            'AIzaSyC1eQ1xj69IdTMeii5r7brs3R90eck-m7k',
            'AIzaSyAa8yy0GdcGPHdtD083HiGGx_S0vMPScDM',
            'AIzaSyDqDvPfSK-K9w5NQRz4HDjRwhLUdVSVqV0',
        ]

        # Headers needed for Google Drive API access
        api_headers = {
            **self.HEADERS,
            'Referer': 'https://drive.google.com/',
            'Origin': 'https://drive.google.com',
        }

        for api_key in api_keys:
            try:
                url = "https://www.googleapis.com/drive/v3/files"
                page_token = None
                items = []
                seen_ids_local = set(seen_ids)

                while True:
                    params = {
                        'q': f"'{folder_id}' in parents and trashed = false",
                        'fields': 'nextPageToken,files(id,name,mimeType)',
                        'pageSize': '1000',
                        'supportsAllDrives': 'true',
                        'includeItemsFromAllDrives': 'true',
                        'key': api_key,
                    }

                    if page_token:
                        params['pageToken'] = page_token

                    response = self.session.get(url, params=params, headers=api_headers, timeout=30)

                    if response.status_code == 403:
                        # API key exhausted or rate limited, try next key
                        items = []
                        break

                    if response.status_code != 200:
                        items = []
                        break

                    try:
                        data = response.json()

                        # Check for API error
                        if 'error' in data:
                            items = []
                            break

                        files = data.get('files', [])

                        for item in files:
                            file_id = item.get('id')
                            if file_id and file_id not in seen_ids_local:
                                seen_ids_local.add(file_id)
                                name = item.get('name', '')
                                mime_type = item.get('mimeType', '')
                                is_folder = mime_type == self.FOLDER_MIME_TYPE

                                items.append({
                                    'id': file_id,
                                    'name': name,
                                    'type': 'folder' if is_folder else 'file',
                                    'mimeType': mime_type
                                })

                        # Check for more pages
                        page_token = data.get('nextPageToken')
                        if not page_token:
                            break

                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"JSON parse error: {e}")
                        items = []
                        break

                # If we got items, update seen_ids and return
                if items:
                    seen_ids.update(seen_ids_local)
                    return items

            except Exception as e:
                print(f"API error with key: {e}")
                continue

        return []

    def _fetch_all_folder_items(self, folder_id: str, seen_ids: set) -> List[Dict[str, Any]]:
        """
        Fetch all items from a folder using Google Drive API v3.
        This handles pagination for folders with more than 50 items.
        """
        additional_items = []

        # Multiple API keys for fallback
        api_keys = [
            'AIzaSyC1eQ1xj69IdTMeii5r7brs3R90eck-m7k',
            'AIzaSyAa8yy0GdcGPHdtD083HiGGx_S0vMPScDM',
            'AIzaSyDqDvPfSK-K9w5NQRz4HDjRwhLUdVSVqV0',
        ]

        # Headers needed for Google Drive API access
        api_headers = {
            **self.HEADERS,
            'Referer': 'https://drive.google.com/',
            'Origin': 'https://drive.google.com',
        }

        for api_key in api_keys:
            try:
                # Use Google Drive API v3 for listing
                url = "https://www.googleapis.com/drive/v3/files"
                page_token = None

                while True:
                    params = {
                        'q': f"'{folder_id}' in parents and trashed = false",
                        'fields': 'nextPageToken,files(id,name,mimeType)',
                        'pageSize': '1000',
                        'supportsAllDrives': 'true',
                        'includeItemsFromAllDrives': 'true',
                        'key': api_key,
                    }

                    if page_token:
                        params['pageToken'] = page_token

                    response = self.session.get(url, params=params, headers=api_headers, timeout=30)

                    if response.status_code == 403:
                        # API key exhausted or rate limited, try next key
                        break

                    if response.status_code != 200:
                        break

                    try:
                        data = response.json()
                        files = data.get('files', [])

                        for item in files:
                            file_id = item.get('id')
                            if file_id and file_id not in seen_ids:
                                seen_ids.add(file_id)
                                name = item.get('name', '')
                                mime_type = item.get('mimeType', '')
                                is_folder = mime_type == self.FOLDER_MIME_TYPE

                                additional_items.append({
                                    'id': file_id,
                                    'name': name,
                                    'type': 'folder' if is_folder else 'file',
                                    'mimeType': mime_type
                                })

                        # Check for more pages
                        page_token = data.get('nextPageToken')
                        if not page_token:
                            break

                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"JSON parse error: {e}")
                        break

                # If we got items, we're done
                if additional_items:
                    return additional_items

            except Exception as e:
                print(f"Error with API key: {e}")
                continue

        # If API methods failed, try alternative parsing method
        if not additional_items:
            additional_items = self._fetch_via_export(folder_id, seen_ids)

        return additional_items

    def _fetch_via_export(self, folder_id: str, seen_ids: set) -> List[Dict[str, Any]]:
        """
        Alternative method to fetch all folder items using export/view endpoints.
        """
        items = []

        try:
            # Try the folder's open view with listing mode
            # This sometimes returns more items
            url = f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
            headers = {
                **self.HEADERS,
                'Accept': 'text/html',
            }

            response = self.session.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                # Look for all file/folder IDs in the page source
                # They appear in various data structures
                content = response.text

                # Pattern 1: Look for folder entries in JSON data
                # Format: ["id","name","mimeType",...]
                folder_pattern = re.compile(
                    r'\["([a-zA-Z0-9_-]{20,})",\s*"([^"]+)",\s*"(application/vnd\.google-apps\.folder)"'
                )
                for match in folder_pattern.finditer(content):
                    file_id = match.group(1)
                    if file_id not in seen_ids:
                        seen_ids.add(file_id)
                        name = match.group(2)
                        try:
                            name = name.encode('utf-8').decode('unicode_escape')
                        except:
                            pass
                        items.append({
                            'id': file_id,
                            'name': name,
                            'type': 'folder',
                            'mimeType': self.FOLDER_MIME_TYPE
                        })

                # Pattern 2: Look for file entries
                file_pattern = re.compile(
                    r'\["([a-zA-Z0-9_-]{20,})",\s*"([^"]+)",\s*"(image/[^"]+|application/[^"]+)"'
                )
                for match in file_pattern.finditer(content):
                    file_id = match.group(1)
                    if file_id not in seen_ids and file_id != folder_id:
                        seen_ids.add(file_id)
                        name = match.group(2)
                        mime_type = match.group(3)
                        try:
                            name = name.encode('utf-8').decode('unicode_escape')
                        except:
                            pass
                        if mime_type != self.FOLDER_MIME_TYPE:
                            items.append({
                                'id': file_id,
                                'name': name,
                                'type': 'file',
                                'mimeType': mime_type
                            })

        except Exception as e:
            print(f"Error in export fetch: {e}")

        return items

    def _scan_platforms_parallel(self):
        """Scan all platform folders in parallel."""
        def scan_platform(platform_name: str, folder_id: str):
            try:
                self._scan_platform_folder(platform_name, folder_id)
            except Exception as e:
                print(f"Error scanning platform {platform_name}: {e}")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(scan_platform, name, fid)
                for name, fid in self._platforms.items()
            ]
            for future in as_completed(futures):
                pass  # Wait for completion

    def _scan_platform_folder(self, platform: str, folder_id: str):
        """Scan a platform folder for game variants."""
        games_dict: Dict[str, ThemedGame] = {}  # game_name -> ThemedGame

        contents = self._list_folder(folder_id)

        for item in contents:
            if item['type'] != 'folder':
                continue

            folder_name = item['name']
            variant_folder_id = item['id']

            # Parse variant folder name
            match = self.VARIANT_PATTERN.match(folder_name)
            if match:
                game_name = match.group(1)
                variant_num = int(match.group(2))
            else:
                # No _N suffix, treat as variant 1
                game_name = folder_name
                variant_num = 1

            # Create variant entry (assets will be scanned on demand)
            variant = ThemedAssetVariant(
                game_name=game_name,
                variant_number=variant_num,
                folder_name=folder_name,
                folder_id=variant_folder_id,
                platform=platform
            )

            # Add to game
            if game_name not in games_dict:
                games_dict[game_name] = ThemedGame(
                    game_name=game_name,
                    platform=platform
                )
            games_dict[game_name].variants.append(variant)

        # Sort variants by number
        for game in games_dict.values():
            game.variants.sort(key=lambda v: v.variant_number)

        # Store games sorted by name
        self._games[platform] = sorted(games_dict.values(), key=lambda g: g.game_name.lower())

    def _scan_variant_folder(self, variant: ThemedAssetVariant) -> ThemedAssetVariant:
        """Scan a variant folder for asset files (on demand)."""
        if variant.assets:
            return variant  # Already scanned

        contents = self._list_folder(variant.folder_id)

        for item in contents:
            if item['type'] != 'file':
                continue

            filename = item['name']
            file_id = item['id']

            # Determine asset type from filename
            asset_type = self._get_asset_type(filename)
            if asset_type:
                asset = ThemedAssetFile(
                    filename=filename,
                    asset_type=asset_type,
                    download_url=self.DRIVE_DOWNLOAD_URL.format(file_id=file_id),
                    file_id=file_id
                )
                variant.assets.append(asset)

        return variant

    def _scan_apps_folder(self, folder_id: str):
        """Scan the android_apps folder."""
        apps_dict: Dict[str, ThemedApp] = {}  # package_name -> ThemedApp

        contents = self._list_folder(folder_id)

        for item in contents:
            if item['type'] != 'folder':
                continue

            folder_name = item['name']
            variant_folder_id = item['id']

            # Parse variant folder name (e.g., "com.netflix.mediaclient" or "com.netflix.mediaclient_2")
            match = self.VARIANT_PATTERN.match(folder_name)
            if match:
                package_name = match.group(1)
                variant_num = int(match.group(2))
            else:
                package_name = folder_name
                variant_num = 1

            # Create variant
            variant = ThemedAssetVariant(
                game_name=package_name,
                variant_number=variant_num,
                folder_name=folder_name,
                folder_id=variant_folder_id,
                platform="android_apps"
            )

            # Add to app
            if package_name not in apps_dict:
                app_name = self._package_to_app_name(package_name)
                apps_dict[package_name] = ThemedApp(
                    package_name=package_name,
                    app_name=app_name
                )
            apps_dict[package_name].variants.append(variant)

        # Sort variants
        for app in apps_dict.values():
            app.variants.sort(key=lambda v: v.variant_number)

        self._apps = sorted(apps_dict.values(), key=lambda a: a.app_name.lower())

    def _get_asset_type(self, filename: str) -> Optional[AssetType]:
        """Determine asset type from filename."""
        for asset_type, pattern in self.ASSET_PATTERNS.items():
            if pattern.match(filename):
                return asset_type
        return None

    def _package_to_app_name(self, package_name: str) -> str:
        """Convert package name to display name."""
        parts = package_name.split('.')
        if parts:
            name = parts[-1]
            name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
            name = name.replace('_', ' ')
            return ' '.join(word.capitalize() for word in name.split())
        return package_name

    # === Search Methods ===

    def get_platforms(self) -> List[str]:
        """Get list of available platforms."""
        return sorted(self._platforms.keys())

    def get_games(self, platform: str) -> List[ThemedGame]:
        """Get all games for a platform."""
        return self._games.get(platform, [])

    def get_apps(self) -> List[ThemedApp]:
        """Get all Android apps."""
        return self._apps

    def get_variant_with_assets(self, variant: ThemedAssetVariant) -> ThemedAssetVariant:
        """Get a variant with its assets scanned."""
        return self._scan_variant_folder(variant)

    def search_game(self, query: str, platform: Optional[str] = None,
                    limit: int = 20) -> List[ThemedGame]:
        """Search for games by name."""
        results: List[Tuple[float, ThemedGame]] = []
        query_lower = query.lower()

        platforms = [platform] if platform else list(self._games.keys())

        for plat in platforms:
            for game in self._games.get(plat, []):
                ratio = difflib.SequenceMatcher(
                    None, query_lower, game.game_name.lower()
                ).ratio()

                if query_lower in game.game_name.lower():
                    ratio = max(ratio, 0.8)
                if game.game_name.lower() in query_lower:
                    ratio = max(ratio, 0.75)

                if ratio > 0.5:
                    results.append((ratio, game))

        results.sort(key=lambda x: x[0], reverse=True)
        return [game for _, game in results[:limit]]

    def search_app(self, query: str, limit: int = 20) -> List[ThemedApp]:
        """Search for Android apps."""
        results: List[Tuple[float, ThemedApp]] = []
        query_lower = query.lower()

        for app in self._apps:
            name_ratio = difflib.SequenceMatcher(
                None, query_lower, app.app_name.lower()
            ).ratio()
            pkg_ratio = difflib.SequenceMatcher(
                None, query_lower, app.package_name.lower()
            ).ratio()

            ratio = max(name_ratio, pkg_ratio)

            if query_lower in app.app_name.lower() or query_lower in app.package_name.lower():
                ratio = max(ratio, 0.8)

            if ratio > 0.4:
                results.append((ratio, app))

        results.sort(key=lambda x: x[0], reverse=True)
        return [app for _, app in results[:limit]]

    def find_game_exact(self, game_name: str, platform: str) -> Optional[ThemedGame]:
        """Find a game by exact name match."""
        for game in self._games.get(platform, []):
            if game.game_name.lower() == game_name.lower():
                return game
        return None

    # === Download Methods ===

    def download_asset(self, asset: ThemedAssetFile, output_path: Path) -> bool:
        """Download a single asset file."""
        try:
            response = self.session.get(asset.download_url, timeout=60, stream=True)

            # Handle Google Drive download confirmation for large files
            if 'text/html' in response.headers.get('Content-Type', ''):
                confirm_token = self._get_confirm_token(response)
                if confirm_token:
                    response = self.session.get(
                        asset.download_url + f"&confirm={confirm_token}",
                        timeout=60, stream=True
                    )

            response.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True

        except Exception as e:
            print(f"Error downloading {asset.filename}: {e}")
            return False

    def download_variant(self, variant: ThemedAssetVariant,
                         output_folder: Path) -> Dict[str, bool]:
        """Download all assets from a variant to a folder."""
        # Make sure assets are scanned
        variant = self._scan_variant_folder(variant)

        results = {}
        for asset in variant.assets:
            output_path = output_folder / asset.filename
            success = self.download_asset(asset, output_path)
            results[asset.filename] = success

        return results

    def _get_confirm_token(self, response) -> Optional[str]:
        """Extract confirmation token from Google Drive warning page."""
        for key, value in response.cookies.items():
            if key.startswith('download_warning'):
                return value
        return None

    # === Stats ===

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        total_games = sum(len(games) for games in self._games.values())
        total_variants = sum(
            sum(g.variant_count for g in games)
            for games in self._games.values()
        )

        return {
            'platforms': len(self._platforms),
            'platform_names': self.get_platforms(),
            'total_games': total_games,
            'total_variants': total_variants,
            'total_apps': len(self._apps),
            'last_scan': self._last_scan.isoformat() if self._last_scan else None,
        }


def create_db_client(folder_id: str, api_key: Optional[str] = None) -> IisuAssetDB:
    """Create and return a database client."""
    return IisuAssetDB(folder_id, api_key)


# For testing
if __name__ == "__main__":
    import sys

    # Default to iiSU community database
    folder_id = sys.argv[1] if len(sys.argv) > 1 else "1117Sy2o0JlRB96HaNvvkK9igXIlP6SVq"

    db = create_db_client(folder_id)
    print("Scanning database...")

    if db.scan():
        stats = db.get_stats()
        print(f"\nDatabase Stats:")
        print(f"  Platforms: {stats['platforms']}")
        print(f"  Total Games: {stats['total_games']}")
        print(f"  Total Variants: {stats['total_variants']}")
        print(f"  Android Apps: {stats['total_apps']}")

        print(f"\nPlatforms: {', '.join(stats['platform_names'])}")

        # Test search
        results = db.search_game("Mario")
        if results:
            print(f"\nSearch 'Mario' found {len(results)} games:")
            for game in results[:5]:
                print(f"  - {game.display_name} [{game.platform}]")
    else:
        print("Failed to scan database")
