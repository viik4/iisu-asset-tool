"""
Import official assets from extracted iiSU Asset Pack into the Workshop server.

Uploads every image file as an official icon, with correct platform mapping.
Skips _SYMBOLS_ and _PSD_ folders.
"""
import os
import sys
import requests
from pathlib import Path

SERVER = "http://localhost:8765"
ADMIN_KEY = Path("asset_server/.admin_key").read_text().strip()
PACK_DIR = Path(r"C:\Users\17317\Documents\GitHub\iisu-asset-tool\iiSUAssetPack\iiSU Asset Pack")

# Exact mapping from folder names in the pack to server platform names
PLATFORM_MAP = {
    "3DS": "Nintendo 3DS",
    "Android": "Android Apps",
    "DS": "Nintendo DS",
    "Dreamcast": "Dreamcast",
    "GB": "Game Boy",
    "GBA": "Game Boy Advance",
    "GBC": "Game Boy Color",
    "GG": "Game Gear",
    "Gamecube": "GameCube",
    "MD": "Mega Drive",
    "N64": "N64",
    "NES": "NES",
    "NGPC": "Neo Geo Pocket",
    "PS2": "PlayStation 2",
    "PSP": "PlayStation Portable",
    "PSVita": "PlayStation Vita",
    "PSX": "PlayStation",
    "SNES": "SNES",
    "Saturn": "Saturn",
    "Switch": "Nintendo Switch",
    "Wii": "Wii",
    "Wii U": "Wii U",
    "eShop": "Nintendo eShop",
}

# System asset folders
SYSTEM_FOLDERS = {
    "_COLLECTIONS_": "collection_icon",
    "_PLATFORMS_": "platform_cover",
}

# Skip these
SKIP_FOLDERS = {"_PSD_", "_SYMBOLS_"}

VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def main():
    if not PACK_DIR.exists():
        print(f"Pack directory not found: {PACK_DIR}")
        sys.exit(1)

    # Check server
    try:
        r = requests.get(f"{SERVER}/api/stats")
        stats = r.json()
        print(f"Server online. Current: {stats['games']} games, {stats['assets']} assets")
    except Exception as e:
        print(f"Cannot reach server: {e}")
        sys.exit(1)

    success = 0
    skipped = 0
    failed = 0

    # Walk the pack directory
    for folder in sorted(PACK_DIR.iterdir()):
        if not folder.is_dir():
            continue

        folder_name = folder.name

        if folder_name in SKIP_FOLDERS:
            print(f"  Skipping {folder_name}")
            continue

        # System assets
        if folder_name in SYSTEM_FOLDERS:
            asset_type = SYSTEM_FOLDERS[folder_name]
            for img_file in sorted(folder.iterdir()):
                if img_file.suffix.lower() not in VALID_EXTENSIONS:
                    continue
                name = img_file.stem
                try:
                    with open(img_file, "rb") as f:
                        resp = requests.post(
                            f"{SERVER}/api/admin/upload-system-asset",
                            headers={"X-Admin-Key": ADMIN_KEY},
                            files={"file": (img_file.name, f, f"image/{img_file.suffix.lstrip('.').lower()}")},
                            data={
                                "asset_type": asset_type,
                                "name": name,
                                "is_official": "true",
                            },
                        )
                    if resp.status_code == 200:
                        success += 1
                        print(f"  [OK] System/{folder_name}: {name}")
                    else:
                        detail = resp.json().get("detail", resp.text)
                        if "duplicate" in str(detail).lower():
                            skipped += 1
                            print(f"  [SKIP] {folder_name}/{name} (duplicate)")
                        else:
                            failed += 1
                            print(f"  [FAIL] {folder_name}/{name}: {detail}")
                except Exception as e:
                    failed += 1
                    print(f"  [ERR] {folder_name}/{name}: {e}")
            continue

        # Game assets
        if folder_name not in PLATFORM_MAP:
            print(f"  [SKIP] Unknown folder: {folder_name}")
            skipped += 1
            continue

        platform = PLATFORM_MAP[folder_name]
        print(f"\n--- {folder_name} -> {platform} ---")

        for img_file in sorted(folder.iterdir()):
            if img_file.suffix.lower() not in VALID_EXTENSIONS:
                continue

            game_name = img_file.stem

            try:
                with open(img_file, "rb") as f:
                    resp = requests.post(
                        f"{SERVER}/api/admin/upload-official",
                        headers={"X-Admin-Key": ADMIN_KEY},
                        files={"file": (img_file.name, f, f"image/{img_file.suffix.lstrip('.').lower()}")},
                        data={
                            "game_name": game_name,
                            "platform": platform,
                            "asset_type": "icon",
                            "variant_number": 1,
                            "upload_source": "import",
                        },
                    )
                if resp.status_code == 200:
                    success += 1
                    print(f"  [OK] {game_name}")
                else:
                    detail = resp.json().get("detail", resp.text)
                    if "duplicate" in str(detail).lower():
                        skipped += 1
                        print(f"  [SKIP] {game_name} (duplicate)")
                    else:
                        failed += 1
                        print(f"  [FAIL] {game_name}: {detail}")
            except Exception as e:
                failed += 1
                print(f"  [ERR] {game_name}: {e}")

    print(f"\n{'='*50}")
    print(f"Done. Success: {success}, Skipped: {skipped}, Failed: {failed}")

    try:
        r = requests.get(f"{SERVER}/api/stats")
        stats = r.json()
        print(f"Server now: {stats['games']} games, {stats['assets']} assets, {stats['storage_mb']:.1f} MB")
    except:
        pass


if __name__ == "__main__":
    main()
