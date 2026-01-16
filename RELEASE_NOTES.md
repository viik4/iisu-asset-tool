# iiSU Asset Tool v1.2.1

## What's New in v1.2.1

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

## Features

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
- **Configurable styles** - Supports official, white, and black logo styles from SteamGridDB
- **Fallback to boxart** - Optional setting to fall back to boxart duplicate when no logo is found
- **Legacy mode** - Option to disable logo scraping and use the original boxart duplicate behavior

### Light/Dark Theme Support
- **Light mode** - New light theme matching the iiSU Launcher aesthetic with clean white backgrounds and purple/pink gradient accents
- **Theme toggle** - Quick toggle button in the header to switch between light and dark modes
- **Persistent preference** - Your theme preference is saved and remembered between sessions
- **Updated styling** - Both themes feature rounded corners, subtle shadows, and modern UI elements matching the iiSU Launcher design

## Bug Fixes

### Android Stability
- **Fixed navigation crash** - App no longer crashes when navigating away from game list during bulk scraping operations
- **Lifecycle-aware coroutines** - Scraping operations now properly cancel when leaving the fragment
- **Platform filtering** - Fixed search returning wrong games (e.g., GBA Minish Cap when searching NES Zelda)

### Search & Matching Improvements
- **New fuzzy matching system** - Completely rewritten game database matching with multiple strategies:
  - Exact match after normalization
  - Substring/contains matching
  - Token-based Jaccard similarity
  - Sequence matching for typo tolerance
  - Prefix matching
- **Direct search fallback** - When no database match is found, the tool now searches artwork providers directly with the ROM filename instead of failing

### ROM Browser Fixes
- **Fixed Interactive Mode in ROM Browser** - Interactive artwork selection now works correctly when processing ROMs from the ROM Browser tab
- **Fixed clipboard copy in logs dialog** - The "Copy to Clipboard" button now properly copies log contents with visual feedback
- **Improved progress tracking** - Progress bar now shows overall progress across all games (e.g., `3/10 (30%)`) with current game title displayed in status

### UI Improvements
- **Cleaner ROM Browser layout** - Reorganized UI with grouped controls, compact buttons, and better spacing
- **Fixed Custom Covers tab** - Preview panel now properly centered with correct padding, artwork box no longer pushed to bottom

### File Filtering
- **Filter out non-ROM files** - System files (systeminfo, thumbs.db, desktop.ini, etc.), metadata files, save files, and other non-ROM files are now automatically excluded from scanning

### Icon Overwriting
- **Enhanced logging** - Added detailed logging for icon deletion and saving operations to help debug overwrite issues

## Build & Distribution

### macOS
- **Native DMG installer** - macOS releases are now distributed as proper `.dmg` files with drag-to-Applications installation
- **App icon** - macOS app bundle now includes a proper `.icns` icon

### Linux
- **Native Linux builds** - Standalone executable for Linux distributions

### All Platforms
- **Included missing files** - `logo.png` and `iisu_theme.qss` are now properly included in release packages

---

**Full Changelog**: https://github.com/viik-4/iisu-asset-tool/compare/v1.2.0...v1.2.1
