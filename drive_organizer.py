"""
Google Drive Folder Organizer for iiSU Community Assets

This script helps organize the iiSU Community Assets Google Drive folder.
It can:
- List current folder structure
- Find loose image files that need to be organized into game folders
- Create game folders and move/rename files into them
- Clean up empty folders

SETUP INSTRUCTIONS:
===================
1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable the Google Drive API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Drive API"
   - Click "Enable"
4. Create OAuth credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app"
   - Download the JSON file
   - Save it as "credentials.json" in this folder
5. Run this script - it will open a browser for authentication

Usage:
    python drive_organizer.py --list              # List current structure
    python drive_organizer.py --analyze           # Analyze and suggest changes
    python drive_organizer.py --organize-icons    # Organize loose icon files
    python drive_organizer.py --rename-icons      # Rename 1024x1024 images to icon.{ext} (png/jpg/webp)
    python drive_organizer.py --fix-thumbs        # Remove -thumb suffix from folder names
    python drive_organizer.py --fix-duplicates    # Add _2, _3 suffixes to duplicate folders
    python drive_organizer.py --clean-empty       # Remove empty folders
    python drive_organizer.py --execute           # Actually make changes (careful!)
"""

import os
import sys
import re
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from dataclasses import dataclass, field
from collections import defaultdict

