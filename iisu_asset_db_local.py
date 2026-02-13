"""
iiSU Asset Database Client - Asset Server Backend

Client for the iiSU Community Asset Server at https://assets.iisu.community

Features:
- Browse and search themed assets by platform/game
- Download assets (icons)
- Upload new assets to share with the community
- Admin dashboard for moderation
"""

import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Union
from pathlib import Path
from enum import Enum
from datetime import datetime
import difflib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class AssetType(Enum):
    """Types of assets in iiSU structure."""
    ICON = "icon"
    HERO = "hero"
    LOGO = "logo"
    SOUNDBYTE = "soundbyte"


@dataclass
class ThemedAssetFile:
    """A single asset file from the database."""
    filename: str
    asset_type: AssetType
    download_url: str
    file_id: str  # For local server, this is the asset ID as string
    size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail_url: Optional[str] = None

    @property
    def is_image(self) -> bool:
        return self.asset_type != AssetType.SOUNDBYTE

    def get_preview_url(self, width: int = 400) -> str:
        """Get a URL suitable for previewing this asset."""
        if self.thumbnail_url:
            return self.thumbnail_url
        return self.download_url

    def get_thumbnail_url(self, width: int = 200) -> str:
        """Get a thumbnail URL for smaller previews."""
        if self.thumbnail_url:
            return self.thumbnail_url
        return self.download_url


@dataclass
class ThemedAssetVariant:
    """A variant of themed assets for a game."""
    game_name: str
    variant_number: int
    folder_name: str  # For compatibility
    folder_id: str    # For local server, this is the game ID as string
    platform: str
    assets: List[ThemedAssetFile] = field(default_factory=list)
    _game_id: Optional[int] = None  # Internal: actual database game ID

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

    def get_asset(self, asset_type: AssetType) -> Optional[ThemedAssetFile]:
        """Get first asset of given type."""
        for asset in self.assets:
            if asset.asset_type == asset_type:
                return asset
        return None

    def get_assets(self, asset_type: AssetType) -> List[ThemedAssetFile]:
        """Get all assets of given type."""
        return [a for a in self.assets if a.asset_type == asset_type]


@dataclass
class ThemedGame:
    """A game with one or more themed asset variants."""
    game_name: str
    platform: str
    variants: List[ThemedAssetVariant] = field(default_factory=list)
    is_official: bool = False

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
    app_name: str
    variants: List[ThemedAssetVariant] = field(default_factory=list)

    @property
    def variant_count(self) -> int:
        return len(self.variants)


