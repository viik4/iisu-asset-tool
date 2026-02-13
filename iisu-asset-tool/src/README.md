# Fallback Icons

This folder contains fallback platform icons to use when game artwork cannot be found.

## Usage

Place borderless platform icons in this folder with the following naming convention:
- `PLATFORM_KEY.png` (e.g., `SNES.png`, `N64.png`, `GAME_BOY_ADVANCE.png`)

The platform key should match the keys used in `config.yaml`.

## Settings

In Settings > Fallback Icons, you can configure:
- **Use platform icon when artwork not found**: Uses these icons as a fallback when no artwork is scraped
- **Skip scraping - always use platform icon**: Bypasses artwork search entirely and uses platform icons for all games

## Icon Requirements

- Recommended size: 512x512 or larger (will be scaled to fit)
- Format: PNG with transparency
- These icons will be composited with the selected border template