# Google API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False
    print("Google API libraries not installed.")
    print("Run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

# If modifying these scopes, delete the token.json file
SCOPES = ['https://www.googleapis.com/auth/drive']

# iiSU Community Assets folder ID
FOLDER_ID = "1117Sy2o0JlRB96HaNvvkK9igXIlP6SVq"

# Standard platform names
STANDARD_PLATFORMS = [
    "3DS", "Android", "Arcade", "Atari 2600", "Atari 5200", "Atari 7800",
    "CPS-I", "CPS-II", "CPS-III", "DS", "Dreamcast", "FDS",
    "G&W", "GB", "GBA", "GBC", "GG", "Gamecube",
    "Jaguar", "Lynx", "MD", "MS", "MSX", "N64", "N64DD",
    "NES", "Neo Geo", "NGPC", "PC", "PC-98", "PC Engine",
    "PS2", "PS3", "PS4", "PS5", "PSP", "PSVita", "PSX",
    "Saturn", "SNES", "Steam", "Switch", "TG16",
    "VB", "Wii", "Wii U", "Xbox", "Xbox 360", "Xbox One",
    "eShop", "android_apps"
]

# Special folders to skip
SPECIAL_FOLDERS = ["_COLLECTIONS_", "_PLATFORMS_", "_SYMBOLS_"]

# Image extensions
IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.gif']

# iiSU asset naming patterns
IISU_ASSET_NAMES = {
    'icon': 'icon.png',
    'hero': 'hero_1.png',
    'logo': 'title.png',
    'screenshot': 'slide_1.png',
}


@dataclass
class DriveItem:
    """Represents a file or folder in Google Drive."""
    id: str
    name: str
    mime_type: str
    parents: List[str] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return self.mime_type == "application/vnd.google-apps.folder"

    @property
    def is_image(self) -> bool:
        ext = Path(self.name).suffix.lower()
        return ext in IMAGE_EXTENSIONS

    @property
    def extension(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def name_without_ext(self) -> str:
        return Path(self.name).stem


@dataclass
class LooseFile:
    """A loose file that needs to be organized."""
    item: DriveItem
    platform: str
    platform_folder_id: str
    suggested_game_name: str
    suggested_asset_type: str  # icon, hero, logo, screenshot


@dataclass
class OrganizationPlan:
    """Plan for organizing files."""
    platform: str
    platform_folder_id: str
    game_name: str
    files_to_organize: List[Tuple[DriveItem, str]]  # (file, new_name)
    needs_folder_creation: bool = True
    existing_folder_id: Optional[str] = None


class DriveOrganizer:
    """Organizes the iiSU Community Assets Google Drive folder."""

    def __init__(self, folder_id: str = FOLDER_ID):
        self.folder_id = folder_id
        self.service = None
        self.credentials = None

    def authenticate(self) -> bool:
        """Authenticate with Google Drive API."""
        creds = None
        token_path = Path("token.json")
        creds_path = Path("credentials.json")

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not creds_path.exists():
                    print("\n" + "=" * 60)
                    print("ERROR: credentials.json not found!")
                    print("=" * 60)
                    print("\nPlease follow these steps to set up Google Drive API access:\n")
                    print("1. Go to: https://console.cloud.google.com/")
                    print("2. Create a new project (or select an existing one)")
                    print("3. Go to 'APIs & Services' > 'Library'")
                    print("4. Search for 'Google Drive API' and click 'Enable'")
                    print("5. Go to 'APIs & Services' > 'Credentials'")
                    print("6. Click 'Create Credentials' > 'OAuth client ID'")
                    print("7. Choose 'Desktop app' as the application type")
                    print("8. Download the JSON file")
                    print("9. Rename it to 'credentials.json' and put it in:")
                    print(f"   {Path.cwd()}")
                    print("\nThen run this script again.")
                    return False

                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0)

            with open(token_path, 'w') as token:
                token.write(creds.to_json())

        self.credentials = creds
        self.service = build('drive', 'v3', credentials=creds)

        # Thread-local storage for per-thread service instances
        self._thread_local = threading.local()

        return True

    def _get_service(self):
        """Get a thread-local service instance (thread-safe)."""
        if not hasattr(self._thread_local, 'service'):
            # Create a new service instance for this thread
            self._thread_local.service = build('drive', 'v3', credentials=self.credentials)
        return self._thread_local.service

    def list_folder(self, folder_id: str, include_image_metadata: bool = False) -> List[DriveItem]:
        """List contents of a folder.

        Args:
            folder_id: Google Drive folder ID
            include_image_metadata: If True, include imageMediaMetadata for images (slower but avoids extra API calls)
        """
        items = []
        page_token = None

        # Use thread-local service for thread safety
        service = self._get_service()

        # Include image metadata if requested (for icon dimension checking)
        if include_image_metadata:
            fields = 'nextPageToken, files(id, name, mimeType, parents, imageMediaMetadata)'
        else:
            fields = 'nextPageToken, files(id, name, mimeType, parents)'

        while True:
            results = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces='drive',
                fields=fields,
                pageToken=page_token,
                pageSize=1000
            ).execute()

            for item in results.get('files', []):
                drive_item = DriveItem(
                    id=item['id'],
                    name=item['name'],
                    mime_type=item['mimeType'],
                    parents=item.get('parents', [])
                )
                # Attach image metadata if available
                if include_image_metadata and 'imageMediaMetadata' in item:
                    drive_item._image_metadata = item['imageMediaMetadata']
                items.append(drive_item)

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        return items

    def get_folder_structure(self, parallel: bool = True, max_workers: int = 10) -> Dict:
        """Get the complete folder structure."""
        print("Scanning folder structure...")

        structure = {
            'root_id': self.folder_id,
            'platforms': {},
            'special_folders': {},
            'other_items': []
        }

        root_items = self.list_folder(self.folder_id)
        print(f"Found {len([i for i in root_items if i.is_folder])} platform folders")

        # Separate folders for parallel processing
        platform_folders = []
        special_folders = []

        for item in root_items:
            if item.is_folder:
                if item.name in SPECIAL_FOLDERS:
                    special_folders.append(item)
                else:
                    platform_folders.append(item)
            else:
                structure['other_items'].append(item)

        if parallel and len(platform_folders) > 1:
            print(f"Scanning {len(platform_folders)} platforms in parallel...")

            def scan_platform(item: DriveItem) -> Tuple[str, Dict]:
                contents = self.list_folder(item.id)
                return (item.name, {
                    'id': item.id,
                    'subfolders': [c for c in contents if c.is_folder],
                    'files': [c for c in contents if not c.is_folder]
                })

            def scan_special(item: DriveItem) -> Tuple[str, Dict]:
                contents = self.list_folder(item.id)
                return (item.name, {
                    'id': item.id,
                    'contents': contents
                })

            completed = 0
            total = len(platform_folders) + len(special_folders)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all platform folders
                platform_futures = {executor.submit(scan_platform, item): item for item in platform_folders}
                special_futures = {executor.submit(scan_special, item): item for item in special_folders}

                # Collect platform results
                for future in as_completed(platform_futures):
                    name, data = future.result()
                    structure['platforms'][name] = data
                    completed += 1
                    if completed % 10 == 0:
                        print(f"  Scanned {completed}/{total} folders...")

                # Collect special folder results
                for future in as_completed(special_futures):
                    name, data = future.result()
                    structure['special_folders'][name] = data
                    completed += 1

            print(f"  Scan complete: {total} folders scanned")
        else:
            # Sequential scanning
            for item in platform_folders:
                contents = self.list_folder(item.id)
                structure['platforms'][item.name] = {
                    'id': item.id,
                    'subfolders': [c for c in contents if c.is_folder],
                    'files': [c for c in contents if not c.is_folder]
                }

            for item in special_folders:
                contents = self.list_folder(item.id)
                structure['special_folders'][item.name] = {
                    'id': item.id,
                    'contents': contents
                }

        return structure

    def find_loose_files(self, structure: Dict) -> List[LooseFile]:
        """Find all loose image files in platform folders that need organizing."""
        loose_files = []

        for platform_name, platform_data in structure['platforms'].items():
            if platform_name in SPECIAL_FOLDERS:
                continue

            for file_item in platform_data['files']:
                if file_item.is_image:
                    # Try to determine game name from filename
                    game_name = self._extract_game_name(file_item.name)
                    asset_type = self._guess_asset_type(file_item.name)

                    loose_files.append(LooseFile(
                        item=file_item,
                        platform=platform_name,
                        platform_folder_id=platform_data['id'],
                        suggested_game_name=game_name,
                        suggested_asset_type=asset_type
                    ))

        return loose_files

    def _extract_game_name(self, filename: str) -> str:
        """Extract a game name from a filename."""
        # Remove extension
        name = Path(filename).stem

        # Common patterns to clean up
        # Remove common suffixes like _icon, _cover, _hero, etc.
        suffixes_to_remove = [
            '_icon', '_cover', '_hero', '_logo', '_title',
            '_screenshot', '_slide', '_ss', '_1', '_2', '_3',
            ' icon', ' cover', ' hero', ' logo', ' title',
            '-icon', '-cover', '-hero', '-logo', '-title',
        ]

        for suffix in suffixes_to_remove:
            if name.lower().endswith(suffix.lower()):
                name = name[:-len(suffix)]
                break

        # Clean up common prefixes
        prefixes_to_remove = ['icon_', 'cover_', 'hero_', 'logo_']
        for prefix in prefixes_to_remove:
            if name.lower().startswith(prefix.lower()):
                name = name[len(prefix):]
                break

        # Clean up the name
        name = name.strip(' _-')

        # If name is empty or very short, use original
        if len(name) < 2:
            name = Path(filename).stem

        return name

    def _guess_asset_type(self, filename: str) -> str:
        """Guess the asset type from filename."""
        name_lower = filename.lower()

        if any(x in name_lower for x in ['icon', 'cover']):
            return 'icon'
        elif any(x in name_lower for x in ['hero', 'banner', 'background']):
            return 'hero'
        elif any(x in name_lower for x in ['logo', 'title']):
            return 'logo'
        elif any(x in name_lower for x in ['screen', 'slide', 'ss']):
            return 'screenshot'
        else:
            # Default to icon since that's most common
            return 'icon'

    def create_organization_plans(self, loose_files: List[LooseFile]) -> List[OrganizationPlan]:
        """Group loose files and create organization plans."""
        # Group by platform and game name
        grouped = defaultdict(list)
        for lf in loose_files:
            key = (lf.platform, lf.platform_folder_id, lf.suggested_game_name)
            grouped[key].append(lf)

        plans = []
        for (platform, platform_id, game_name), files in grouped.items():
            # Determine file renames
            files_to_organize = []

            # Count asset types for numbering
            type_counts = defaultdict(int)

            for lf in files:
                asset_type = lf.suggested_asset_type
                type_counts[asset_type] += 1
                count = type_counts[asset_type]

                # Generate new filename
                ext = lf.item.extension or '.png'
                if asset_type == 'icon':
                    new_name = f'icon{ext}'
                elif asset_type == 'hero':
                    new_name = f'hero_{count}{ext}'
                elif asset_type == 'logo':
                    new_name = f'title{ext}'
                elif asset_type == 'screenshot':
                    new_name = f'slide_{count}{ext}'
                else:
                    new_name = f'{asset_type}_{count}{ext}'

                files_to_organize.append((lf.item, new_name))

            plans.append(OrganizationPlan(
                platform=platform,
                platform_folder_id=platform_id,
                game_name=game_name,
                files_to_organize=files_to_organize
            ))

        return plans

    def print_structure(self, structure: Dict):
        """Print the folder structure nicely."""
        print("\n" + "=" * 60)
        print("iiSU Community Assets - Current Structure")
        print("=" * 60)

        # Platforms with organized games
        print("\n[PLATFORMS WITH GAME FOLDERS]")
        for name, data in sorted(structure['platforms'].items()):
            game_count = len(data['subfolders'])
            file_count = len(data['files'])
            image_count = sum(1 for f in data['files'] if f.is_image)

            if game_count > 0 or image_count > 0:
                status_parts = []
                if game_count > 0:
                    status_parts.append(f"{game_count} game(s)")
                if image_count > 0:
                    status_parts.append(f"{image_count} loose image(s)")

                print(f"  {name}: {', '.join(status_parts)}")

                # Show some game names
                if game_count > 0 and game_count <= 5:
                    for game in data['subfolders'][:5]:
                        print(f"    [folder] {game.name}")

                # Show loose files
                if image_count > 0 and image_count <= 5:
                    for f in [f for f in data['files'] if f.is_image][:5]:
                        print(f"    [file]   {f.name}")
                elif image_count > 5:
                    for f in [f for f in data['files'] if f.is_image][:3]:
                        print(f"    [file]   {f.name}")
                    print(f"    ... and {image_count - 3} more loose images")

        # Empty platforms
        empty_platforms = [name for name, data in structure['platforms'].items()
                          if not data['subfolders'] and not data['files']]
        if empty_platforms:
            print(f"\n[EMPTY PLATFORM FOLDERS] ({len(empty_platforms)})")
            for name in sorted(empty_platforms)[:10]:
                print(f"  {name}")
            if len(empty_platforms) > 10:
                print(f"  ... and {len(empty_platforms) - 10} more")

        # Summary
        total_games = sum(len(p['subfolders']) for p in structure['platforms'].values())
        total_loose = sum(sum(1 for f in p['files'] if f.is_image) for p in structure['platforms'].values())

        print("\n" + "-" * 60)
        print(f"Total game folders: {total_games}")
        print(f"Total loose images needing organization: {total_loose}")
        print("-" * 60)

    def print_organization_plans(self, plans: List[OrganizationPlan]):
        """Print the organization plans."""
        print("\n" + "=" * 60)
        print("Organization Plan")
        print("=" * 60)

        if not plans:
            print("\nNo loose files found that need organization!")
            return

        for plan in plans:
            print(f"\n[{plan.platform}] Create folder: '{plan.game_name}'")
            for item, new_name in plan.files_to_organize:
                print(f"  - '{item.name}' -> '{new_name}'")

        total_folders = len(plans)
        total_files = sum(len(p.files_to_organize) for p in plans)
        print("\n" + "-" * 60)
        print(f"Will create {total_folders} new game folder(s)")
        print(f"Will organize {total_files} file(s)")
        print("-" * 60)

    def execute_organization(self, plans: List[OrganizationPlan], dry_run: bool = True,
                               parallel: bool = True, max_workers: int = 10) -> Dict:
        """Execute the organization plans."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        results = {
            'folders_created': 0,
            'files_moved': 0,
            'files_renamed': 0,
            'errors': []
        }

        # Thread-safe counters
        lock = threading.Lock()

        def process_plan(plan: OrganizationPlan) -> Tuple[int, int, List[str]]:
            """Process a single plan. Returns (folders_created, files_moved, errors)."""
            folders = 0
            files = 0
            errors = []

            try:
                if dry_run:
                    return (1, len(plan.files_to_organize), [])

                # Create the game folder
                folder_id = self._create_folder(plan.game_name, plan.platform_folder_id)

                if not folder_id:
                    return (0, 0, [f"Failed to create folder: {plan.game_name}"])

                folders = 1

                # Move and rename each file
                for item, new_name in plan.files_to_organize:
                    success = self._move_and_rename(
                        item.id,
                        folder_id,
                        plan.platform_folder_id,
                        new_name
                    )
                    if success:
                        files += 1
                    else:
                        errors.append(f"Failed to move: {item.name}")

            except Exception as e:
                errors.append(f"Error processing {plan.game_name}: {str(e)}")

            return (folders, files, errors)

        if dry_run:
            # Dry run - just count
            for plan in plans:
                print(f"[DRY RUN] Would create: {plan.platform}/{plan.game_name} ({len(plan.files_to_organize)} files)")
                results['folders_created'] += 1
                results['files_moved'] += len(plan.files_to_organize)
        elif parallel and len(plans) > 1:
            # Parallel execution
            print(f"\nProcessing {len(plans)} folders in parallel (max {max_workers} workers)...")

            completed = 0
            total = len(plans)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_plan, plan): plan for plan in plans}

                for future in as_completed(futures):
                    plan = futures[future]
                    folders, files, errors = future.result()

                    with lock:
                        results['folders_created'] += folders
                        results['files_moved'] += files
                        results['errors'].extend(errors)
                        completed += 1

                        # Progress update
                        if completed % 10 == 0 or completed == total:
                            print(f"  Progress: {completed}/{total} folders processed")
        else:
            # Sequential execution
            for i, plan in enumerate(plans):
                print(f"\n[{i+1}/{len(plans)}] Creating: {plan.platform}/{plan.game_name}")
                folders, files, errors = process_plan(plan)
                results['folders_created'] += folders
                results['files_moved'] += files
                results['errors'].extend(errors)

        return results

    def _create_folder(self, name: str, parent_id: str) -> Optional[str]:
        """Create a new folder."""
        try:
            service = self._get_service()
            file_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_id]
            }
            folder = service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            return folder.get('id')
        except HttpError as e:
            print(f"Error creating folder: {e}")
            return None

    def _move_and_rename(self, file_id: str, new_parent_id: str,
                         old_parent_id: str, new_name: str) -> bool:
        """Move a file to a new folder and rename it."""
        try:
            service = self._get_service()
            service.files().update(
                fileId=file_id,
                addParents=new_parent_id,
                removeParents=old_parent_id,
                body={'name': new_name},
                fields='id, parents'
            ).execute()
            return True
        except HttpError as e:
            print(f"Error moving/renaming file: {e}")
            return False

    def remove_empty_folders(self, structure: Dict, dry_run: bool = True) -> int:
        """Remove empty platform folders."""
        removed = 0

        service = self._get_service()

        for name, data in structure['platforms'].items():
            if not data['subfolders'] and not data['files']:
                if dry_run:
                    print(f"  Would remove: {name}")
                    removed += 1
                else:
                    try:
                        service.files().delete(fileId=data['id']).execute()
                        print(f"  Removed: {name}")
                        removed += 1
                    except HttpError as e:
                        print(f"  Error removing {name}: {e}")

        return removed

    def get_image_metadata(self, file_id: str) -> Optional[Dict]:
        """Get image metadata including dimensions (fallback for individual files)."""
        try:
            service = self._get_service()
            file_info = service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, imageMediaMetadata'
            ).execute()
            return file_info.get('imageMediaMetadata')
        except HttpError as e:
            return None

    def find_square_icons(self, structure: Dict, target_size: int = 1024,
                          parallel: bool = True, max_workers: int = 10) -> List[Tuple[DriveItem, str, str]]:
        """
        Find all image files with square dimensions (e.g., 1024x1024) that aren't already named icon.*

        Returns list of (DriveItem, parent_folder_id, current_path) tuples.

        This method fetches image metadata during folder listing to avoid slow individual API calls.
        """
        candidates = []

        print(f"Scanning for {target_size}x{target_size} images that need renaming...")

        # Count total game folders for progress
        total_game_folders = sum(
            len(platform_data['subfolders'])
            for platform_name, platform_data in structure['platforms'].items()
            if platform_name not in SPECIAL_FOLDERS
        )
        scanned_folders = [0]
        lock = threading.Lock()

        def scan_game_folder(args):
            """Scan a single game folder for square icons."""
            platform_name, game_folder = args
            folder_candidates = []

            # List folder contents WITH image metadata included
            game_contents = self.list_folder(game_folder.id, include_image_metadata=True)

            for item in game_contents:
                if item.is_image and not item.name.lower().startswith('icon.'):
                    # Check dimensions from metadata attached during listing
                    metadata = getattr(item, '_image_metadata', None)
                    if metadata:
                        width = metadata.get('width', 0)
                        height = metadata.get('height', 0)

                        if width == height == target_size:
                            path = f"{platform_name}/{game_folder.name}/{item.name}"
                            folder_candidates.append((item, game_folder.id, path))

            with lock:
                scanned_folders[0] += 1
                if scanned_folders[0] % 50 == 0 or scanned_folders[0] == total_game_folders:
                    print(f"  Scanned {scanned_folders[0]}/{total_game_folders} game folders...")

            return folder_candidates

        # Build list of (platform_name, game_folder) tuples
        folder_tasks = []
        for platform_name, platform_data in structure['platforms'].items():
            if platform_name in SPECIAL_FOLDERS:
                continue
            for game_folder in platform_data['subfolders']:
                folder_tasks.append((platform_name, game_folder))

        print(f"Scanning {len(folder_tasks)} game folders for {target_size}x{target_size} images...")

        if parallel and len(folder_tasks) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(scan_game_folder, task) for task in folder_tasks]

                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        candidates.extend(result)
        else:
            for task in folder_tasks:
                result = scan_game_folder(task)
                if result:
                    candidates.extend(result)

        print(f"Found {len(candidates)} images with {target_size}x{target_size} dimensions")
        return candidates

    def rename_to_icon(self, file_id: str, current_name: str) -> bool:
        """Rename a file to icon.{ext} (preserving original extension like .png, .jpg, .webp)."""
        ext = Path(current_name).suffix.lower()
        new_name = f"icon{ext}"

        try:
            service = self._get_service()
            service.files().update(
                fileId=file_id,
                body={'name': new_name},
                fields='id, name'
            ).execute()
            return True
        except HttpError as e:
            print(f"Error renaming file: {e}")
            return False

    def execute_icon_renames(self, candidates: List[Tuple[DriveItem, str, str]],
                              dry_run: bool = True, parallel: bool = True,
                              max_workers: int = 10) -> Dict:
        """Execute the icon rename operations."""
        results = {
            'renamed': 0,
            'errors': []
        }

        if not candidates:
            print("No files to rename.")
            return results

        lock = threading.Lock()

        def rename_file(file_tuple: Tuple[DriveItem, str, str]) -> Tuple[bool, Optional[str]]:
            item, parent_id, path = file_tuple
            ext = item.extension
            new_name = f"icon{ext}"

            if dry_run:
                return (True, None)

            if self.rename_to_icon(item.id, item.name):
                return (True, None)
            else:
                return (False, f"Failed to rename: {path}")

        if dry_run:
            print("\n[DRY RUN] Would rename the following files:")
            for item, _, path in candidates:
                ext = item.extension
                print(f"  {path} -> icon{ext}")
            results['renamed'] = len(candidates)
        elif parallel and len(candidates) > 1:
            print(f"\nRenaming {len(candidates)} files in parallel...")
            completed = 0

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(rename_file, c): c for c in candidates}

                for future in as_completed(futures):
                    success, error = future.result()

                    with lock:
                        if success:
                            results['renamed'] += 1
                        if error:
                            results['errors'].append(error)

                        completed += 1
                        if completed % 20 == 0 or completed == len(candidates):
                            print(f"  Progress: {completed}/{len(candidates)}")
        else:
            for i, (item, parent_id, path) in enumerate(candidates):
                ext = item.extension
                print(f"[{i+1}/{len(candidates)}] Renaming: {path} -> icon{ext}")
                success, error = rename_file((item, parent_id, path))
                if success:
                    results['renamed'] += 1
                if error:
                    results['errors'].append(error)

        return results

    def find_thumb_folders(self, structure: Dict) -> List[Tuple[DriveItem, str, str]]:
        """
        Find all folders with -thumb suffix that need renaming.

        Returns list of (DriveItem, platform_name, new_name) tuples.
        """
        candidates = []

        print("Scanning for folders with -thumb suffix...")

        for platform_name, platform_data in structure['platforms'].items():
            if platform_name in SPECIAL_FOLDERS:
                continue

            for game_folder in platform_data['subfolders']:
                name = game_folder.name
                # Check for -thumb suffix (case insensitive)
                if name.lower().endswith('-thumb'):
                    new_name = name[:-6]  # Remove -thumb
                    if new_name:  # Make sure we have something left
                        candidates.append((game_folder, platform_name, new_name))

        print(f"Found {len(candidates)} folders with -thumb suffix")
        return candidates

    def find_duplicate_folders(self, structure: Dict) -> List[Tuple[DriveItem, str, str]]:
        """
        Find duplicate folder names within each platform and suggest _2, _3 suffixes.

        Returns list of (DriveItem, platform_name, new_name) tuples for folders that need renaming.
        """
        candidates = []

        print("Scanning for duplicate folder names...")

        for platform_name, platform_data in structure['platforms'].items():
            if platform_name in SPECIAL_FOLDERS:
                continue

            # Group folders by normalized name (lowercase, no _N suffix)
            name_groups = defaultdict(list)
            for game_folder in platform_data['subfolders']:
                # Get base name (remove existing _N suffix if present)
                name = game_folder.name
                base_name = re.sub(r'_\d+$', '', name)
                name_groups[base_name.lower()].append(game_folder)

            # Find groups with duplicates
            for base_name, folders in name_groups.items():
                if len(folders) > 1:
                    # Sort by name to be consistent
                    folders.sort(key=lambda x: x.name)

                    # Find existing _N suffixes
                    existing_nums = set()
                    for f in folders:
                        match = re.search(r'_(\d+)$', f.name)
                        if match:
                            existing_nums.add(int(match.group(1)))

                    # Assign new names
                    next_num = 2
                    for folder in folders:
                        # Skip if already has a valid suffix
                        if re.search(r'_\d+$', folder.name):
                            continue

                        # Find next available number
                        while next_num in existing_nums:
                            next_num += 1

                        # First folder without suffix becomes the base (no change needed)
                        # unless there's already a _1 version
                        if next_num == 2 and 1 not in existing_nums:
                            # Keep first one as-is, start numbering from second
                            next_num = 2
                            continue

                        new_name = f"{folder.name}_{next_num}"
                        candidates.append((folder, platform_name, new_name))
                        existing_nums.add(next_num)
                        next_num += 1

        print(f"Found {len(candidates)} folders that need _N suffixes")
        return candidates

    def rename_folder(self, folder_id: str, new_name: str) -> bool:
        """Rename a folder."""
        try:
            service = self._get_service()
            service.files().update(
                fileId=folder_id,
                body={'name': new_name},
                fields='id, name'
            ).execute()
            return True
        except HttpError as e:
            print(f"Error renaming folder: {e}")
            return False

    def execute_folder_renames(self, candidates: List[Tuple[DriveItem, str, str]],
                                dry_run: bool = True, parallel: bool = True,
                                max_workers: int = 10) -> Dict:
        """Execute folder rename operations."""
        results = {
            'renamed': 0,
            'errors': []
        }

        if not candidates:
            print("No folders to rename.")
            return results

        lock = threading.Lock()

        def rename_one(item_tuple: Tuple[DriveItem, str, str]) -> Tuple[bool, Optional[str]]:
            folder, platform, new_name = item_tuple

            if dry_run:
                return (True, None)

            if self.rename_folder(folder.id, new_name):
                return (True, None)
            else:
                return (False, f"Failed to rename: {platform}/{folder.name}")

        if dry_run:
            print("\n[DRY RUN] Would rename the following folders:")
            for folder, platform, new_name in candidates:
                print(f"  {platform}/{folder.name} -> {new_name}")
            results['renamed'] = len(candidates)
        elif parallel and len(candidates) > 1:
            print(f"\nRenaming {len(candidates)} folders in parallel...")
            completed = 0

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(rename_one, c): c for c in candidates}

                for future in as_completed(futures):
                    success, error = future.result()

                    with lock:
                        if success:
                            results['renamed'] += 1
                        if error:
                            results['errors'].append(error)

                        completed += 1
                        if completed % 20 == 0 or completed == len(candidates):
                            print(f"  Progress: {completed}/{len(candidates)}")
        else:
            for i, (folder, platform, new_name) in enumerate(candidates):
                print(f"[{i+1}/{len(candidates)}] Renaming: {platform}/{folder.name} -> {new_name}")
                success, error = rename_one((folder, platform, new_name))
                if success:
                    results['renamed'] += 1
                if error:
                    results['errors'].append(error)

        return results


def main():
    parser = argparse.ArgumentParser(
        description='Organize the iiSU Community Assets Google Drive folder',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--list', action='store_true',
                        help='List current folder structure')
    parser.add_argument('--analyze', action='store_true',
                        help='Analyze loose files and show organization plan')
    parser.add_argument('--organize-icons', action='store_true',
                        help='Organize loose icon files into game folders')
    parser.add_argument('--rename-icons', action='store_true',
                        help='Rename 1024x1024 images to icon.{ext} (preserves extension)')
    parser.add_argument('--icon-size', type=int, default=1024,
                        help='Target icon size for --rename-icons (default: 1024)')
    parser.add_argument('--fix-thumbs', action='store_true',
                        help='Remove -thumb suffix from folder names')
    parser.add_argument('--fix-duplicates', action='store_true',
                        help='Add _2, _3 suffixes to duplicate folder names')
    parser.add_argument('--clean-empty', action='store_true',
                        help='Remove empty platform folders')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute changes (without this, only shows what would be done)')
    parser.add_argument('--folder-id', type=str, default=FOLDER_ID,
                        help='Google Drive folder ID to organize')
    parser.add_argument('--workers', type=int, default=10,
                        help='Number of parallel workers (default: 10)')
    parser.add_argument('--sequential', action='store_true',
                        help='Disable parallel processing (slower but safer)')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompts')

    args = parser.parse_args()

    # Default to list + analyze if nothing specified
    if not any([args.list, args.analyze, args.organize_icons, args.rename_icons,
                args.fix_thumbs, args.fix_duplicates, args.clean_empty]):
        args.list = True
        args.analyze = True

    dry_run = not args.execute

    # Create organizer and authenticate
    organizer = DriveOrganizer(args.folder_id)

    print("Authenticating with Google Drive...")
    if not organizer.authenticate():
        sys.exit(1)

    print("Authentication successful!\n")

    # Get folder structure
    structure = organizer.get_folder_structure()

    if args.list:
        organizer.print_structure(structure)

    if args.analyze or args.organize_icons:
        loose_files = organizer.find_loose_files(structure)
        plans = organizer.create_organization_plans(loose_files)
        organizer.print_organization_plans(plans)

        if args.organize_icons and plans:
            if dry_run:
                print("\n[DRY RUN MODE] - No changes will be made")
                print("Add --execute to actually make these changes")
            else:
                print("\n" + "=" * 60)
                print("EXECUTING ORGANIZATION")
                print("=" * 60)
                if not args.yes:
                    confirm = input("\nAre you sure you want to proceed? (yes/no): ")
                    if confirm.lower() != 'yes':
                        print("Aborted.")
                        sys.exit(0)

            results = organizer.execute_organization(
                plans,
                dry_run=dry_run,
                parallel=not args.sequential,
                max_workers=args.workers
            )

            print("\n" + "-" * 60)
            print("Results:")
            print(f"  Folders created: {results['folders_created']}")
            print(f"  Files organized: {results['files_moved']}")
            if results['errors']:
                print(f"  Errors: {len(results['errors'])}")
                for err in results['errors']:
                    print(f"    - {err}")

    if args.rename_icons:
        print("\n" + "=" * 60)
        print(f"RENAME {args.icon_size}x{args.icon_size} IMAGES TO icon.{{ext}}")
        print("=" * 60)

        candidates = organizer.find_square_icons(
            structure,
            target_size=args.icon_size,
            parallel=not args.sequential,
            max_workers=args.workers
        )

        if candidates:
            print(f"\nFound {len(candidates)} file(s) to rename:")
            for item, _, path in candidates[:20]:
                print(f"  {path}")
            if len(candidates) > 20:
                print(f"  ... and {len(candidates) - 20} more")

            if dry_run:
                print("\n[DRY RUN MODE] - No changes will be made")
                print("Add --execute to actually rename these files")
            else:
                print("\n" + "=" * 60)
                print("EXECUTING RENAMES")
                print("=" * 60)
                if not args.yes:
                    confirm = input("\nAre you sure you want to proceed? (yes/no): ")
                    if confirm.lower() != 'yes':
                        print("Aborted.")
                        sys.exit(0)

            results = organizer.execute_icon_renames(
                candidates,
                dry_run=dry_run,
                parallel=not args.sequential,
                max_workers=args.workers
            )

            print("\n" + "-" * 60)
            print("Results:")
            print(f"  Files renamed: {results['renamed']}")
            if results['errors']:
                print(f"  Errors: {len(results['errors'])}")
                for err in results['errors'][:10]:
                    print(f"    - {err}")
                if len(results['errors']) > 10:
                    print(f"    ... and {len(results['errors']) - 10} more errors")
        else:
            print(f"\nNo {args.icon_size}x{args.icon_size} images found that need renaming.")

    if args.fix_thumbs:
        print("\n" + "=" * 60)
        print("FIX -thumb FOLDER NAMES")
        print("=" * 60)

        candidates = organizer.find_thumb_folders(structure)

        if candidates:
            print(f"\nFound {len(candidates)} folder(s) with -thumb suffix:")
            for folder, platform, new_name in candidates[:20]:
                print(f"  {platform}/{folder.name} -> {new_name}")
            if len(candidates) > 20:
                print(f"  ... and {len(candidates) - 20} more")

            if dry_run:
                print("\n[DRY RUN MODE] - No changes will be made")
                print("Add --execute to actually rename these folders")
            else:
                print("\n" + "=" * 60)
                print("EXECUTING FOLDER RENAMES")
                print("=" * 60)
                if not args.yes:
                    confirm = input("\nAre you sure you want to proceed? (yes/no): ")
                    if confirm.lower() != 'yes':
                        print("Aborted.")
                        sys.exit(0)

            results = organizer.execute_folder_renames(
                candidates,
                dry_run=dry_run,
                parallel=not args.sequential,
                max_workers=args.workers
            )

            print("\n" + "-" * 60)
            print("Results:")
            print(f"  Folders renamed: {results['renamed']}")
            if results['errors']:
                print(f"  Errors: {len(results['errors'])}")
                for err in results['errors'][:10]:
                    print(f"    - {err}")
                if len(results['errors']) > 10:
                    print(f"    ... and {len(results['errors']) - 10} more errors")
        else:
            print("\nNo folders with -thumb suffix found.")

    if args.fix_duplicates:
        print("\n" + "=" * 60)
        print("FIX DUPLICATE FOLDER NAMES")
        print("=" * 60)

        candidates = organizer.find_duplicate_folders(structure)

        if candidates:
            print(f"\nFound {len(candidates)} folder(s) that need _N suffixes:")
            for folder, platform, new_name in candidates[:20]:
                print(f"  {platform}/{folder.name} -> {new_name}")
            if len(candidates) > 20:
                print(f"  ... and {len(candidates) - 20} more")

            if dry_run:
                print("\n[DRY RUN MODE] - No changes will be made")
                print("Add --execute to actually rename these folders")
            else:
                print("\n" + "=" * 60)
                print("EXECUTING FOLDER RENAMES")
                print("=" * 60)
                if not args.yes:
                    confirm = input("\nAre you sure you want to proceed? (yes/no): ")
                    if confirm.lower() != 'yes':
                        print("Aborted.")
                        sys.exit(0)

            results = organizer.execute_folder_renames(
                candidates,
                dry_run=dry_run,
                parallel=not args.sequential,
                max_workers=args.workers
            )

            print("\n" + "-" * 60)
            print("Results:")
            print(f"  Folders renamed: {results['renamed']}")
            if results['errors']:
                print(f"  Errors: {len(results['errors'])}")
                for err in results['errors'][:10]:
                    print(f"    - {err}")
                if len(results['errors']) > 10:
                    print(f"    ... and {len(results['errors']) - 10} more errors")
        else:
            print("\nNo duplicate folder names found that need renaming.")

    if args.clean_empty:
        print("\n[CLEANING EMPTY FOLDERS]")
        if dry_run:
            print("(Dry run - showing what would be removed)")

        removed = organizer.remove_empty_folders(structure, dry_run=dry_run)

        if dry_run:
            print(f"\nWould remove {removed} empty folder(s)")
            print("Add --execute to actually remove them")
        else:
            print(f"\nRemoved {removed} empty folder(s)")


if __name__ == "__main__":
    main()