class IisuAssetDBLocal:
    """
    Client for the iiSU Asset Server (local/self-hosted).

    Connects to a FastAPI backend that stores assets locally.
    Supports public read and upload, admin-only delete.
    """

    def __init__(self, server_url: str = "https://assets.iisu.community"):
        """
        Initialize the client.

        Args:
            server_url: Base URL of the asset server
        """
        self.server_url = server_url.rstrip('/')
        self.session = self._create_session()

        # Cached data
        self._platforms: Dict[str, int] = {}  # platform_name -> platform_id
        self._games: Dict[str, List[ThemedGame]] = {}  # platform -> games
        self._apps: List[ThemedApp] = []
        self._last_scan: Optional[datetime] = None
        self._scan_cache_minutes = 5  # Shorter cache since local server is fast

    def _create_session(self) -> requests.Session:
        """Create session with retries and connection pooling."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "iiSU-Asset-Tool/1.0",
            "Accept": "application/json",
        })

        retry = Retry(total=3, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=retry)
        session.mount('http://', adapter)
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

    def is_server_available(self) -> bool:
        """Check if the asset server is running and accessible."""
        try:
            response = self.session.get(f"{self.server_url}/", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def scan(self, force: bool = False) -> bool:
        """
        Scan the database.

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

            # Fetch platforms
            response = self.session.get(f"{self.server_url}/api/platforms", timeout=30)
            response.raise_for_status()
            platforms = response.json()

            for p in platforms:
                self._platforms[p['name']] = p['id']

            # Fetch all games
            response = self.session.get(f"{self.server_url}/api/games", timeout=60)
            response.raise_for_status()
            games_data = response.json()

            # Group games by platform and name
            games_dict: Dict[str, Dict[str, ThemedGame]] = {}  # platform -> {name -> ThemedGame}

            for g in games_data:
                platform = g['platform_name']
                game_name = g['name']
                variant_num = g['variant_number']

                if platform not in games_dict:
                    games_dict[platform] = {}

                if game_name not in games_dict[platform]:
                    games_dict[platform][game_name] = ThemedGame(
                        game_name=game_name,
                        platform=platform,
                        is_official=bool(g.get('is_official', False))
                    )
                elif g.get('is_official', False):
                    # If any variant is official, mark the game as official
                    games_dict[platform][game_name].is_official = True

                # Create variant with assets
                variant = ThemedAssetVariant(
                    game_name=game_name,
                    variant_number=variant_num,
                    folder_name=game_name if variant_num == 1 else f"{game_name}_{variant_num}",
                    folder_id=str(g['id']),
                    platform=platform,
                    _game_id=g['id']
                )

                # Parse assets
                for a in g.get('assets', []):
                    asset_type = self._parse_asset_type(a['asset_type'])
                    if asset_type:
                        asset = ThemedAssetFile(
                            filename=a['filename'],
                            asset_type=asset_type,
                            download_url=a['download_url'],
                            file_id=str(a['id']),
                            size=a.get('file_size'),
                            width=a.get('width'),
                            height=a.get('height'),
                            thumbnail_url=a.get('thumbnail_url')
                        )
                        variant.assets.append(asset)

                games_dict[platform][game_name].variants.append(variant)

            # Sort and store
            for platform, games in games_dict.items():
                for game in games.values():
                    game.variants.sort(key=lambda v: v.variant_number)

                # Handle Android apps separately
                if platform.lower() == 'android apps':
                    for game in games.values():
                        app = ThemedApp(
                            package_name=game.game_name,
                            app_name=self._package_to_app_name(game.game_name),
                            variants=game.variants
                        )
                        self._apps.append(app)
                    self._apps.sort(key=lambda a: a.app_name.lower())
                else:
                    self._games[platform] = sorted(
                        games.values(),
                        key=lambda g: g.game_name.lower()
                    )

            self._last_scan = datetime.now()
            return True

        except Exception as e:
            print(f"Error scanning database: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _parse_asset_type(self, type_str: str) -> Optional[AssetType]:
        """Parse asset type string to enum."""
        type_map = {
            'icon': AssetType.ICON,
            'hero': AssetType.HERO,
            'logo': AssetType.LOGO,
            'soundbyte': AssetType.SOUNDBYTE,
        }
        return type_map.get(type_str.lower())

    def _package_to_app_name(self, package_name: str) -> str:
        """Convert package name to display name."""
        parts = package_name.split('.')
        if parts:
            name = parts[-1]
            name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
            name = name.replace('_', ' ')
            return ' '.join(word.capitalize() for word in name.split())
        return package_name

    # === Public API Methods ===

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
        """Get a variant with its assets (already loaded in scan)."""
        return variant

    def search_game(self, query: str, platform: Optional[str] = None,
                    limit: int = 20) -> List[ThemedGame]:
        """Search for games by name."""
        # Try server search first
        try:
            response = self.session.get(
                f"{self.server_url}/api/search",
                params={'q': query, 'limit': limit},
                timeout=10
            )
            if response.status_code == 200:
                results = response.json()
                # Convert to ThemedGame objects
                games = []
                for r in results:
                    if platform and r['platform_name'].lower() != platform.lower():
                        continue
                    game = self.find_game_exact(r['name'], r['platform_name'])
                    if game:
                        games.append(game)
                return games[:limit]
        except Exception:
            pass

        # Fallback to local search
        results: List[tuple] = []
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
        results: List[tuple] = []
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

    # === Upload Methods (Public - Write Only) ===

    def upload_asset(self, file_path: Path, game_name: str, platform: str,
                     asset_type: str, variant_number: int = 1) -> Dict[str, Any]:
        """
        Upload a new asset to the database.

        Args:
            file_path: Path to the asset file
            game_name: Name of the game
            platform: Platform name (e.g., "SNES", "PlayStation")
            asset_type: Type of asset ("icon")
            variant_number: Variant number (1 for original, 2+ for alternates)

        Returns:
            Dict with 'success', 'message', 'game_id', 'asset_id'
        """
        if not file_path.exists():
            return {'success': False, 'message': f"File not found: {file_path}"}

        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f)}
                data = {
                    'game_name': game_name,
                    'platform': platform,
                    'asset_type': asset_type,
                    'variant_number': variant_number
                }

                response = self.session.post(
                    f"{self.server_url}/api/upload",
                    files=files,
                    data=data,
                    timeout=120
                )

                return response.json()

        except Exception as e:
            return {'success': False, 'message': str(e)}

    # === Download Methods ===

    def download_asset(self, asset: ThemedAssetFile, output_path: Path) -> bool:
        """Download a single asset file."""
        try:
            response = self.session.get(asset.download_url, timeout=60, stream=True)
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
        results = {}
        for asset in variant.assets:
            output_path = output_folder / asset.filename
            success = self.download_asset(asset, output_path)
            results[asset.filename] = success

        return results

    # === Stats ===

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            response = self.session.get(f"{self.server_url}/api/stats", timeout=10)
            if response.status_code == 200:
                stats = response.json()
                return {
                    'platforms': stats['platforms'],
                    'platform_names': self.get_platforms(),
                    'total_games': stats['games'],
                    'total_variants': stats['games'],  # Approximate
                    'total_apps': len(self._apps),
                    'total_size_mb': stats['total_size_mb'],
                    'last_scan': self._last_scan.isoformat() if self._last_scan else None,
                }
        except Exception:
            pass

        # Fallback to local stats
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


