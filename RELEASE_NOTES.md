# iiSU Asset Tool v1.2.2

## What's New in v1.2.2

### New Platform Support
- **Arcade platform** - Added Arcade border and platform icon
- **Steam platform** - Added Steam border and platform icon for PC games from Steam
- **PC (Generic) platform** - Added generic PC border and platform icon for Windows/DOS games

### Steam Store Integration
- **New artwork source** - Steam Store added as an artwork provider (no API key required)
- **Multiplatform search** - Steam searches across all games, providing artwork for both PC-exclusive and multiplatform titles
- **Fast parallel fetching** - Downloads multiple Steam artwork options simultaneously
- **Store search fallback** - Uses Steam Store search API when app list is unavailable

### Artwork Picker Improvements
- **Grid layout** - Artwork selection now displays in a 3-column grid instead of horizontal scroll
- **All results shown** - SteamGridDB now returns ALL available artwork instead of limiting to 5
- **Parallel downloads** - Artwork options download 8x faster using concurrent fetching
- **Vertical scrolling** - Better usability on all screen sizes

### Search & Matching Improvements
- **Improved fuzzy matching** - Fixed false matches between similar titles:
  - "Pac-Man" no longer matches "Pac-Mania", "Jr. Pac-Man", or "Pac-Man Plus"
  - Better word boundary detection prevents substring false positives
  - Prefix/suffix detection distinguishes sequels from originals
- **Strict logo/hero matching** - Logos and hero images now use strict title matching to prevent wrong game artwork
- **Removed "official" logo style** - Default logo styles changed to "white" and "black" to avoid unreliable user-submitted logos

### Custom Covers Fix
- **Icon size consistency** - Fixed bug where platform icon appeared larger in preview than in exported image
- **Proper scaling** - Icons now scale correctly at all output resolutions

### Settings Improvements
- **Categorized settings** - Settings dialog redesigned with tabbed categories: General, Sources, Output, Processing, and Platforms
- **Full settings persistence** - All settings now save between sessions, including worker count, limits, and export format

---

## Previous Release: v1.2.1

### Branding
- **New app logo** - Fresh logo designed by Caddypillar
- **In-app logo display** - Logo now appears in the Android navigation rail

### Android Improvements
- **IGDB API key settings** - Added IGDB Client ID and Client Secret input fields in Settings for screenshot scraping
- **Fixed screenshot scraping** - Screenshots now properly use IGDB API instead of non-existent SteamGridDB endpoint
- **Vertical artwork picker** - Interactive mode popup now scrolls vertically instead of horizontally for better usability
- **Improved artwork previews** - Hero and logo thumbnails now preserve aspect ratio instead of being cropped to squares
- **DS Mode toggle** - New setting to show/hide hero and logo sections (for dual-screen devices and foldables)
- **Custom asset directory** - Set a custom directory for iiSU assets on SD card or external storage
- **Interactive mode default** - Interactive mode is now enabled by default with warning when disabled
- **5-column platform grid** - Platform browser now displays 5 columns instead of 4 for better use of screen space

### Desktop Improvements
- **Interactive mode default** - Interactive mode now enabled by default on all platforms
- **Disable warning** - Shows warning dialog when disabling interactive mode explaining artwork will be auto-selected

---

## v1.2.0 Features

### Android App
- **Native Android app** - Full-featured Android port of iiSU Asset Tool
- **iiSU Browser** - Browse your ROM library organized by platform with game counts and missing asset stats
- **Artwork scraping** - Search and download artwork from SteamGridDB, IGDB, TheGamesDB, and Libretro
- **Bulk generation** - Generate icons for entire platforms with parallel downloads
- **Interactive mode** - Pick artwork from multiple options for each game
- **Custom border support** - Upload your own border image to use for all icons
- **Caching system** - Multi-layer caching (memory + disk) for fast platform and game list loading
- **Refresh button** - Manual refresh in iiSU Browser to reload platform data
- **Source priority** - Drag-to-reorder artwork sources with enable/disable toggles
- **Logo scraping** - Download game logos from SteamGridDB for title.png
- **Hero image downloads** - Download hero/banner images from SteamGridDB
- **Screenshot scraping** - Download game screenshots from IGDB or Libretro with configurable count (1-10)
- **Fallback icons** - Use platform icons when artwork not found
- **Export format options** - Choose PNG or JPEG output with quality settings
- **Light/Dark theme** - Match your system theme or choose manually
- **Cancel button** - Cancel bulk scraping operations mid-progress without crashing
- **Platform-aware search** - Improved SteamGridDB search filters results by platform to avoid wrong game matches

