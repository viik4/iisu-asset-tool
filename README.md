# iiSU Asset Tool
<img src="https://github.com/viik4/iisu-asset-tool/blob/809a64d3c86609240f0dddf959fc4dc1f584dd60/AssetToolGitHub.png" width="450" height="250">

Create custom icons, borders, and covers for your game library. Built for the [iiSU Network](https://iisu.network/) community.

## Download

Download the latest release from the [Releases](https://github.com/viik-4/iisu-asset-tool/releases) page.

| Platform | File |
|----------|------|
| Windows | `iiSU_Asset_Tool.exe` |
| macOS | `iiSU_Asset_Tool.dmg` |
| Linux | `iiSU_Asset_Tool.AppImage` |
| Android | `iiSU_Asset_Tool.apk` |

### macOS Installation

macOS may show "app is damaged" because the app is not notarized. To fix this, open Terminal and run:

```bash
xattr -cr /Applications/iiSU\ Asset\ Tool.app
```

Or right-click the app and select "Open" to bypass Gatekeeper.

## Features

### Icon Scraper
Automatically fetch game artwork from multiple sources and apply platform-specific borders.
- Batch process hundreds of games at once
- Smart title matching with fuzzy search
- Multiple artwork sources with intelligent fallback
- Region detection and preference filtering
- Interactive mode to choose from all available artwork
- Parallel downloads for fast processing

### Custom Icons
Upload your own images and apply borders with interactive positioning.
- Drag to position artwork
- Rotate and zoom controls
- Real-time preview
- Per-platform or global custom borders

### Custom Borders
Create gradient borders with custom colors and platform icons.
- Color picker with gradient presets
- Upload custom platform icons (PNG, SVG)
- Adjustable icon positioning and scale
- PSD template-based rendering

### Custom Covers
Generate cover artwork with gradients, overlays, and platform branding.
- Drag to position artwork
- Mouse wheel zoom
- Gradient color customization
- Consistent preview and export sizing

### ROM Browser
Browse and process ROMs from local or external drives.
- Automatic iiSU directory detection
- USB drive scanning
- ADB device support for Android
- Platform detection from folder structure
- Region filtering

## Settings

All settings are organized into categories and persist between sessions:

### General
- API key management (SteamGridDB, IGDB)
- ROM directory configuration
- Config file location

### Sources
- Artwork source priority (drag to reorder)
- Hero image downloads (1-5 per game)
- Screenshot downloads (1-10 per game)
- Logo/title image scraping
- Fallback platform icons

### Output
- Export format (PNG or JPEG with quality control)
- Auto-copy to Android device via ADB
- Custom borders (global or per-platform)

### Processing
- Worker count for parallel processing
- Per-platform game limits

### Platforms
- Add custom platforms (Steam, retro consoles, etc.)
- Custom border and icon files per platform

## Artwork Sources

| Source | Description | API Key |
|--------|-------------|---------|
| [SteamGridDB](https://www.steamgriddb.com/) | Community-curated game artwork | Optional |
| [IGDB](https://www.igdb.com/) | Internet Game Database | Optional |
| [TheGamesDB](https://thegamesdb.net/) | Game information database | Built-in |
| [Libretro Thumbnails](https://thumbnails.libretro.com/) | RetroArch thumbnails | Built-in |
| [Steam Store](https://store.steampowered.com/) | Steam game library with multiplatform support | None required |

### API Key Setup

| Source | How to Get |
|--------|------------|
| SteamGridDB | [steamgriddb.com/profile/preferences/api](https://www.steamgriddb.com/profile/preferences/api) |
| IGDB | [Twitch Developer Portal](https://dev.twitch.tv/console/apps) (Client ID + Secret) |

Configure API keys in Settings > General. Keys are encrypted and stored securely.

## Supported Platforms

**Nintendo:** NES, SNES, N64, GameCube, Wii, Wii U, Switch, Game Boy, GBC, GBA, DS, 3DS

**Sony:** PlayStation 1-5, PSP, PS Vita

**Microsoft:** Xbox, Xbox 360

**Sega:** Master System, Genesis, Saturn, Dreamcast, Game Gear

**PC:** Steam, PC (Generic)

**Other:** Arcade, TurboGrafx-16, Neo Geo, Atari, and more

**Custom:** Add your own platforms with custom borders and icons

## Output

Generated assets are saved to:
- **Scraped Icons:** `output/` folder (organized by platform)
- **Review Queue:** `review/` folder (for manual review)
- **Custom Exports:** Your chosen location

Each game folder contains:
- `icon.png/jpg` - Main game icon with border
- `title.png` - Game logo or title image
- `hero_1.png`, `hero_2.png`, etc. - Hero/banner images
- `slide_1.png`, `slide_2.png`, etc. - Screenshots

## Configuration

Edit `config.yaml` to customize:
- Output image size (default: 1024px)
- Export format (PNG/JPEG)
- API timeouts and delays
- Platform definitions
- Artwork source priorities
- Processing settings (workers, limits)
- Theme preferences

## Credits

- Logo by **Caddypillar**
- Built for the [iiSU Network](https://iisu.network/) community

## License

MIT License - see [LICENSE](LICENSE) for details.