def create_local_client(server_url: str = "https://assets.iisu.community") -> IisuAssetDBLocal:
    """Create and return a local server client."""
    return IisuAssetDBLocal(server_url)


# Unified client wrapper (kept for backward compatibility)
class IisuAssetDBUnified:
    """
    Unified client wrapper for the iiSU Asset Server.

    Usage:
        db = IisuAssetDBUnified(server_url="https://assets.iisu.community")
        db.scan()
    """

    def __init__(self, server_url: str = "https://assets.iisu.community"):
        self.server_url = server_url

        self._local_client: Optional[IisuAssetDBLocal] = None
        self._active_client = None
        self._using_local = False

    def scan(self, force: bool = False) -> bool:
        """Scan database using the asset server."""
        self._local_client = IisuAssetDBLocal(self.server_url)
        if self._local_client.is_server_available():
            if self._local_client.scan(force):
                self._active_client = self._local_client
                self._using_local = True
                print(f"Connected to asset server at {self.server_url}")
                return True

        print("Asset server unavailable")
        return False

    @property
    def is_using_local(self) -> bool:
        return self._using_local

    @property
    def is_scanned(self) -> bool:
        return self._active_client is not None and self._active_client.is_scanned

    # Delegate all methods to active client
    def get_platforms(self) -> List[str]:
        return self._active_client.get_platforms() if self._active_client else []

    def get_games(self, platform: str) -> List[ThemedGame]:
        return self._active_client.get_games(platform) if self._active_client else []

    def get_apps(self) -> List[ThemedApp]:
        return self._active_client.get_apps() if self._active_client else []

    def get_variant_with_assets(self, variant) -> ThemedAssetVariant:
        if self._active_client:
            return self._active_client.get_variant_with_assets(variant)
        return variant

    def search_game(self, query: str, platform: str = None, limit: int = 20):
        if self._active_client:
            return self._active_client.search_game(query, platform, limit)
        return []

    def search_app(self, query: str, limit: int = 20):
        if self._active_client:
            return self._active_client.search_app(query, limit)
        return []

    def find_game_exact(self, game_name: str, platform: str):
        if self._active_client:
            return self._active_client.find_game_exact(game_name, platform)
        return None

    def download_asset(self, asset, output_path: Path) -> bool:
        if self._active_client:
            return self._active_client.download_asset(asset, output_path)
        return False

    def download_variant(self, variant, output_folder: Path) -> Dict[str, bool]:
        if self._active_client:
            return self._active_client.download_variant(variant, output_folder)
        return {}

    def get_stats(self) -> Dict[str, Any]:
        if self._active_client:
            stats = self._active_client.get_stats()
            stats['using_local_server'] = self._using_local
            return stats
        return {'using_local_server': False}

    def upload_asset(self, file_path: Path, game_name: str, platform: str,
                     asset_type: str, variant_number: int = 1) -> Dict[str, Any]:
        if not self._local_client:
            return {
                'success': False,
                'message': 'Not connected to asset server.'
            }
        return self._local_client.upload_asset(
            file_path, game_name, platform, asset_type, variant_number
        )


def create_unified_client(
    server_url: str = "https://assets.iisu.community"
) -> IisuAssetDBUnified:
    """Create a unified client for the asset server."""
    return IisuAssetDBUnified(server_url)


# For testing
if __name__ == "__main__":
    import sys

    server_url = sys.argv[1] if len(sys.argv) > 1 else "https://assets.iisu.community"

    print(f"Testing connection to {server_url}...")

    client = IisuAssetDBLocal(server_url)

    if client.is_server_available():
        print("✓ Server is available")

        if client.scan():
            stats = client.get_stats()
            print(f"\nDatabase Stats:")
            print(f"  Platforms: {stats['platforms']}")
            print(f"  Total Games: {stats['total_games']}")
            print(f"  Android Apps: {stats['total_apps']}")

            if 'total_size_mb' in stats:
                print(f"  Total Size: {stats['total_size_mb']:.1f} MB")

            print(f"\nPlatforms: {', '.join(stats['platform_names'])}")

            # Test search
            results = client.search_game("Mario")
            if results:
                print(f"\nSearch 'Mario' found {len(results)} games:")
                for game in results[:5]:
                    print(f"  - {game.display_name} [{game.platform}]")
        else:
            print("✗ Failed to scan database")
    else:
        print("✗ Server is not available")
        print("\nTo start the server, run:")
        print("  python -m asset_server.run")
