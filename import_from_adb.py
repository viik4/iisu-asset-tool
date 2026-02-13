"""
Import assets from ADB-connected device directly into asset_storage/ and database.

No server upload needed — files go straight to disk, records straight to SQLite.
Only imports icons, heroes, and logos (no screenshots/slides).
"""
import subprocess
import sqlite3
import hashlib
import uuid
import os
import re
import sys
from pathlib import Path
from PIL import Image

# Paths
BASE_DIR = Path(__file__).parent
ASSET_STORAGE = BASE_DIR / "asset_storage"
DB_PATH = BASE_DIR / "asset_server" / "assets.db"

# iiSU asset path on device
DEVICE_PATH = "/sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles"

# Console folder -> server platform name
PLATFORM_MAP = {
    'nds': 'Nintendo DS',
    'n64': 'N64',
    'snes': 'SNES',
    'nes': 'NES',
    'gba': 'Game Boy Advance',
    'gbc': 'Game Boy Color',
    'gb': 'Game Boy',
    'psx': 'PlayStation',
    'ps1': 'PlayStation',
    'ps2': 'PlayStation 2',
    'psp': 'PlayStation Portable',
    'gc': 'GameCube',
    'gamecube': 'GameCube',
    'wii': 'Wii',
    'wiiu': 'Wii U',
    'switch': 'Nintendo Switch',
    '3ds': 'Nintendo 3DS',
    'n3ds': 'Nintendo 3DS',
    'genesis': 'Mega Drive',
    'megadrive': 'Mega Drive',
    'md': 'Mega Drive',
    'saturn': 'Saturn',
    'dreamcast': 'Dreamcast',
    'dc': 'Dreamcast',
    'arcade': 'Arcade',
    'mame': 'Arcade',
    'neogeo': 'Neo Geo',
    'ngpc': 'Neo Geo Pocket',
    'android': 'Android Apps',
    'android_apps': 'Android Apps',
    'apps': 'Android Apps',
    'pc': 'PC (Generic)',
    'steam': 'Steam',
    'gg': 'Game Gear',
    'xbox': 'Xbox',
    'xbox360': 'Xbox 360',
    'eshop': 'Nintendo eShop',
}

# Asset filename patterns
ASSET_PATTERNS = {
    'icon': ['icon'],
    'hero': ['hero', 'banner', 'background'],
    'logo': ['logo', 'title'],
}

MIME_MAP = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
}


def adb_shell(cmd):
    """Run an adb shell command and return stdout lines."""
    result = subprocess.run(
        ['adb', 'shell', cmd],
        capture_output=True, encoding='utf-8', errors='replace', timeout=30
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]


def adb_pull(remote, local):
    """Pull a file from device. Returns True on success."""
    result = subprocess.run(
        ['adb', 'pull', remote, str(local)],
        capture_output=True, text=True, timeout=60
    )
    return result.returncode == 0


def get_asset_type(filename):
    """Determine asset type from filename. Returns None for non-asset files."""
    name_lower = filename.lower()
    ext = Path(filename).suffix.lower()
    if ext not in MIME_MAP:
        return None
    for asset_type, patterns in ASSET_PATTERNS.items():
        if any(p in name_lower for p in patterns):
            return asset_type
    return None


def clean_game_name(name):
    """Remove region codes, revision info, brackets, etc."""
    result = name
    result = re.sub(r'\s*\([^)]*\)', '', result)
    result = re.sub(r'\s*\[[^\]]*\]', '', result)
    return result.strip()


def get_platform_id(conn, name):
    """Get or create platform, return ID."""
    row = conn.execute("SELECT id FROM platforms WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cursor = conn.execute(
        "INSERT INTO platforms (name, display_name) VALUES (?, ?)", (name, name)
    )
    conn.commit()
    return cursor.lastrowid