### Linux Support
- **Native Linux builds** - Linux releases now available alongside Windows and macOS
- **PyInstaller packaging** - Standalone executable with all dependencies bundled

### Custom Border Support
- **Custom border upload** - Upload your own custom border image to use for all icons instead of platform-specific borders
- **Works across all modes** - Custom borders work in both search-based scraping and ROM browser scraping
- **Available on all platforms** - Feature available on PC (Windows/macOS/Linux) and Android
- **Preview before applying** - See a preview of your custom border in settings before enabling
- **Easy toggle** - Quick switch to enable/disable custom border without losing your selected image
- **Recommended format** - 1024x1024 PNG with transparency for best results

### Region Support
- **Region detection** - Automatically detects game region from ROM filenames (USA, Europe, Japan, etc.) using standard tags like `(USA)`, `[U]`, `[JUE]`
- **Region filter in ROM Browser** - Filter your ROM list by region to show only USA, Europe, Japan, or World releases
- **Region preference in Icon Scraper** - Set a region preference for artwork search
- **Region display in game list** - Games now show their detected region (e.g., "Super Mario World [USA]") in the ROM Browser

### Fallback Platform Icons
- **Use platform icon as fallback** - New setting to use a generic platform icon when no artwork is found for a game
- **Skip scraping mode** - Option to bypass artwork scraping entirely and just use platform icons for all games (useful for quick icon generation)
- **Custom fallback icons folder** - Specify a custom folder containing platform icons to use as fallbacks
- **Automatic fallback source** - Falls back to `platform_icons` folder if no dedicated fallback icon is found

### Screenshot Scraping
- **In-game screenshot downloads** - Download screenshots from IGDB, TheGamesDB, or Libretro snapshots
- **slide_Y naming format** - Screenshots are saved as `slide_1.png`, `slide_2.png`, etc.
- **Configurable count** - Set the number of screenshots to download per game (1-10)
- **Multi-provider fallback** - Tries IGDB first, then TheGamesDB, then Libretro snapshots

### Auto-Copy to Device (ADB)
- **Automatic device transfer** - Copy generated icons directly to connected Android devices via ADB
- **iiSU Launcher integration** - Default path configured for iiSU Launcher assets folder
- **Custom device paths** - Configure any destination path on your Android device
- **Full asset transfer** - Copies icons, titles, hero images, and screenshots

### Hero Image Improvements
- **New hero_Y naming format** - Hero images are now saved as `hero_1.png`, `hero_2.png`, etc. (cleaner format without dimensions)

### Game Logo Scraping for title.png
- **Logo scraping** - Now downloads game logos from SteamGridDB to use as `title.png` instead of duplicating the boxart
- **Transparent PNG logos** - Logos are clean text/title images with transparent backgrounds
- **Configurable styles** - Supports white and black logo styles from SteamGridDB
- **Fallback to boxart** - Optional setting to fall back to boxart duplicate when no logo is found
- **Legacy mode** - Option to disable logo scraping and use the original boxart duplicate behavior

### Light/Dark Theme Support
- **Light mode** - New light theme matching the iiSU Launcher aesthetic with clean white backgrounds and purple/pink gradient accents
- **Theme toggle** - Quick toggle button in the header to switch between light and dark modes
- **Persistent preference** - Your theme preference is saved and remembered between sessions
- **Updated styling** - Both themes feature rounded corners, subtle shadows, and modern UI elements matching the iiSU Launcher design

---

**Full Changelog**: https://github.com/viik-4/iisu-asset-tool/compare/v1.2.1...v1.2.2
