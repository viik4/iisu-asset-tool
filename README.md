# iiSU Asset Tool

<img src="[https://github.com/viik4/iisu-asset-tool/blob/0b2c001c127d1c4859242a9c744296cf619e6e2c/AssetToolGitHub.png]" width="450" height="250">

Create custom icons, heroes, logos, and covers for your game library. Built for the [iiSU](https://iisu.network/) community.

**Desktop** (Windows, macOS, Linux) · **Android** · **Web Workshop**

## Download

Grab the latest release from the [Releases](https://github.com/viik-4/iisu-asset-tool/releases) page.

| Platform | File |
|----------|------|
| Windows | `iiSU_Asset_Tool.exe` |
| macOS | `iiSU_Asset_Tool.dmg` |
| Linux | `iiSU_Asset_Tool.AppImage` |
| Android | `iiSU_Asset_Tool.apk` |

> **macOS:** If you see "app is damaged", run `xattr -cr /Applications/iiSU\ Asset\ Tool.app` in Terminal, or right-click → Open.

## Features

### Icon Scraper
Fetch game artwork from multiple sources and apply platform-specific borders.
- Batch process hundreds of games at once
- Smart title matching with fuzzy search
- Multiple artwork sources with intelligent fallback
- Interactive mode to choose from all available artwork
- Region detection and preference filtering

### Workshop
Browse, download, and upload community-made assets from the iiSU Asset Server.
- Icons, heroes, logos, and screenshots
- Per-game shareable URLs
- Platform filtering and search
- Download individual assets or bulk ZIP
- Upload your own artwork to share with the community

### Custom Icons
Upload your own images and apply borders with interactive positioning.
- Drag to position, rotate, and zoom
- Real-time preview with platform borders

### Custom Borders
Create gradient borders with custom colors and platform icons.
- Color picker with gradient presets
- Upload custom platform icons (PNG, SVG)
- PSD template-based rendering

### Custom Covers
Generate cover artwork with gradients, overlays, and platform branding.

### ROM Browser
Browse and process ROMs from local or external drives.
- Automatic iiSU directory detection
- USB drive and ADB device support
- Deep search for nested folder structures

### My Assets (Android)
Browse and manage all generated artwork in a visual grid with platform filtering, search, and bulk re-scraping.

## Artwork Sources

| Source | API Key |
|--------|---------|
| [SteamGridDB](https://www.steamgriddb.com/) | Optional |
| [IGDB](https://www.igdb.com/) | Optional |
| [TheGamesDB](https://thegamesdb.net/) | Built-in |
| [Libretro Thumbnails](https://thumbnails.libretro.com/) | Built-in |
| [Steam Store](https://store.steampowered.com/) | None |

API keys: [SteamGridDB](https://www.steamgriddb.com/profile/preferences/api) · [IGDB](https://dev.twitch.tv/console/apps) — configure in Settings > General.

## Supported Platforms

**Nintendo:** NES, SNES, N64, GameCube, Wii, Wii U, Switch, Game Boy, GBC, GBA, DS, 3DS
**Sony:** PS1–PS5, PSP, PS Vita
**Microsoft:** Xbox, Xbox 360
**Sega:** Master System, Genesis, Saturn, Dreamcast, Game Gear
**PC:** Steam, PC (Generic)
**Other:** Arcade, TurboGrafx-16, Neo Geo, Atari, and more
**Custom:** Add your own platforms with custom borders and icons

## Output

Each game folder contains:
- `icon.png` — Game icon with platform border
- `hero_1.png` — Hero/banner image
- `title.png` — Game logo
- `slide_1.png` — Screenshots

Export as PNG or JPEG with configurable quality.

## Asset Server

The iiSU Workshop runs on a FastAPI + SQLite backend at [assets.iisu.community](https://assets.iisu.community).

- Browse and upload game artwork from the web
- Admin dashboard for community moderation
- 60+ platforms supported
- System assets (collection icons, platform covers, borders)

## Credits

- Logo by **Caddypillar**
- Music by **Thaddeus Silva**
- Built for the [iiSU Network](https://iisu.network/) community

## License

MIT License — see [LICENSE](LICENSE) for details.
