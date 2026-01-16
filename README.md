# iiSU Asset Tool
<img src="https://github.com/viik4/iisu-asset-tool/blob/809a64d3c86609240f0dddf959fc4dc1f584dd60/AssetToolGitHub.png" width="200" />

Create custom icons, borders, and covers for your game library. Built for the [iiSU Network](https://iisu.network/) community.

## Download

Download the latest release from the [Releases](https://github.com/viik-4/iisu-asset-tool/releases) page.

| Platform | File |
|----------|------|
| Windows | `iiSU_Asset_Tool.exe` |
| macOS | `iiSU_Asset_Tool.dmg` |
| Linux | `iiSU_Asset_Tool.AppImage` |
| Android | `iiSU_Asset_Tool.apk` |

## Features

### Icon Scraper
Automatically fetch game artwork from multiple sources and apply platform-specific borders.
- Batch process hundreds of games at once
- Smart logo detection and cropping
- Multiple artwork sources with fallback
- Region detection and preference filtering

### Custom Icons
Upload your own images and apply borders with interactive positioning.
- Drag to position artwork
- Rotate and zoom controls
- Real-time preview

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

### ROM Browser
Browse and process ROMs from local or external drives.
- Automatic iiSU directory detection
- USB drive scanning
- ADB device support for Android
- Platform detection from folder structure

### Additional Features
- **Logo Scraping** - Generate title.png files from game logos
- **Hero Images** - Download banner/hero artwork
- **Screenshot Scraping** - Capture 1-10 screenshots per game
- **Light/Dark Themes** - System-aware theme switching
- **Interactive Artwork Selection** - Choose from multiple artwork options
- **Custom Border Upload** - Use your own border designs
- **Fallback Platform Icons** - Automatic fallback for missing artwork
- **Device Copying** - Transfer assets via ADB
- **Export Formats** - PNG or JPEG with quality control

## Artwork Sources

| Source | Description | API Key |
|--------|-------------|---------|
| [SteamGridDB](https://www.steamgriddb.com/) | Community-curated game artwork | Optional |
| [IGDB](https://www.igdb.com/) | Internet Game Database | Optional |
| [TheGamesDB](https://thegamesdb.net/) | Game information database | Built-in |
| [Libretro Thumbnails](https://thumbnails.libretro.com/) | RetroArch thumbnails | Built-in |

### API Key Setup

| Source | How to Get |
|--------|------------|
| SteamGridDB | [steamgriddb.com/profile/preferences/api](https://www.steamgriddb.com/profile/preferences/api) |
| IGDB | [Twitch Developer Portal](https://dev.twitch.tv/console/apps) (Client ID + Secret) |

Configure API keys in Settings (gear icon). Keys are encrypted and stored securely.

## Supported Platforms

**Nintendo:** NES, SNES, N64, GameCube, Wii, Wii U, Switch, Game Boy, GBC, GBA, DS, 3DS

**Sony:** PlayStation 1-5, PSP, PS Vita

**Microsoft:** Xbox, Xbox 360

**Sega:** Master System, Genesis, Saturn, Dreamcast, Game Gear

## Output

Generated assets are saved to:
- **Scraped Icons:** `output/` folder (organized by platform)
- **Review Queue:** `review/` folder (for manual review)
- **Custom Exports:** Your chosen location


## Configuration

Edit `config.yaml` to customize:
- Output image size (default: 1024px)
- Export format (PNG/JPEG)
- API timeouts and delays
- Platform definitions
- Artwork source priorities
- Logo detection settings
- Theme preferences

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built for the [iiSU Network](https://iisu.network/) community.