def get_game_id(conn, name, platform_id, variant=1):
    """Get or create game, return ID."""
    row = conn.execute(
        "SELECT id FROM games WHERE name = ? AND platform_id = ? AND variant_number = ?",
        (name, platform_id, variant)
    ).fetchone()
    if row:
        return row[0]
    cursor = conn.execute(
        "INSERT INTO games (name, platform_id, variant_number, is_official) VALUES (?, ?, ?, 0)",
        (name, platform_id, variant)
    )
    conn.commit()
    return cursor.lastrowid


def hash_exists(conn, file_hash):
    """Check if this file hash already exists in the database."""
    row = conn.execute(
        "SELECT id FROM assets WHERE file_hash = ? AND is_deleted = 0", (file_hash,)
    ).fetchone()
    return row is not None


def main():
    # Check ADB
    try:
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=10)
        devices = [l for l in result.stdout.strip().split('\n')[1:] if 'device' in l and 'offline' not in l]
        if not devices:
            print("No ADB devices connected.")
            sys.exit(1)
        print(f"Device found: {devices[0].split()[0]}")
    except Exception as e:
        print(f"ADB error: {e}")
        sys.exit(1)

    # Check DB
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Scan device
    print(f"Scanning {DEVICE_PATH}...")
    consoles = adb_shell(f'ls "{DEVICE_PATH}"')
    print(f"Found {len(consoles)} console folders: {', '.join(consoles)}")

    total_imported = 0
    total_skipped = 0
    total_failed = 0

    for console in consoles:
        platform_key = console.lower().replace(' ', '').replace('-', '').replace('_', '')
        platform_name = PLATFORM_MAP.get(platform_key)
        if not platform_name:
            print(f"\n  [SKIP] Unknown platform: {console}")
            continue

        platform_id = get_platform_id(conn, platform_name)
        games = adb_shell(f'ls "{DEVICE_PATH}/{console}"')
        print(f"\n--- {console} -> {platform_name} ({len(games)} games) ---")

        for game_folder in games:
            game_name = clean_game_name(game_folder)
            if not game_name:
                continue

            files = adb_shell(f'ls "{DEVICE_PATH}/{console}/{game_folder}"')
            asset_files = []
            for f in files:
                atype = get_asset_type(f)
                if atype:
                    asset_files.append((f, atype))

            if not asset_files:
                continue

            game_id = get_game_id(conn, game_name, platform_id)

            # Create storage folder
            storage_folder = ASSET_STORAGE / platform_name / game_name
            storage_folder.mkdir(parents=True, exist_ok=True)

            for filename, asset_type in asset_files:
                remote_path = f"{DEVICE_PATH}/{console}/{game_folder}/{filename}"
                unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
                local_path = storage_folder / unique_name

                # Pull file
                if not adb_pull(remote_path, local_path):
                    total_failed += 1
                    print(f"  [FAIL] {game_name}/{filename} - pull failed")
                    continue

                # Get file info
                file_size = local_path.stat().st_size
                ext = local_path.suffix.lower()
                mime_type = MIME_MAP.get(ext, 'image/png')

                # Hash check
                with open(local_path, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()

                if hash_exists(conn, file_hash):
                    local_path.unlink()
                    total_skipped += 1
                    continue

                # Get dimensions
                width, height = None, None
                try:
                    with Image.open(local_path) as img:
                        width, height = img.size
                except:
                    pass

                # Insert DB record
                conn.execute(
                    """INSERT INTO assets
                       (game_id, asset_type, filename, original_filename, file_path,
                        file_size, mime_type, file_hash, width, height, upload_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (game_id, asset_type, unique_name, filename, str(local_path),
                     file_size, mime_type, file_hash, width, height, 'adb')
                )
                conn.commit()
                total_imported += 1
                print(f"  [OK] {game_name}/{filename} ({asset_type})")

    conn.close()

    print(f"\n{'='*50}")
    print(f"Done. Imported: {total_imported}, Skipped: {total_skipped}, Failed: {total_failed}")


if __name__ == "__main__":
    main()
