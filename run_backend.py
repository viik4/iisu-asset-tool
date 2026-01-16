import os
import re
import sys
import json
import time
import hashlib
import zipfile
import threading
import unicodedata
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
from urllib.parse import unquote

import requests
import yaml
from PIL import Image, ImageOps, ImageChops, ImageFilter


def _get_subprocess_flags():
    """Get platform-specific subprocess flags to hide console on Windows."""
    if sys.platform == 'win32':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}

# Import search utilities from rom_parser
try:
    from rom_parser import normalize_for_search, get_search_variants, clean_game_title, get_iisu_folder_name
except ImportError:
    # Fallback implementations if rom_parser is not available
    def clean_game_title(name: str) -> str:
        """Basic fallback title cleaning."""
        name = re.sub(r'\s*\[[^\]]*\]', '', name)
        name = re.sub(r'\s*\([^)]*\)', '', name)
        name = re.sub(r'\s+v\d+(\.\d+)*', '', name, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', name).strip()

    def normalize_for_search(name: str) -> str:
        """Basic fallback normalization."""
        name = clean_game_title(name)
        normalized = unicodedata.normalize('NFD', name)
        return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')

    def get_search_variants(name: str) -> List[str]:
        """Basic fallback variants."""
        clean = clean_game_title(name)
        normalized = normalize_for_search(name)
        variants = [clean]
        if normalized != clean:
            variants.append(normalized)
        return variants

    def get_iisu_folder_name(platform_key: str) -> str:
        """Fallback iiSU folder name - just lowercase."""
        return platform_key.lower()


# ==========================
# Cancel Token
# ==========================
class CancelToken:
    def __init__(self):
        self._evt = threading.Event()

    def cancel(self):
        self._evt.set()

    @property
    def is_cancelled(self) -> bool:
        return self._evt.is_set()


# ==========================
# Utilities
# ==========================
def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def safe_slug(s: str, limit: int = 180) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s)
    return s[:limit] if len(s) > limit else s

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def get_export_extension(export_format: str) -> str:
    """
    Get the correct file extension for an export format.

    Args:
        export_format: Format string (e.g., "JPEG", "PNG")

    Returns:
        File extension without dot (e.g., "jpg", "png")
    """
    fmt = export_format.upper()
    if fmt in ("JPG", "JPEG"):
        return "jpg"
    return fmt.lower()


def save_image_for_export(img: Image.Image, path: Path, export_format: str, quality: int = 95, optimize: bool = True):
    """
    Save an image in the specified format, handling RGBA to RGB conversion for JPEG.

    Args:
        img: PIL Image to save
        path: Output path
        export_format: Format string (e.g., "JPEG", "PNG")
        quality: JPEG quality (1-100), ignored for PNG
        optimize: Whether to optimize the output
    """
    # Normalize format
    fmt = export_format.upper()
    if fmt in ("JPG", "JPEG"):
        fmt = "JPEG"
        # JPEG doesn't support transparency - convert RGBA to RGB with white background
        if img.mode in ("RGBA", "LA", "P"):
            # Create white background
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                # Paste with alpha mask
                background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else img.split()[1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(path, fmt, quality=quality, optimize=optimize)
    else:
        # PNG or other formats that support transparency
        img.save(path, fmt, optimize=optimize)


def fuzzy_match_title(search_term: str, database_titles: List[str], threshold: float = 0.6) -> List[Tuple[str, float]]:
    """
    Fuzzy match a search term against database titles.
    Returns list of (title, score) tuples sorted by score descending.
    Uses multiple matching strategies for maximum leniency.
    """
    from difflib import SequenceMatcher

    if not search_term or not database_titles:
        return []

    # Important keywords that must match if present in search term
    # These distinguish different versions/editions of the same game
    CRITICAL_KEYWORDS = {
        'trilogy', 'collection', 'compilation', 'anthology', 'bundle',
        'remaster', 'remastered', 'remake', 'hd', 'definitive', 'complete',
        'goty', 'ultimate', 'deluxe', 'premium', 'gold', 'platinum',
        '2', '3', '4', '5', '6', '7', '8', '9', '10',  # Numbered sequels
        'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',  # Roman numerals
        'zero', 'origins', 'revelations', 'corruption', 'echoes', 'hunters',
        'prime', 'fusion', 'super', 'advance', 'portable', 'pocket',
    }

    # Normalize search term
    search_norm = normalize_for_search(search_term).lower()
    search_tokens = set(re.findall(r'[a-z0-9]+', search_norm))

    # Find critical keywords in search term
    search_critical = search_tokens & CRITICAL_KEYWORDS

    results = []

    for title in database_titles:
        # Normalize database title
        title_norm = normalize_for_search(title).lower()
        title_tokens = set(re.findall(r'[a-z0-9]+', title_norm))

        # Check for critical keyword mismatch
        # If search has critical keywords, title should have them too
        title_critical = title_tokens & CRITICAL_KEYWORDS
        if search_critical:
            # If search has "trilogy" but title doesn't, heavily penalize
            missing_critical = search_critical - title_critical
            if missing_critical:
                # Skip this match entirely - critical keywords are missing
                continue

        # Also penalize if title has critical keywords that search doesn't
        # e.g., searching "Metroid Prime" should not match "Metroid Prime 3"
        if title_critical - search_critical:
            extra_critical = title_critical - search_critical
            # Only skip if the extra keywords are sequel indicators
            sequel_indicators = {'2', '3', '4', '5', '6', '7', '8', '9', '10',
                                'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',
                                'trilogy', 'collection', 'compilation'}
            if extra_critical & sequel_indicators:
                continue

        # Strategy 1: Exact match (after normalization)
        if search_norm == title_norm:
            results.append((title, 1.0))
            continue

        # Strategy 2: One contains the other
        if search_norm in title_norm or title_norm in search_norm:
            # Score based on length ratio
            len_ratio = min(len(search_norm), len(title_norm)) / max(len(search_norm), len(title_norm))
            results.append((title, 0.85 + (len_ratio * 0.1)))
            continue

        # Strategy 3: Token overlap (Jaccard similarity)
        if search_tokens and title_tokens:
            intersection = len(search_tokens & title_tokens)
            union = len(search_tokens | title_tokens)
            jaccard = intersection / union if union > 0 else 0

            # Boost if all search tokens are found
            if search_tokens <= title_tokens:
                jaccard = min(1.0, jaccard + 0.2)

            if jaccard >= threshold:
                results.append((title, jaccard))
                continue

        # Strategy 4: Sequence matching (handles typos, minor differences)
        seq_ratio = SequenceMatcher(None, search_norm, title_norm).ratio()
        if seq_ratio >= threshold:
            results.append((title, seq_ratio))
            continue

        # Strategy 5: Check if search starts with or title starts with
        if search_norm.startswith(title_norm[:min(10, len(title_norm))]) or \
           title_norm.startswith(search_norm[:min(10, len(search_norm))]):
            results.append((title, 0.65))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def find_best_database_match(search_term: str, database_titles: List[str], max_results: int = 5) -> List[str]:
    """
    Find the best matching titles from the database for a search term.
    Returns up to max_results titles, or the search_term itself if no good matches.
    """
    matches = fuzzy_match_title(search_term, database_titles, threshold=0.5)

    if matches:
        # Return top matches
        return [title for title, score in matches[:max_results]]
    else:
        # No good matches - return the search term itself
        return [search_term]


def _emit_log(callbacks, msg: str):
    if callbacks is None:
        return
    # Handle dict-style callbacks (from GUI)
    if isinstance(callbacks, dict):
        if "log" in callbacks and callable(callbacks["log"]):
            try:
                callbacks["log"](msg)
            except Exception:
                pass
    # Handle object-style callbacks
    elif hasattr(callbacks, "log"):
        try:
            callbacks.log.emit(msg)
        except Exception:
            pass

def _emit_progress(callbacks, done: int, total: int):
    if callbacks is None:
        return
    # Handle dict-style callbacks (from GUI)
    if isinstance(callbacks, dict):
        if "progress" in callbacks and callable(callbacks["progress"]):
            try:
                callbacks["progress"](done, total)
            except Exception:
                pass
    # Handle object-style callbacks
    elif hasattr(callbacks, "progress"):
        try:
            callbacks.progress.emit(done, total)
        except Exception:
            pass

def _emit_preview(callbacks, img_path: Path):
    if callbacks is None:
        return
    # Handle dict-style callbacks (from GUI)
    if isinstance(callbacks, dict):
        if "preview" in callbacks and callable(callbacks["preview"]):
            try:
                callbacks["preview"](str(img_path))
            except Exception:
                pass
    # Handle object-style callbacks
    elif hasattr(callbacks, "preview"):
        try:
            callbacks.preview.emit(str(img_path))
        except Exception:
            pass

def _request_user_selection(callbacks, title: str, platform: str, artwork_options: List[Dict[str, Any]]) -> Optional[int]:
    """
    Request user to select artwork from options.
    Returns selected index, None if skipped, -1 if cancelled all.
    """
    _emit_log(callbacks, f"[DEBUG] _request_user_selection called for {title} with {len(artwork_options)} options")

    if callbacks is None:
        _emit_log(callbacks, f"[DEBUG] No callbacks provided")
        return None

    # Handle dict-style callbacks (from GUI)
    if isinstance(callbacks, dict):
        _emit_log(callbacks, f"[DEBUG] Callbacks is dict, has request_selection: {'request_selection' in callbacks}")
        if "request_selection" in callbacks and callable(callbacks["request_selection"]):
            try:
                _emit_log(callbacks, f"[DEBUG] Calling request_selection callback...")
                result = callbacks["request_selection"](title, platform, artwork_options)
                _emit_log(callbacks, f"[DEBUG] Callback returned: {result}")
                return result
            except Exception as e:
                _emit_log(callbacks, f"[ERROR] Callback exception: {e}")
                import traceback
                _emit_log(callbacks, f"[ERROR] {traceback.format_exc()}")
                return None
    # Handle object-style callbacks
    elif hasattr(callbacks, "request_selection"):
        try:
            return callbacks.request_selection(title, platform, artwork_options)
        except Exception as e:
            _emit_log(callbacks, f"[ERROR] Object callback exception: {e}")
            return None

    _emit_log(callbacks, f"[DEBUG] No valid callback found")
    return None


# ==========================
# SteamGridDB (thread-local session)
# ==========================
_thread_local = threading.local()

def get_session(api_key: str) -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "iiSU-Icons/1.0",
        })
        _thread_local.session = s
    return s

def sgdb_get(api_key: str, base_url: str, path: str, params: Optional[dict], timeout_s: int) -> dict:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    s = get_session(api_key)
    r = s.get(url, params=params, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    if not data.get("success", False):
        raise RuntimeError(data)
    return data

def search_autocomplete(api_key: str, base_url: str, term: str, timeout_s: int) -> List[dict]:
    """Search SteamGridDB autocomplete with a single term."""
    term_q = requests.utils.quote(term)
    data = sgdb_get(api_key, base_url, f"search/autocomplete/{term_q}", None, timeout_s)
    return data.get("data", []) or []


def search_with_variants(api_key: str, base_url: str, title: str, timeout_s: int, delay_s: float = 0.25, callbacks=None) -> List[dict]:
    """
    Search SteamGridDB using multiple search term variants.
    Tries cleaned name, normalized name (no accents), and other variations.
    Returns combined unique results.
    """
    variants = get_search_variants(title)
    all_results = []
    seen_ids = set()

    _emit_log(callbacks, f"[DEBUG] Search variants for '{title}': {variants}")

    for variant in variants:
        if not variant:
            continue

        try:
            results = search_autocomplete(api_key, base_url, variant, timeout_s)

            # Add unique results
            for result in results:
                rid = result.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_results.append(result)

            if delay_s > 0 and variants.index(variant) < len(variants) - 1:
                time.sleep(delay_s)

            # If we found good results, we can stop
            if len(all_results) >= 5:
                break

        except Exception as e:
            import traceback
            _emit_log(callbacks, f"[DEBUG] Search variant '{variant}' failed: {e}")
            _emit_log(callbacks, f"[DEBUG] Traceback: {traceback.format_exc()}")
            continue

    _emit_log(callbacks, f"[DEBUG] Found {len(all_results)} unique results across {len(variants)} variants")
    return all_results


def get_game_by_id(api_key: str, base_url: str, game_id: str, timeout_s: int) -> dict:
    data = sgdb_get(api_key, base_url, f"games/id/{game_id}", None, timeout_s)
    return data.get("data", {}) or []

def grids_by_game(
    api_key: str,
    base_url: str,
    game_id: str,
    dimensions: Optional[List[str]],
    styles: Optional[List[str]],
    timeout_s: int
) -> List[dict]:
    params = {}
    # SteamGridDB API expects comma-separated values, not multiple params
    if dimensions:
        params["dimensions"] = ",".join(dimensions) if isinstance(dimensions, list) else dimensions
    if styles:
        params["styles"] = ",".join(styles) if isinstance(styles, list) else styles
    data = sgdb_get(api_key, base_url, f"grids/game/{game_id}", params or None, timeout_s)
    return data.get("data", []) or []

def is_animated(url: str) -> bool:
    return url.lower().endswith(".webp")

def pick_best_grid(grids: List[dict], prefer_dim: str, allow_animated: bool, square_only: bool) -> Optional[dict]:
    """Pick the best grid based on score, upvotes, and preferences."""
    if not grids:
        return None

    filtered = []
    for g in grids:
        url = (g.get("url") or "").strip()
        if not url:
            continue
        if not allow_animated and is_animated(url):
            continue
        filtered.append(g)
    if not filtered:
        return None

    if square_only:
        exact = [g for g in filtered if f"{g.get('width')}x{g.get('height')}" == prefer_dim]
        if not exact:
            return None
        # Sort by score (primary), upvotes (secondary), then id (tiebreaker)
        exact.sort(key=lambda x: (x.get("score", 0), x.get("upvotes", 0), x.get("id", 0)), reverse=True)
        return exact[0]

    # Sort by score (primary), upvotes (secondary), then id (tiebreaker)
    filtered.sort(key=lambda x: (x.get("score", 0), x.get("upvotes", 0), x.get("id", 0)), reverse=True)
    return filtered[0]

def download_bytes(url: str, timeout_s: int) -> bytes:
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    return r.content


# ==========================
# Platform-aware candidate selection
# ==========================
def _flatten_strings(obj: Any) -> str:
    parts: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            parts.append(str(k))
            parts.append(_flatten_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            parts.append(_flatten_strings(v))
    else:
        parts.append(str(obj))
    return " ".join(parts)

def extract_year_from_title(title: str) -> Optional[int]:
    """Extract a 4-digit year from a title string (e.g., from '(1992)' or '1992')."""
    if not title:
        return None
    # Look for years in parentheses first (most reliable)
    paren_match = re.search(r'\((\d{4})\)', title)
    if paren_match:
        year = int(paren_match.group(1))
        if 1970 <= year <= 2030:
            return year
    # Then look for standalone 4-digit years
    year_match = re.search(r'\b(19[7-9]\d|20[0-2]\d)\b', title)
    if year_match:
        return int(year_match.group(1))
    return None


def get_release_year_from_meta(game_meta: dict) -> Optional[int]:
    """Extract release year from SteamGridDB game metadata."""
    if not game_meta:
        return None
    # Try release_date field (Unix timestamp or string)
    release_date = game_meta.get("release_date")
    if release_date:
        try:
            if isinstance(release_date, (int, float)):
                # Unix timestamp
                from datetime import datetime
                return datetime.fromtimestamp(release_date).year
            elif isinstance(release_date, str):
                # Try to parse as date string
                year_match = re.search(r'(\d{4})', release_date)
                if year_match:
                    return int(year_match.group(1))
        except Exception:
            pass
    return None


def extract_sequel_number(title: str) -> Optional[str]:
    """Extract sequel/series number from title (Arabic or Roman numerals)."""
    if not title:
        return None
    t = title.lower().strip()

    # Roman numeral map
    roman_map = {
        'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'v': '5',
        'vi': '6', 'vii': '7', 'viii': '8', 'ix': '9', 'x': '10',
        'xi': '11', 'xii': '12', 'xiii': '13', 'xiv': '14', 'xv': '15'
    }

    # Look for Arabic numbers at end or after main title
    # Matches: "Game 2", "Game2", "Game - 2", "Game: Part 2"
    arabic_match = re.search(r'[\s:\-]+(\d+)\s*$', t)
    if arabic_match:
        return arabic_match.group(1)

    # Look for standalone number at end
    arabic_end = re.search(r'(\d+)\s*$', t)
    if arabic_end:
        return arabic_end.group(1)

    # Look for Roman numerals at end (as word boundary)
    roman_match = re.search(r'\b(x{0,3}(?:ix|iv|v?i{0,3}))\s*$', t)
    if roman_match:
        roman = roman_match.group(1)
        if roman in roman_map:
            return roman_map[roman]

    return None


def extract_subtitle(title: str) -> Optional[str]:
    """Extract subtitle after colon or dash."""
    if not title:
        return None
    # Look for subtitle after : or -
    match = re.search(r'[:\-]\s*(.+)$', title)
    if match:
        subtitle = match.group(1).strip().lower()
        # Ignore if it's just a number or very short
        if len(subtitle) > 2 and not subtitle.isdigit():
            return subtitle
    return None


def score_candidate(title: str, candidate_name: str, game_meta: dict, platform_hints: List[str]) -> int:
    t = (title or "").lower().strip()
    n = (candidate_name or "").lower().strip()
    score = 0

    if n == t:
        score += 200
    elif n.startswith(t) or t.startswith(n):
        score += 140
    elif t in n or n in t:
        score += 90

    t_tokens = set(re.findall(r"[a-z0-9]+", t))
    n_tokens = set(re.findall(r"[a-z0-9]+", n))
    score += min(len(t_tokens & n_tokens) * 8, 80)

    meta_text = _flatten_strings(game_meta).lower()
    for h in platform_hints:
        hh = h.lower()
        if hh and hh in meta_text:
            score += 60

    # Sequel number matching - CRITICAL for series games
    title_num = extract_sequel_number(title)
    candidate_num = extract_sequel_number(candidate_name)

    if title_num:
        if candidate_num == title_num:
            score += 150  # Exact sequel match - very important
        elif candidate_num and candidate_num != title_num:
            score -= 200  # Wrong sequel number - heavily penalize
        elif not candidate_num:
            score -= 150  # Title has number but candidate doesn't - likely wrong game

    # Subtitle matching - important for games like "Castlevania: Symphony of the Night"
    title_subtitle = extract_subtitle(title)
    candidate_subtitle = extract_subtitle(candidate_name)

    if title_subtitle:
        if candidate_subtitle:
            # Compare subtitles
            sub_t_tokens = set(re.findall(r"[a-z0-9]+", title_subtitle))
            sub_n_tokens = set(re.findall(r"[a-z0-9]+", candidate_subtitle))
            overlap = len(sub_t_tokens & sub_n_tokens)
            if overlap >= 2:
                score += 100  # Good subtitle match
            elif overlap == 1:
                score += 30   # Partial match
            else:
                score -= 50   # Different subtitles
        else:
            # Title has subtitle but candidate doesn't
            score -= 80

    # Release year matching - big bonus for matching year
    title_year = extract_year_from_title(title)
    meta_year = get_release_year_from_meta(game_meta)
    if title_year and meta_year:
        year_diff = abs(title_year - meta_year)
        if year_diff == 0:
            score += 100  # Exact year match - strong signal
        elif year_diff == 1:
            score += 50   # Off by one year (release date variations)
        elif year_diff <= 2:
            score += 20   # Close enough
        elif year_diff >= 5:
            score -= 50   # Likely wrong game (e.g., remake vs original)

    return score

def choose_best_game_id(
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    title: str,
    platform_hints: List[str],
    autocomplete_results: List[dict],
    max_candidates: int = 8,
    callbacks=None
) -> Optional[str]:
    if not autocomplete_results:
        return None

    candidates = autocomplete_results[:max_candidates]
    best_id = None
    best_score = -10**9

    title_year = extract_year_from_title(title)
    title_num = extract_sequel_number(title)
    title_subtitle = extract_subtitle(title)

    if title_year:
        _emit_log(callbacks, f"[DEBUG] Year extracted from title '{title}': {title_year}")
    if title_num:
        _emit_log(callbacks, f"[DEBUG] Sequel number from title '{title}': {title_num}")
    if title_subtitle:
        _emit_log(callbacks, f"[DEBUG] Subtitle from title '{title}': {title_subtitle}")

    for c in candidates:
        cid = c.get("id")
        if cid is None:
            continue
        cid = str(cid)

        meta = {}
        try:
            meta = get_game_by_id(api_key, base_url, cid, timeout_s)
            if delay_s > 0:
                time.sleep(delay_s)
        except Exception:
            meta = {}

        name = c.get("name") or meta.get("name") or ""
        meta_year = get_release_year_from_meta(meta)
        candidate_num = extract_sequel_number(name)
        candidate_subtitle = extract_subtitle(name)
        s = score_candidate(title, name, meta, platform_hints)

        debug_info = f"'{name}' (id={cid}, year={meta_year}"
        if candidate_num:
            debug_info += f", seq={candidate_num}"
        if candidate_subtitle:
            debug_info += f", sub='{candidate_subtitle[:20]}...'" if len(candidate_subtitle or "") > 20 else f", sub='{candidate_subtitle}'"
        debug_info += f") score={s}"
        _emit_log(callbacks, f"[DEBUG] Candidate: {debug_info}")

        if s > best_score:
            best_score = s
            best_id = cid

    _emit_log(callbacks, f"[DEBUG] Best match: id={best_id} with score={best_score}")
    return best_id


# ==========================
# Libretro thumbnails provider
# ==========================
_LIBRETRO_BAD_CHARS = r'&\*/:<>?\|"'  # libretro recommends replacing certain characters with '_' in thumbnail filenames

def libretro_sanitize_filename(name: str) -> str:
    out = []
    for ch in (name or "").strip():
        if ch in _LIBRETRO_BAD_CHARS:
            out.append("_")
        else:
            out.append(ch)
    s = "".join(out).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def libretro_candidate_names(title: str) -> List[str]:
    """Generate candidate names for Libretro thumbnail search."""
    # Clean the title first
    clean_title = clean_game_title(title)
    base = libretro_sanitize_filename(clean_title)

    # Also try normalized version (no accents)
    normalized = normalize_for_search(title)
    normalized_base = libretro_sanitize_filename(normalized)

    candidates = [base]
    if normalized_base != base:
        candidates.append(normalized_base)

    regions = [
        "World", "USA", "Europe", "Japan",
        "USA, Europe", "USA, Australia", "Europe, Australia",
        "Japan, USA", "Japan, Europe",
    ]
    for r in regions:
        candidates.append(f"{base} ({r})")

    # tiny punctuation tweaks
    candidates.append(re.sub(r"\s*-\s*", " - ", base))
    candidates.append(re.sub(r"\s*:\s*", ": ", base))

    seen = set()
    out = []
    for c in candidates:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out

def _libretro_index_url(base_url: str, playlist_name: str, type_dir: str) -> str:
    # The index is browsable HTML
    return f"{base_url.rstrip('/')}/{requests.utils.quote(playlist_name)}/{requests.utils.quote(type_dir)}/"

def _parse_libretro_index_filenames(index_html: str) -> List[str]:
    """
    Parses the apache-style directory listing from thumbnails.libretro.com and returns .png filenames.
    """
    # Directory listings have links like: <a href="Super%20Mario%20Bros.%20(World).png">...
    # We'll extract href="...png"
    hrefs = re.findall(r'href="([^"]+\.png)"', index_html, flags=re.IGNORECASE)
    out = []
    for h in hrefs:
        # Convert %20 to spaces etc
        fname = unquote(html.unescape(h))
        # Some listings include absolute paths or weird prefixes; keep basename only
        fname = fname.split("/")[-1]
        if fname.lower().endswith(".png"):
            out.append(fname)
    return out

def _norm_for_match(s: str) -> str:
    # Aggressive normalization for matching titles to filenames
    s = (s or "").lower()
    s = re.sub(r"\.png$", "", s)
    # strip bracket tags like [h], [b], [iNES title], etc.
    s = re.sub(r"\[[^\]]+\]", "", s)
    # strip parenthetical chunks that are mostly region/lang/publisher/date noise,
    # but keep it gentle (we’ll still score tokens)
    s = re.sub(r"\(([^)]*)\)", r" \1 ", s)
    # punctuation -> spaces
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _score_match(title_norm: str, fname_norm: str) -> int:
    """
    Token overlap score with boosts for prefix/contains.
    """
    if not title_norm or not fname_norm:
        return -10**9

    if fname_norm == title_norm:
        return 500

    score = 0
    if fname_norm.startswith(title_norm) or title_norm.startswith(fname_norm):
        score += 200
    if title_norm in fname_norm or fname_norm in title_norm:
        score += 120

    t = set(title_norm.split())
    f = set(fname_norm.split())
    inter = len(t & f)
    union = max(1, len(t | f))
    score += int(300 * (inter / union))

    # small bonus for longer matches (discourages tiny collisions)
    score += min(len(fname_norm), 180) // 6
    return score

def _load_or_build_libretro_index(
    *,
    cache_dir: Path,
    base_url: str,
    playlist_name: str,
    type_dir: str,
    timeout_s: int,
    cache_hours: int = 168
) -> List[str]:
    ensure_dir(cache_dir)
    key = sha256_text(f"{base_url}|{playlist_name}|{type_dir}|index")
    cache_path = cache_dir / f"{key}.json"

    # Use cache if fresh
    if cache_path.exists():
        try:
            obj = json.loads(cache_path.read_text(encoding="utf-8"))
            ts = float(obj.get("ts", 0))
            if (time.time() - ts) < cache_hours * 3600 and isinstance(obj.get("files"), list):
                return obj["files"]
        except Exception:
            pass

    # Fetch index HTML
    url = _libretro_index_url(base_url, playlist_name, type_dir)
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    files = _parse_libretro_index_filenames(r.text)

    cache_path.write_text(json.dumps({"ts": time.time(), "files": files}, indent=2), encoding="utf-8")
    return files

def libretro_try_download_boxart(
    base_url: str,
    playlist_name: str,
    type_dir: str,
    title: str,
    timeout_s: int,
    cache_dir: Optional[Path] = None,
    use_index_matching: bool = True,
    index_cache_hours: int = 168,
    debug_log=None
) -> Optional[bytes]:
    """
    1) Try direct candidate names (fast)
    2) If that fails and use_index_matching=True, build/load index for platform and fuzzy match
    """
    # ---- 1) Direct tries (fast path)
    for cand in libretro_candidate_names(title):
        path = "/".join([
            requests.utils.quote(playlist_name, safe=""),
            requests.utils.quote(type_dir, safe=""),
            requests.utils.quote(cand + ".png", safe=""),
        ])
        url = f"{base_url.rstrip('/')}/{path}"
        try:
            r = requests.get(url, timeout=timeout_s)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            continue

    # ---- 2) Index + fuzzy match
    if not use_index_matching or cache_dir is None:
        return None

    try:
        files = _load_or_build_libretro_index(
            cache_dir=cache_dir,
            base_url=base_url,
            playlist_name=playlist_name,
            type_dir=type_dir,
            timeout_s=timeout_s,
            cache_hours=index_cache_hours,
        )
    except Exception as e:
        if debug_log:
            debug_log(f"[LIBRETRO] Index fetch failed: {e}")
        return None

    title_norm = _norm_for_match(title)
    best = None
    best_score = -10**9

    for fname in files:
        s = _score_match(title_norm, _norm_for_match(fname))
        if s > best_score:
            best_score = s
            best = fname

    # Threshold to avoid nonsense matches
    if not best or best_score < 220:
        if debug_log:
            debug_log(f"[LIBRETRO] No good match for '{title}' (best={best} score={best_score})")
        return None

    url = f"{_libretro_index_url(base_url, playlist_name, type_dir)}{requests.utils.quote(best)}"
    try:
        r = requests.get(url, timeout=timeout_s)
        if r.status_code == 200 and r.content:
            if debug_log:
                debug_log(f"[LIBRETRO] Matched '{title}' -> '{best}' (score={best_score})")
            return r.content
    except Exception as e:
        if debug_log:
            debug_log(f"[LIBRETRO] Download failed for {best}: {e}")
        return None



# ==========================
# Image ops + border mask
# ==========================
try:
    import numpy as np
except ImportError:
    np = None

def center_crop_to_square(img: Image.Image, out_size: int, centering: Tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGBA")
    cx, cy = centering
    cx = max(0.0, min(1.0, float(cx)))
    cy = max(0.0, min(1.0, float(cy)))
    return ImageOps.fit(img, (out_size, out_size), method=Image.LANCZOS, centering=(cx, cy))

def _content_centroid(img_rgba: Image.Image, alpha_threshold: int = 16, margin_pct: float = 0.06) -> Tuple[float, float, int]:
    """Returns (mx,my,count) centroid of non-transparent pixels, normalized to [0,1] in x/y."""
    img = ImageOps.exif_transpose(img_rgba).convert("RGBA")
    w, h = img.size
    if w <= 1 or h <= 1:
        return (0.5, 0.5, 0)

    mx = int(round(w * margin_pct))
    my = int(round(h * margin_pct))
    x1, y1 = mx, my
    x2, y2 = max(x1 + 1, w - mx), max(y1 + 1, h - my)
    region = img.crop((x1, y1, x2, y2))
    rw, rh = region.size

    if np is not None:
        a = np.array(region.split()[-1], dtype=np.uint8)
        mask = a > alpha_threshold
        cnt = int(mask.sum())
        if cnt <= 0:
            return (0.5, 0.5, 0)
        ys, xs = np.nonzero(mask)
        cx = float(xs.mean()) / max(1.0, (rw - 1))
        cy = float(ys.mean()) / max(1.0, (rh - 1))
        gx = (x1 + cx * (rw - 1)) / (w - 1)
        gy = (y1 + cy * (rh - 1)) / (h - 1)
        return (float(gx), float(gy), cnt)

    alpha = region.split()[-1]
    pix = alpha.load()
    total = 0
    sx = 0.0
    sy = 0.0
    for yy in range(rh):
        for xx in range(rw):
            if pix[xx, yy] > alpha_threshold:
                total += 1
                sx += xx
                sy += yy
    if total <= 0:
        return (0.5, 0.5, 0)
    cx = (sx / total) / max(1.0, (rw - 1))
    cy = (sy / total) / max(1.0, (rh - 1))
    gx = (x1 + cx * (rw - 1)) / (w - 1)
    gy = (y1 + cy * (rh - 1)) / (h - 1)
    return (float(gx), float(gy), int(total))

def _best_centering_for_img(img_rgba: Image.Image, out_size: int, steps: int = 5, span: float = 0.22,
                            alpha_threshold: int = 16, margin_pct: float = 0.06) -> Tuple[Tuple[float, float], Tuple[float, float, int]]:
    """Search a small grid of ImageOps.fit centering points and pick the one that best centers content."""
    steps = max(1, int(steps))
    span = max(0.0, min(0.49, float(span)))
    if steps == 1:
        best = (0.5, 0.5)
        fitted = center_crop_to_square(img_rgba, out_size, centering=best)
        mx, my, cnt = _content_centroid(fitted, alpha_threshold=alpha_threshold, margin_pct=margin_pct)
        return best, (mx, my, cnt)

    offsets = [(-span + (2 * span) * i / (steps - 1)) for i in range(steps)]
    best_c = (0.5, 0.5)
    best_metrics = (0.5, 0.5, 0)
    best_score = 1e9

    for oy in offsets:
        for ox in offsets:
            c = (0.5 + ox, 0.5 + oy)
            fitted = center_crop_to_square(img_rgba, out_size, centering=c)
            mx, my, cnt = _content_centroid(fitted, alpha_threshold=alpha_threshold, margin_pct=margin_pct)
            score = (mx - 0.5) ** 2 + (my - 0.5) ** 2
            if cnt <= 0:
                score += 10.0
            if score < best_score:
                best_score = score
                best_c = (max(0.0, min(1.0, c[0])), max(0.0, min(1.0, c[1])))
                best_metrics = (mx, my, cnt)

    return best_c, best_metrics


# ==========================
# Smart Logo/Art Detection
# ==========================

def _detect_content_bbox(img_rgba: Image.Image, alpha_threshold: int = 16, edge_padding: int = 5) -> Tuple[int, int, int, int]:
    """
    Detect tight bounding box around non-transparent content.
    Returns (x1, y1, x2, y2) in pixel coordinates.
    """
    img = ImageOps.exif_transpose(img_rgba).convert("RGBA")
    w, h = img.size

    if np is not None:
        alpha = np.array(img.split()[-1], dtype=np.uint8)
        mask = alpha > alpha_threshold

        if not mask.any():
            return (0, 0, w, h)

        rows = np.any(mask, axis=1)
        cols = np.any(mask, axis=0)

        y_indices = np.where(rows)[0]
        x_indices = np.where(cols)[0]

        if len(y_indices) == 0 or len(x_indices) == 0:
            return (0, 0, w, h)

        x1 = max(0, int(x_indices[0]) - edge_padding)
        x2 = min(w, int(x_indices[-1]) + edge_padding + 1)
        y1 = max(0, int(y_indices[0]) - edge_padding)
        y2 = min(h, int(y_indices[-1]) + edge_padding + 1)

        return (x1, y1, x2, y2)

    # Fallback without NumPy
    alpha = img.split()[-1]
    pix = alpha.load()

    min_x, min_y = w, h
    max_x, max_y = 0, 0

    found_any = False
    for y in range(h):
        for x in range(w):
            if pix[x, y] > alpha_threshold:
                found_any = True
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

    if not found_any:
        return (0, 0, w, h)

    x1 = max(0, min_x - edge_padding)
    x2 = min(w, max_x + edge_padding + 1)
    y1 = max(0, min_y - edge_padding)
    y2 = min(h, max_y + edge_padding + 1)

    return (x1, y1, x2, y2)


def _detect_logo_region_cv2(img_rgba: Image.Image, debug: bool = False) -> Optional[Tuple[int, int, int, int]]:
    """
    Advanced logo detection using OpenCV (if available).
    Uses edge detection + morphology to find the main logo region.
    Returns (x1, y1, x2, y2) or None if OpenCV unavailable.
    """
    try:
        import cv2
    except ImportError:
        return None

    img = ImageOps.exif_transpose(img_rgba).convert("RGBA")
    w, h = img.size

    # Convert to NumPy
    img_array = np.array(img, dtype=np.uint8)

    # Extract alpha channel
    alpha = img_array[:, :, 3]

    # Create mask of non-transparent regions
    mask = (alpha > 16).astype(np.uint8) * 255

    if mask.sum() == 0:
        return None

    # Convert RGB to grayscale for edge detection
    gray = cv2.cvtColor(img_array[:, :, :3], cv2.COLOR_RGB2GRAY)

    # Apply bilateral filter to reduce noise while keeping edges
    filtered = cv2.bilateralFilter(gray, 9, 75, 75)

    # Canny edge detection
    edges = cv2.Canny(filtered, 50, 150)

    # Apply mask to edges (only consider edges in non-transparent areas)
    edges = cv2.bitwise_and(edges, edges, mask=mask)

    # Morphological operations to connect nearby edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(edges, kernel, iterations=2)
    closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel, iterations=1)

    # Find contours
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    # Find the largest contour by area
    largest_contour = max(contours, key=cv2.contourArea)

    # Get bounding rectangle
    x, y, bw, bh = cv2.boundingRect(largest_contour)

    # Add padding
    padding = 10
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(w, x + bw + padding)
    y2 = min(h, y + bh + padding)

    return (x1, y1, x2, y2)


def detect_and_crop_logo(img_rgba: Image.Image,
                         method: str = "auto",
                         min_content_ratio: float = 0.15,
                         max_crop_ratio: float = 0.85,
                         debug_log=None) -> Image.Image:
    """
    Detect the main logo/artwork region and crop to it intelligently.

    Args:
        img_rgba: Input RGBA image
        method: "auto", "bbox", "cv2", or "none"
        min_content_ratio: Minimum ratio of content to keep (prevents over-cropping)
        max_crop_ratio: Maximum crop ratio (prevents tiny crops)
        debug_log: Optional logging function

    Returns:
        Cropped image (or original if detection fails)
    """
    img = ImageOps.exif_transpose(img_rgba).convert("RGBA")
    orig_w, orig_h = img.size

    if method == "none":
        return img

    bbox = None

    # Try CV2 method first if available and requested
    if method in ("auto", "cv2"):
        bbox = _detect_logo_region_cv2(img, debug=False)
        if bbox and debug_log:
            debug_log(f"[LOGO] CV2 detection: {bbox}")

    # Fallback to simple bbox if CV2 failed or not requested
    if bbox is None and method in ("auto", "bbox"):
        bbox = _detect_content_bbox(img, alpha_threshold=16, edge_padding=10)
        if debug_log:
            debug_log(f"[LOGO] BBox detection: {bbox}")

    if bbox is None:
        return img

    x1, y1, x2, y2 = bbox
    crop_w = x2 - x1
    crop_h = y2 - y1

    # Safety checks
    if crop_w <= 0 or crop_h <= 0:
        return img

    # Check if crop is too small
    content_ratio = (crop_w * crop_h) / (orig_w * orig_h)
    if content_ratio < min_content_ratio:
        if debug_log:
            debug_log(f"[LOGO] Crop too small ({content_ratio:.2%}), using original")
        return img

    # Check if crop is too similar to original (no point cropping)
    if crop_w > orig_w * max_crop_ratio and crop_h > orig_h * max_crop_ratio:
        if debug_log:
            debug_log(f"[LOGO] Crop too similar to original, using original")
        return img

    # Perform crop
    cropped = img.crop((x1, y1, x2, y2))

    if debug_log:
        debug_log(f"[LOGO] Cropped from {orig_w}x{orig_h} to {crop_w}x{crop_h} ({content_ratio:.2%})")

    return cropped


def fill_center_hole(alpha: Image.Image) -> Image.Image:
    a = alpha.convert("L")
    w, h = a.size
    px = a.load()
    cx, cy = w // 2, h // 2
    if px[cx, cy] != 0:
        return a
    q = deque([(cx, cy)])
    visited = {(cx, cy)}
    while q:
        x, y = q.popleft()
        px[x, y] = 255
        for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                if px[nx, ny] == 0:
                    visited.add((nx, ny))
                    q.append((nx, ny))
    return a

def corner_mask_from_border(border_rgba: Image.Image, threshold: int = 18, shrink_px: int = 8, feather: float = 0.8) -> Image.Image:
    border_alpha = border_rgba.split()[-1].convert("L")
    hard = border_alpha.point(lambda p: 255 if p >= threshold else 0, mode="L")
    hard = fill_center_hole(hard)
    if shrink_px > 0:
        hard = hard.filter(ImageFilter.MinFilter(2 * shrink_px + 1))
    if feather and feather > 0:
        hard = hard.filter(ImageFilter.GaussianBlur(radius=feather))
    return hard

def compose_with_border(base_img: Image.Image, border_path: Path, out_size: int, centering: Tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    base = center_crop_to_square(base_img, out_size, centering=centering)

    border = Image.open(border_path)
    border = ImageOps.exif_transpose(border).convert("RGBA")
    if border.size != (out_size, out_size):
        border = border.resize((out_size, out_size), Image.LANCZOS)

    mask = corner_mask_from_border(border, threshold=18, shrink_px=8, feather=0.8)
    base.putalpha(ImageChops.multiply(base.split()[-1], mask))
    return Image.alpha_composite(base, border)


# ==========================
# Dataset import (EveryVideoGameEver)
# ==========================
def download_and_extract_zip(zip_url: str, cache_dir: Path, log_cb=None) -> Path:
    ensure_dir(cache_dir)
    zip_key = sha256_text(zip_url)
    zip_path = cache_dir / f"{zip_key}.zip"
    extract_root = cache_dir / f"{zip_key}_extracted"

    if extract_root.exists():
        return extract_root

    if not zip_path.exists():
        _emit_log(log_cb, f"[DATASET] Downloading zip: {zip_url}")
        data = download_bytes(zip_url, timeout_s=180)
        zip_path.write_bytes(data)

    _emit_log(log_cb, "[DATASET] Extracting zip…")
    ensure_dir(extract_root)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_root)

    return extract_root

def iter_json_files(root: Path) -> List[Path]:
    return sorted([p for p in root.rglob("*.json") if p.is_file()])

def dedupe_preserve(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out

def extract_titles_from_json(obj: Any) -> List[str]:
    preferred_keys = ["name", "title", "game", "Game", "Title", "Name"]

    def extract_from_item(item: Any) -> Optional[str]:
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for k in preferred_keys:
                v = item.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            for v in item.values():
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    titles: List[str] = []
    if isinstance(obj, dict):
        for container_key in ["data", "games", "items", "list", "entries"]:
            v = obj.get(container_key)
            if isinstance(v, list):
                for it in v:
                    t = extract_from_item(it)
                    if t:
                        titles.append(t)
                return dedupe_preserve(titles)
        t = extract_from_item(obj)
        return [t] if t else []

    if isinstance(obj, list):
        for it in obj:
            t = extract_from_item(it)
            if t:
                titles.append(t)
        return dedupe_preserve(titles)

    return []

def load_dataset_platform_titles(dataset_root: Path, gamesdb_subdir: str) -> Dict[str, List[str]]:
    gamesdb = dataset_root / gamesdb_subdir
    if not gamesdb.exists():
        raise RuntimeError(f"[DATASET] Could not find GamesDB at: {gamesdb}")

    platform_map: Dict[str, List[str]] = {}
    for jf in iter_json_files(gamesdb):
        platform_name = jf.stem
        try:
            obj = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            titles = extract_titles_from_json(obj)
            if titles:
                platform_map[platform_name] = titles
        except Exception:
            continue

    if not platform_map:
        raise RuntimeError("[DATASET] No platform JSONs found / no titles extracted.")
    return platform_map

def resolve_platform_titles(
    dataset_platform_to_titles: Dict[str, List[str]],
    platform_aliases: Dict[str, List[str]],
    desired_platform_key: str,
    platform_config: Optional[Dict[str, Any]] = None,
    callbacks=None
) -> Tuple[str, List[str]]:
    """
    Strict-normalized resolver:
      - Matches aliases to dataset keys by normalized equality (case/punct insensitive).
      - NO substring/prefix fuzzy matching (prevents DS/3DS, GB/GBC/GBA collisions).
      - Falls back to Wikipedia scraping if platform has wikipedia_url in config.
    """
    desired = desired_platform_key.strip()
    aliases = (platform_aliases.get(desired_platform_key, []) or []) + [desired]

    # Build normalized lookup for dataset keys
    norm_map = {}
    for k in dataset_platform_to_titles.keys():
        nk = norm_key(k)
        # if collision, keep the first; collisions are rare and should be fixed via aliasing
        norm_map.setdefault(nk, k)

    for a in aliases:
        na = norm_key(a)
        if not na:
            continue
        if na in norm_map:
            real_key = norm_map[na]
            return real_key, dataset_platform_to_titles[real_key]

    # No match in dataset - check for Wikipedia fallback
    if platform_config:
        wikipedia_url = platform_config.get("wikipedia_url")
        if wikipedia_url:
            _emit_log(callbacks, f"[DATASET] No dataset match for {desired_platform_key}, trying Wikipedia fallback...")
            titles = fetch_wikipedia_game_list(wikipedia_url, callbacks=callbacks)
            if titles:
                _emit_log(callbacks, f"[DATASET] Wikipedia fallback loaded {len(titles)} titles for {desired_platform_key}")
                return desired_platform_key, titles
            else:
                _emit_log(callbacks, f"[DATASET] Wikipedia fallback failed for {desired_platform_key}")

    raise KeyError(f'No dataset platform match for {desired_platform_key}. Tried aliases: {aliases}')




# ==========================
# Public API for UI
# ==========================
def read_platform_keys(config_path: Path) -> List[str]:
    cfg = load_yaml(config_path)
    platforms_cfg = cfg.get("platforms", {}) or {}
    return sorted(platforms_cfg.keys())

def get_output_dir(config_path: Path) -> Path:
    cfg = load_yaml(config_path)
    root = Path(config_path).resolve().parent
    paths = cfg.get("paths", {}) or {}
    return (root / paths.get("output_dir", "./output")).resolve()

def get_review_dir(config_path: Path) -> Path:
    cfg = load_yaml(config_path)
    root = Path(config_path).resolve().parent
    paths = cfg.get("paths", {}) or {}
    return (root / paths.get("review_dir", "./review")).resolve()


# ==========================
# Wikipedia Game List Scraper
# ==========================
def fetch_wikipedia_game_list(url: str, callbacks=None) -> List[str]:
    """
    Scrape game titles from a Wikipedia "List of games" page.
    Returns list of game titles.
    """
    import re
    from html import unescape

    try:
        _emit_log(callbacks, f"[WIKIPEDIA] Fetching game list from {url}")

        # Use Wikipedia API for cleaner HTML
        api_url = 'https://en.wikipedia.org/w/api.php'

        # Extract page title from URL
        page_title = url.split('/wiki/')[-1]

        params = {
            'action': 'parse',
            'page': page_title,
            'format': 'json',
            'prop': 'text',
            'formatversion': '2'
        }

        headers = {
            'User-Agent': 'IconGenerator/1.0 (Educational project for game icon generation)'
        }

        response = requests.get(api_url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if 'parse' not in data or 'text' not in data['parse']:
            _emit_log(callbacks, f"[WIKIPEDIA] No parse data returned for {page_title}")
            return []

        html_content = data['parse']['text']

        titles = []

        # Wikipedia game list format:
        # <tr><td><i>Game Title</i></td><td>Genre</td>...</tr>
        # Pattern to match <td><i>Title</i></td> at the start of table rows

        # Extract all <i> tags within <td> tags
        td_i_pattern = r'<td[^>]*><i>([^<]+)</i>'
        matches = re.findall(td_i_pattern, html_content)

        for match in matches:
            # Clean up the title
            title = unescape(match).strip()
            # Remove footnote references like [1], [a], etc.
            title = re.sub(r'\[[^\]]+\]', '', title).strip()

            # Skip empty, very short titles
            if len(title) < 2:
                continue

            # Filter out obvious non-game entries
            skip_terms = [
                'unreleased', 'cancelled', 'tba', 'tbd',
                'unknown', 'various', 'multiple', 'n/a',
                'yes', 'no', 'genre', 'developer', 'publisher'
            ]
            if any(skip in title.lower() for skip in skip_terms):
                continue

            # Only add unique titles
            if title not in titles:
                titles.append(title)

        _emit_log(callbacks, f"[WIKIPEDIA] Found {len(titles)} game titles")
        return titles

    except Exception as e:
        _emit_log(callbacks, f"[WIKIPEDIA] Error fetching {url}: {e}")
        return []

# ==========================
# Providers
# ==========================
def fetch_multiple_art_from_steamgriddb(
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    cache_dir: Path,
    allow_animated: bool,
    prefer_dim: str,
    square_styles: List[str],
    square_only: bool,
    platform_key: str,
    title: str,
    platform_hints: List[str],
    max_results: int = 5,
    callbacks=None
) -> List[Tuple[bytes, str]]:
    """
    Fetch multiple artwork options from SteamGridDB.
    Returns list of (bytes, source_tag) tuples.
    Uses smart search with multiple variants for better matching.
    """
    results = []

    try:
        # Clean the title first for better matching
        search_title = normalize_for_search(title)
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Searching for '{title}' (normalized: '{search_title}')...")

        # Use variant search for better results
        autocomplete_results = search_with_variants(api_key, base_url, title, timeout_s, delay_s, callbacks)

        if not autocomplete_results:
            _emit_log(callbacks, f"[DEBUG] SteamGridDB: No results found for any search variant")
            return results

        if delay_s > 0:
            time.sleep(delay_s)

        # Get best game ID using the normalized title for comparison
        game_id = choose_best_game_id(api_key, base_url, timeout_s, delay_s, search_title, platform_hints, autocomplete_results, 8, callbacks)
        if not game_id:
            return results

        # Fetch all grids for this game
        grids = grids_by_game(api_key, base_url, game_id, [prefer_dim], square_styles, timeout_s)
        if not grids:
            return results

        if delay_s > 0:
            time.sleep(delay_s)

        # Filter grids based on preferences
        suitable_grids = []
        for grid in grids:
            # Check animation
            if not allow_animated and grid.get("mime", "").startswith("image/webp"):
                continue
            # Check if square only
            if square_only and grid.get("width") != grid.get("height"):
                continue
            suitable_grids.append(grid)

        # Sort by score (highest first) to get the best quality artwork
        suitable_grids.sort(key=lambda x: (x.get("score", 0), x.get("upvotes", 0), x.get("id", 0)), reverse=True)

        _emit_log(callbacks, f"[DEBUG] SteamGridDB: {len(suitable_grids)} suitable grids after filtering, sorted by score")
        if suitable_grids:
            top_scores = [(g.get("score", 0), g.get("style", "?")) for g in suitable_grids[:5]]
            _emit_log(callbacks, f"[DEBUG] SteamGridDB: Top scores: {top_scores}")

        # Take up to max_results grids (now sorted by score)
        for grid in suitable_grids[:max_results]:
            url = grid.get("url")
            if not url:
                continue

            try:
                cache_key = sha256_text(url)
                cache_path = cache_dir / f"{cache_key}.bin"

                if cache_path.exists():
                    img_bytes = cache_path.read_bytes()
                else:
                    img_bytes = download_bytes(url, timeout_s)
                    cache_path.write_bytes(img_bytes)

                # Add grid style info to source tag
                style = grid.get("style", "unknown")
                source_tag = f"SteamGridDB - {style}"
                results.append((img_bytes, source_tag))

            except Exception as e:
                _emit_log(callbacks, f"[DEBUG] SteamGridDB: Failed to download grid - {e}")
                continue

        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Returning {len(results)} artwork options")
        return results

    except Exception as e:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Error - {e}")
        return results

def fetch_art_from_steamgriddb_square(
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    cache_dir: Path,
    allow_animated: bool,
    prefer_dim: str,
    square_styles: List[str],
    square_only: bool,
    platform_key: str,
    title: str,
    platform_hints: List[str],
    callbacks=None
) -> Optional[Tuple[bytes, str]]:
    # returns (bytes, source_tag) or None

    # Clean and normalize the title for better search
    search_title = normalize_for_search(title)

    _emit_log(callbacks, f"[DEBUG] SteamGridDB: Function called for '{title}' (normalized: '{search_title}')")

    try:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Searching with variants for '{title}'...")
        # Use smart variant search for better results
        results = search_with_variants(api_key, base_url, title, timeout_s, delay_s, callbacks)

        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Search returned {len(results) if results else 0} results")
        if delay_s > 0:
            time.sleep(delay_s)
    except Exception as e:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Search failed - {type(e).__name__}: {e}")
        return None
    if not results:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: No results found for '{title}'")
        return None

    _emit_log(callbacks, f"[DEBUG] SteamGridDB: Choosing best game ID from {len(results)} results...")
    # Use the normalized title for matching
    game_id = choose_best_game_id(api_key, base_url, timeout_s, delay_s, search_title, platform_hints, results, 8, callbacks)
    if not game_id:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: No matching game ID found")
        return None
    _emit_log(callbacks, f"[DEBUG] SteamGridDB: Selected game ID: {game_id}")

    try:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Fetching grids for game ID {game_id}...")
        grids = grids_by_game(api_key, base_url, game_id, [prefer_dim], square_styles, timeout_s)
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Found {len(grids) if grids else 0} grids")
        if delay_s > 0:
            time.sleep(delay_s)
    except Exception as e:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Grid fetch failed - {type(e).__name__}: {e}")
        return None

    _emit_log(callbacks, f"[DEBUG] SteamGridDB: Picking best grid from {len(grids)} options...")
    # Log top grid scores for debugging
    if grids:
        grids_with_scores = [(g.get("score", 0), g.get("style", "?"), g.get("width", 0), g.get("height", 0)) for g in grids[:5]]
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Top grid scores (score, style, w, h): {grids_with_scores}")
    best = pick_best_grid(grids, prefer_dim=prefer_dim, allow_animated=allow_animated, square_only=square_only)
    if not best or not best.get("url"):
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: No suitable grid found")
        return None
    _emit_log(callbacks, f"[DEBUG] SteamGridDB: Selected grid - score={best.get('score', 0)}, style={best.get('style', '?')}, dim={best.get('width')}x{best.get('height')}")

    url = best["url"]
    cache_key = sha256_text(url)
    cache_path = cache_dir / f"{cache_key}.bin"
    try:
        if cache_path.exists():
            _emit_log(callbacks, f"[DEBUG] SteamGridDB: Using cached image")
            return cache_path.read_bytes(), "steamgriddb_square"
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Downloading image...")
        img_bytes = download_bytes(url, timeout_s)
        cache_path.write_bytes(img_bytes)
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Image downloaded and cached")
        return img_bytes, "steamgriddb_square"
    except Exception as e:
        _emit_log(callbacks, f"[DEBUG] SteamGridDB: Download failed - {type(e).__name__}: {e}")
        return None


# ==========================
# Hero Image Provider (SteamGridDB)
# ==========================
def heroes_by_game(
    api_key: str,
    base_url: str,
    game_id: str,
    dimensions: Optional[List[str]],
    styles: Optional[List[str]],
    timeout_s: int
) -> List[dict]:
    """Fetch hero images for a game from SteamGridDB."""
    params = {}
    if dimensions:
        params["dimensions"] = ",".join(dimensions) if isinstance(dimensions, list) else dimensions
    if styles:
        params["styles"] = ",".join(styles) if isinstance(styles, list) else styles
    data = sgdb_get(api_key, base_url, f"heroes/game/{game_id}", params or None, timeout_s)
    return data.get("data", []) or []


def logos_by_game(
    api_key: str,
    base_url: str,
    game_id: str,
    styles: Optional[List[str]],
    timeout_s: int
) -> List[dict]:
    """Fetch logo images for a game from SteamGridDB.

    Logo styles: official, white, black, custom
    """
    params = {}
    if styles:
        params["styles"] = ",".join(styles) if isinstance(styles, list) else styles
    data = sgdb_get(api_key, base_url, f"logos/game/{game_id}", params or None, timeout_s)
    return data.get("data", []) or []


def fetch_heroes_from_steamgriddb(
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    cache_dir: Path,
    allow_animated: bool,
    prefer_dimensions: List[str],
    styles: List[str],
    platform_key: str,
    title: str,
    platform_hints: List[str],
    max_heroes: int = 1,
    callbacks=None
) -> List[Tuple[bytes, str]]:
    """
    Fetch hero images from SteamGridDB.

    Hero images are wide banner images typically used for Steam library backgrounds.
    Common dimensions: 1920x620, 3840x1240

    Returns list of (bytes, filename_hint) tuples.
    """
    results = []

    if not api_key:
        return results

    try:
        _emit_log(callbacks, f"[HERO] Searching SteamGridDB for heroes: '{title}'...")

        # Search for game
        autocomplete_results = search_autocomplete(api_key, base_url, title, timeout_s)
        if not autocomplete_results:
            _emit_log(callbacks, f"[HERO] No search results for '{title}'")
            return results

        if delay_s > 0:
            time.sleep(delay_s)

        # Get best game ID
        game_id = choose_best_game_id(
            api_key, base_url, timeout_s, delay_s,
            title, platform_hints, autocomplete_results, 8, callbacks
        )

        if not game_id:
            _emit_log(callbacks, f"[HERO] No matching game ID for '{title}'")
            return results

        _emit_log(callbacks, f"[HERO] Found game ID: {game_id}")

        # Fetch heroes
        heroes = heroes_by_game(api_key, base_url, game_id, prefer_dimensions, styles, timeout_s)

        if not heroes:
            _emit_log(callbacks, f"[HERO] No hero images found for game ID {game_id}")
            return results

        _emit_log(callbacks, f"[HERO] Found {len(heroes)} hero images")

        if delay_s > 0:
            time.sleep(delay_s)

        # Filter and download heroes
        suitable_heroes = []
        for hero in heroes:
            url = hero.get("url", "").strip()
            if not url:
                continue
            if not allow_animated and is_animated(url):
                continue
            suitable_heroes.append(hero)

        # Sort by score (primary), upvotes (secondary), id (tiebreaker) - highest first
        suitable_heroes.sort(key=lambda x: (x.get("score", 0), x.get("upvotes", 0), x.get("id", 0)), reverse=True)
        if suitable_heroes:
            _emit_log(callbacks, f"[HERO] Top hero scores: {[(h.get('score', 0), h.get('style', '?')) for h in suitable_heroes[:3]]}")

        # Download top heroes
        for i, hero in enumerate(suitable_heroes[:max_heroes]):
            url = hero.get("url")
            if not url:
                continue

            try:
                cache_key = sha256_text(url)
                cache_path = cache_dir / f"hero_{cache_key}.bin"

                if cache_path.exists():
                    img_bytes = cache_path.read_bytes()
                    _emit_log(callbacks, f"[HERO] Using cached hero {i+1}")
                else:
                    img_bytes = download_bytes(url, timeout_s)
                    cache_path.write_bytes(img_bytes)
                    _emit_log(callbacks, f"[HERO] Downloaded hero {i+1}")

                # Generate filename hint - hero_Y format (hero_1, hero_2, etc.)
                filename = f"hero_{i+1}"

                results.append((img_bytes, filename))

                if delay_s > 0:
                    time.sleep(delay_s)

            except Exception as e:
                _emit_log(callbacks, f"[HERO] Failed to download hero {i+1}: {e}")
                continue

        _emit_log(callbacks, f"[HERO] Retrieved {len(results)} hero images")
        return results

    except Exception as e:
        _emit_log(callbacks, f"[HERO] Error fetching heroes: {e}")
        return results


# ==========================
# Logo Fetching (SteamGridDB)
# ==========================

def fetch_logos_from_steamgriddb(
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    cache_dir: Path,
    allow_animated: bool,
    styles: List[str],
    platform_key: str,
    title: str,
    platform_hints: List[str],
    callbacks=None
) -> Optional[Tuple[bytes, str]]:
    """
    Fetch a logo image from SteamGridDB.

    Logo images are transparent PNG images of game titles/logos.
    Styles: official, white, black, custom

    Returns (bytes, filename_hint) tuple or None if no logo found.
    """
    if not api_key:
        return None

    try:
        _emit_log(callbacks, f"[LOGO] Searching SteamGridDB for logo: '{title}'...")

        # Search for game
        autocomplete_results = search_autocomplete(api_key, base_url, title, timeout_s)
        if not autocomplete_results:
            _emit_log(callbacks, f"[LOGO] No search results for '{title}'")
            return None

        if delay_s > 0:
            time.sleep(delay_s)

        # Get best game ID
        game_id = choose_best_game_id(
            api_key, base_url, timeout_s, delay_s,
            title, platform_hints, autocomplete_results, 8, callbacks
        )

        if not game_id:
            _emit_log(callbacks, f"[LOGO] No matching game ID for '{title}'")
            return None

        _emit_log(callbacks, f"[LOGO] Found game ID: {game_id}")

        # Fetch logos
        logos = logos_by_game(api_key, base_url, game_id, styles, timeout_s)

        if not logos:
            _emit_log(callbacks, f"[LOGO] No logos found for game ID {game_id}")
            return None

        _emit_log(callbacks, f"[LOGO] Found {len(logos)} logos")

        if delay_s > 0:
            time.sleep(delay_s)

        # Filter logos
        suitable_logos = []
        for logo in logos:
            url = logo.get("url", "").strip()
            if not url:
                continue
            if not allow_animated and is_animated(url):
                continue
            suitable_logos.append(logo)

        if not suitable_logos:
            _emit_log(callbacks, f"[LOGO] No suitable logos after filtering")
            return None

        # Sort by score (primary), upvotes (secondary), id (tiebreaker) - highest first
        suitable_logos.sort(key=lambda x: (x.get("score", 0), x.get("upvotes", 0), x.get("id", 0)), reverse=True)
        _emit_log(callbacks, f"[LOGO] Top logo scores: {[(l.get('score', 0), l.get('style', '?')) for l in suitable_logos[:3]]}")
        best_logo = suitable_logos[0]
        url = best_logo.get("url")

        if not url:
            return None

        try:
            cache_key = sha256_text(url)
            cache_path = cache_dir / f"logo_{cache_key}.bin"

            if cache_path.exists():
                img_bytes = cache_path.read_bytes()
                _emit_log(callbacks, f"[LOGO] Using cached logo")
            else:
                img_bytes = download_bytes(url, timeout_s)
                cache_path.write_bytes(img_bytes)
                _emit_log(callbacks, f"[LOGO] Downloaded logo")

            return (img_bytes, "title")

        except Exception as e:
            _emit_log(callbacks, f"[LOGO] Failed to download logo: {e}")
            return None

    except Exception as e:
        _emit_log(callbacks, f"[LOGO] Error fetching logo: {e}")
        return None


# ==========================
# Screenshot Fetching
# ==========================

def fetch_screenshots_from_igdb(
    *,
    client_id: str,
    client_secret: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    platform_map: Dict[str, int],
    platform_key: str,
    title: str,
    cache_dir: Path,
    max_screenshots: int = 3,
    callbacks=None
) -> List[Tuple[bytes, str]]:
    """
    Fetch screenshots from IGDB.
    Returns list of (bytes, filename_hint) tuples with slide_Y naming.
    """
    results = []

    # Get access token
    token = get_igdb_access_token(client_id, client_secret, timeout_s)
    if not token:
        _emit_log(callbacks, f"[SCREENSHOT] IGDB: Failed to get access token")
        return results

    # Get platform ID
    platform_id = platform_map.get(platform_key)
    if not platform_id:
        _emit_log(callbacks, f"[SCREENSHOT] IGDB: No platform mapping for {platform_key}")
        return results

    try:
        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        # Search for game with screenshots
        search_title = normalize_for_search(title)
        search_url = f"{base_url.rstrip('/')}/games"
        query = f'search "{search_title}"; fields name,screenshots.image_id; where platforms = ({platform_id}); limit 1;'

        _emit_log(callbacks, f"[SCREENSHOT] IGDB: Searching for '{title}'...")
        r = requests.post(search_url, headers=headers, data=query, timeout=timeout_s)
        r.raise_for_status()
        games = r.json()

        if delay_s > 0:
            time.sleep(delay_s)

        if not games:
            _emit_log(callbacks, f"[SCREENSHOT] IGDB: No games found for '{title}'")
            return results

        game = games[0]
        screenshots = game.get("screenshots", [])

        if not screenshots:
            _emit_log(callbacks, f"[SCREENSHOT] IGDB: No screenshots for '{game.get('name')}'")
            return results

        _emit_log(callbacks, f"[SCREENSHOT] IGDB: Found {len(screenshots)} screenshots")

        # Download screenshots
        for i, screenshot in enumerate(screenshots[:max_screenshots]):
            image_id = screenshot.get("image_id")
            if not image_id:
                continue

            try:
                # IGDB screenshot URL - use 720p size
                screenshot_url = f"https://images.igdb.com/igdb/image/upload/t_720p/{image_id}.jpg"

                cache_key = sha256_text(screenshot_url)
                cache_path = cache_dir / f"screenshot_{cache_key}.bin"

                if cache_path.exists():
                    img_bytes = cache_path.read_bytes()
                    _emit_log(callbacks, f"[SCREENSHOT] Using cached screenshot {i+1}")
                else:
                    img_bytes = download_bytes(screenshot_url, timeout_s)
                    cache_path.write_bytes(img_bytes)
                    _emit_log(callbacks, f"[SCREENSHOT] Downloaded screenshot {i+1}")

                # slide_Y naming format
                filename = f"slide_{i+1}"
                results.append((img_bytes, filename))

                if delay_s > 0:
                    time.sleep(delay_s)

            except Exception as e:
                _emit_log(callbacks, f"[SCREENSHOT] Failed to download screenshot {i+1}: {e}")
                continue

        _emit_log(callbacks, f"[SCREENSHOT] Retrieved {len(results)} screenshots from IGDB")
        return results

    except Exception as e:
        _emit_log(callbacks, f"[SCREENSHOT] IGDB error: {e}")
        return results


def fetch_screenshots_from_thegamesdb(
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    platform_map: Dict[str, int],
    platform_key: str,
    title: str,
    cache_dir: Path,
    max_screenshots: int = 3,
    callbacks=None
) -> List[Tuple[bytes, str]]:
    """
    Fetch screenshots from TheGamesDB.
    Returns list of (bytes, filename_hint) tuples with slide_Y naming.
    """
    results = []

    # Get platform ID
    platform_id = platform_map.get(platform_key)
    if not platform_id:
        _emit_log(callbacks, f"[SCREENSHOT] TheGamesDB: No platform mapping for {platform_key}")
        return results

    try:
        # Search for game
        search_title = normalize_for_search(title)
        search_url = f"{base_url.rstrip('/')}/Games/ByGameName"
        params = {
            "apikey": api_key,
            "name": search_title,
            "filter[platform]": platform_id,
            "include": "boxart"  # This includes all images
        }

        _emit_log(callbacks, f"[SCREENSHOT] TheGamesDB: Searching for '{title}'...")
        r = requests.get(search_url, params=params, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()

        if delay_s > 0:
            time.sleep(delay_s)

        games = data.get("data", {}).get("games", [])
        if not games:
            _emit_log(callbacks, f"[SCREENSHOT] TheGamesDB: No games found for '{title}'")
            return results

        game = games[0]
        game_id = game.get("id")

        if not game_id:
            return results

        # Get images for game
        images_url = f"{base_url.rstrip('/')}/Games/Images"
        img_params = {
            "apikey": api_key,
            "games_id": game_id,
            "filter[type]": "screenshot"
        }

        r = requests.get(images_url, params=img_params, timeout=timeout_s)
        r.raise_for_status()
        img_data = r.json()

        if delay_s > 0:
            time.sleep(delay_s)

        # Get base URL for images
        base_img_url = img_data.get("data", {}).get("base_url", {}).get("original", "")
        images = img_data.get("data", {}).get("images", {}).get(str(game_id), [])

        screenshots = [img for img in images if img.get("type") == "screenshot"]

        if not screenshots:
            _emit_log(callbacks, f"[SCREENSHOT] TheGamesDB: No screenshots for game ID {game_id}")
            return results

        _emit_log(callbacks, f"[SCREENSHOT] TheGamesDB: Found {len(screenshots)} screenshots")

        # Download screenshots
        for i, screenshot in enumerate(screenshots[:max_screenshots]):
            filename_part = screenshot.get("filename")
            if not filename_part or not base_img_url:
                continue

            try:
                screenshot_url = f"{base_img_url}{filename_part}"

                cache_key = sha256_text(screenshot_url)
                cache_path = cache_dir / f"screenshot_{cache_key}.bin"

                if cache_path.exists():
                    img_bytes = cache_path.read_bytes()
                    _emit_log(callbacks, f"[SCREENSHOT] Using cached screenshot {i+1}")
                else:
                    img_bytes = download_bytes(screenshot_url, timeout_s)
                    cache_path.write_bytes(img_bytes)
                    _emit_log(callbacks, f"[SCREENSHOT] Downloaded screenshot {i+1}")

                # slide_Y naming format
                filename = f"slide_{i+1}"
                results.append((img_bytes, filename))

                if delay_s > 0:
                    time.sleep(delay_s)

            except Exception as e:
                _emit_log(callbacks, f"[SCREENSHOT] Failed to download screenshot {i+1}: {e}")
                continue

        _emit_log(callbacks, f"[SCREENSHOT] Retrieved {len(results)} screenshots from TheGamesDB")
        return results

    except Exception as e:
        _emit_log(callbacks, f"[SCREENSHOT] TheGamesDB error: {e}")
        return results


def fetch_screenshots_from_libretro(
    *,
    lr_base: str,
    lr_playlist_map: Dict[str, str],
    timeout_s: int,
    platform_key: str,
    title: str,
    cache_dir: Path,
    max_screenshots: int = 3,
    callbacks=None
) -> List[Tuple[bytes, str]]:
    """
    Fetch screenshots from Libretro Named_Snaps directory.
    Returns list of (bytes, filename_hint) tuples with slide_Y naming.
    """
    results = []

    playlist = lr_playlist_map.get(platform_key)
    if not playlist:
        _emit_log(callbacks, f"[SCREENSHOT] Libretro: No playlist mapping for {platform_key}")
        return results

    # Try to find snapshots
    type_dir = "Named_Snaps"

    try:
        for cand in libretro_candidate_names(title):
            path = "/".join([
                requests.utils.quote(playlist, safe=""),
                requests.utils.quote(type_dir, safe=""),
                requests.utils.quote(cand + ".png", safe=""),
            ])
            url = f"{lr_base.rstrip('/')}/{path}"

            try:
                r = requests.get(url, timeout=timeout_s)
                if r.status_code == 200 and r.content:
                    # Libretro typically has one snapshot per game
                    cache_key = sha256_text(url)
                    cache_path = cache_dir / f"snapshot_{cache_key}.bin"
                    cache_path.write_bytes(r.content)

                    filename = "slide_1"
                    results.append((r.content, filename))
                    _emit_log(callbacks, f"[SCREENSHOT] Libretro: Found snapshot for '{title}'")
                    return results  # Libretro has single snapshots
            except Exception:
                continue

        _emit_log(callbacks, f"[SCREENSHOT] Libretro: No snapshot found for '{title}'")
        return results

    except Exception as e:
        _emit_log(callbacks, f"[SCREENSHOT] Libretro error: {e}")
        return results


def fetch_art_from_libretro(
    *,
    lr_base: str,
    lr_type_dir: str,
    lr_playlist_map: Dict[str, str],
    timeout_s: int,
    platform_key: str,
    title: str,
    cache_dir: Path,
    use_index_matching: bool,
    index_cache_hours: int,
    debug_log=None
) -> Optional[Tuple[bytes, str]]:
    playlist = lr_playlist_map.get(platform_key)
    if not playlist:
        return None

    b = libretro_try_download_boxart(
        base_url=lr_base,
        playlist_name=playlist,
        type_dir=lr_type_dir,
        title=title,
        timeout_s=timeout_s,
        cache_dir=cache_dir,
        use_index_matching=use_index_matching,
        index_cache_hours=index_cache_hours,
        debug_log=debug_log
    )
    if not b:
        return None
    return b, "libretro_boxart"


# ==========================
# IGDB Provider
# ==========================
_igdb_token_cache = {"token": None, "expires_at": 0}

def get_igdb_access_token(client_id: str, client_secret: str, timeout_s: int) -> Optional[str]:
    """Get IGDB access token using Twitch OAuth."""
    import time

    # Check cached token
    if _igdb_token_cache["token"] and time.time() < _igdb_token_cache["expires_at"]:
        return _igdb_token_cache["token"]

    # Request new token
    try:
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }
        r = requests.post(url, params=params, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()

        token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)

        # Cache token with 5 minute buffer
        _igdb_token_cache["token"] = token
        _igdb_token_cache["expires_at"] = time.time() + expires_in - 300

        return token
    except Exception:
        return None


def fetch_art_from_igdb(
    *,
    client_id: str,
    client_secret: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    platform_map: Dict[str, int],
    cover_size: str,
    platform_key: str,
    title: str,
    cache_dir: Path,
    debug_log=None
) -> Optional[Tuple[bytes, str]]:
    """Fetch artwork from IGDB."""
    def _log(msg):
        if debug_log and callable(debug_log):
            debug_log(msg)

    # Clean and normalize title for better search
    search_title = normalize_for_search(title)
    _log(f"[DEBUG] IGDB: Searching for '{title}' (normalized: '{search_title}')")

    # Get platform ID
    platform_id = platform_map.get(platform_key)
    if not platform_id:
        _log(f"[DEBUG] IGDB: No platform mapping for {platform_key}")
        return None
    _log(f"[DEBUG] IGDB: Platform {platform_key} -> ID {platform_id}")

    # Get access token
    _log(f"[DEBUG] IGDB: Getting access token...")
    token = get_igdb_access_token(client_id, client_secret, timeout_s)
    if not token:
        _log(f"[DEBUG] IGDB: Failed to get access token")
        return None
    _log(f"[DEBUG] IGDB: Got access token: {token[:20]}...")

    try:
        # Search for game using normalized title
        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        # IGDB uses POST with Apicalypse query language
        search_url = f"{base_url.rstrip('/')}/games"
        # Use normalized title for search
        query = f'search "{search_title}"; fields name,cover.image_id,platforms; where platforms = ({platform_id}); limit 5;'

        _log(f"[DEBUG] IGDB: Searching for '{search_title}' on platform {platform_id}...")
        r = requests.post(search_url, headers=headers, data=query, timeout=timeout_s)
        r.raise_for_status()
        games = r.json()
        _log(f"[DEBUG] IGDB: Found {len(games)} games")

        if delay_s > 0:
            time.sleep(delay_s)

        if not games:
            _log(f"[DEBUG] IGDB: No games found for '{title}' on platform {platform_id}")
            return None

        # Get best match (first result, IGDB search is quite good)
        game = games[0]
        _log(f"[DEBUG] IGDB: Best match: '{game.get('name')}'")
        cover = game.get("cover")

        if not cover or "image_id" not in cover:
            _log(f"[DEBUG] IGDB: No cover found for '{game.get('name')}'")
            return None

        # Build cover URL
        image_id = cover["image_id"]
        # IGDB image URL format: https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg
        # Sizes: cover_small (90x128), cover_big (264x374), 720p (1280x720), 1080p (1920x1080)
        cover_url = f"https://images.igdb.com/igdb/image/upload/t_{cover_size}/{image_id}.jpg"
        _log(f"[DEBUG] IGDB: Cover URL: {cover_url}")

        # Download and cache
        cache_key = sha256_text(cover_url)
        cache_path = cache_dir / f"{cache_key}.bin"

        if cache_path.exists():
            _log(f"[DEBUG] IGDB: Using cached image")
            return cache_path.read_bytes(), "igdb_cover"

        _log(f"[DEBUG] IGDB: Downloading cover...")
        img_bytes = download_bytes(cover_url, timeout_s)
        cache_path.write_bytes(img_bytes)
        _log(f"[DEBUG] IGDB: Cover downloaded and cached")

        return img_bytes, "igdb_cover"

    except Exception as e:
        _log(f"[DEBUG] IGDB: Error - {type(e).__name__}: {e}")
        return None


# ==========================
# TheGamesDB Provider
# ==========================
def fetch_art_from_thegamesdb(
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
    delay_s: float,
    platform_map: Dict[str, int],
    prefer_image_type: str,
    platform_key: str,
    title: str,
    cache_dir: Path,
    debug_log=None
) -> Optional[Tuple[bytes, str]]:
    """Fetch artwork from TheGamesDB."""
    def _log(msg):
        if debug_log and callable(debug_log):
            debug_log(msg)

    # Clean and normalize title for better search
    search_title = normalize_for_search(title)
    _log(f"[DEBUG] TheGamesDB: Searching for '{title}' (normalized: '{search_title}')")

    # Get platform ID
    platform_id = platform_map.get(platform_key)
    if not platform_id:
        _log(f"[DEBUG] TheGamesDB: No platform mapping for {platform_key}")
        return None
    _log(f"[DEBUG] TheGamesDB: Platform {platform_key} -> ID {platform_id}")

    try:
        # Search for game using normalized title
        search_url = f"{base_url.rstrip('/')}/Games/ByGameName"
        params = {
            "apikey": api_key,
            "name": search_title,
            "filter[platform]": platform_id
        }

        _log(f"[DEBUG] TheGamesDB: Searching for '{search_title}' on platform {platform_id}...")
        r = requests.get(search_url, params=params, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()

        if delay_s > 0:
            time.sleep(delay_s)

        games = data.get("data", {}).get("games", [])
        _log(f"[DEBUG] TheGamesDB: Found {len(games)} games")
        if not games:
            _log(f"[DEBUG] TheGamesDB: No games found for '{title}' on platform {platform_id}")
            return None

        # Get first match
        game = games[0]
        game_id = game.get("id")
        game_name = game.get("game_title", title)
        _log(f"[DEBUG] TheGamesDB: Best match: '{game_name}' (ID: {game_id})")

        # Fetch images for this game
        images_url = f"{base_url.rstrip('/')}/Games/Images"
        params = {
            "apikey": api_key,
            "games_id": game_id
        }

        _log(f"[DEBUG] TheGamesDB: Fetching images for game ID {game_id}...")
        r = requests.get(images_url, params=params, timeout=timeout_s)
        r.raise_for_status()
        img_data = r.json()

        if delay_s > 0:
            time.sleep(delay_s)

        # Get base image URL
        base_img_url = img_data.get("data", {}).get("base_url", {}).get("original")
        images_list = img_data.get("data", {}).get("images", {}).get(str(game_id), [])
        _log(f"[DEBUG] TheGamesDB: Found {len(images_list) if images_list else 0} images")

        if not images_list or not base_img_url:
            _log(f"[DEBUG] TheGamesDB: No images found for '{game_name}'")
            return None

        # Find preferred image type
        best_image = None
        for img in images_list:
            if img.get("type") == prefer_image_type:
                best_image = img
                break

        # Fallback to any boxart or first image
        if not best_image:
            for img in images_list:
                if img.get("type") == "boxart":
                    best_image = img
                    break

        if not best_image and images_list:
            best_image = images_list[0]

        if not best_image:
            _log(f"[DEBUG] TheGamesDB: No suitable images for '{game_name}'")
            return None

        # Build image URL
        filename = best_image.get("filename")
        image_url = f"{base_img_url}{filename}"
        _log(f"[DEBUG] TheGamesDB: Selected image: {image_url}")

        # Download and cache
        cache_key = sha256_text(image_url)
        cache_path = cache_dir / f"{cache_key}.bin"

        if cache_path.exists():
            _log(f"[DEBUG] TheGamesDB: Using cached image")
            return cache_path.read_bytes(), "thegamesdb_boxart"

        _log(f"[DEBUG] TheGamesDB: Downloading image...")
        img_bytes = download_bytes(image_url, timeout_s)
        cache_path.write_bytes(img_bytes)
        _log(f"[DEBUG] TheGamesDB: Image downloaded and cached")

        return img_bytes, "thegamesdb_boxart"

    except Exception as e:
        _log(f"[DEBUG] TheGamesDB: Error - {type(e).__name__}: {e}")
        return None


# Stub "elsewhere" provider you can implement later
def fetch_art_from_custom_http(*, timeout_s: int, platform_key: str, title: str) -> Optional[Tuple[bytes, str]]:
    return None


# ==========================
# Config Migration
# ==========================
def migrate_legacy_art_sources(art_sources: dict) -> dict:
    """Migrate old 'mode' string to new providers list structure."""
    if "providers" in art_sources:
        return art_sources  # Already migrated

    # Parse legacy mode string
    mode = art_sources.get("mode", "steamgriddb_then_libretro")
    sg_square = art_sources.get("steamgriddb_square_only", True)
    lr_crop = art_sources.get("libretro_crop_mode", "center_crop")

    # Build providers list from mode
    providers = []
    if mode == "steamgriddb":
        providers = [{"id": "steamgriddb", "enabled": True, "square_only": sg_square}]
    elif mode == "libretro":
        providers = [{"id": "libretro", "enabled": True, "crop_mode": lr_crop}]
    elif mode == "libretro_then_steamgriddb":
        providers = [
            {"id": "libretro", "enabled": True, "crop_mode": lr_crop},
            {"id": "steamgriddb", "enabled": True, "square_only": sg_square}
        ]
    else:  # steamgriddb_then_libretro (default)
        providers = [
            {"id": "steamgriddb", "enabled": True, "square_only": sg_square},
            {"id": "libretro", "enabled": True, "crop_mode": lr_crop}
        ]

    # Add new providers (disabled by default)
    providers.extend([
        {"id": "igdb", "enabled": False},
        {"id": "thegamesdb", "enabled": False}
    ])

    return {"providers": providers, "mode": mode}  # Keep mode for reference


def run_job(
    config_path: Path,
    platforms: List[str],
    workers: int,
    limit: int,
    cancel: CancelToken,
    callbacks=None,
    source_order: Optional[List[Dict[str, Any]]] = None,
    source_mode: Optional[str] = None,
    steamgriddb_square_only: Optional[bool] = None,
    search_term: Optional[str] = None,
    letter_filter: Optional[str] = None,
    interactive_mode: bool = False,
    download_heroes: bool = False,
    hero_count: int = 1,
    region_preference: Optional[str] = None,
    fallback_settings: Optional[Dict[str, Any]] = None,
    download_screenshots: bool = False,
    screenshot_count: int = 3,
    copy_to_device: bool = False,
    device_path: Optional[str] = None,
    scrape_logos: bool = True,
    logo_fallback_to_boxart: bool = True,
    custom_border_settings: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:

    config_path = Path(config_path)
    root = config_path.resolve().parent

    try:
        cfg = load_yaml(config_path)
    except Exception as e:
        return False, f"Failed to read config: {e}"

    out_size = int(cfg.get("output_size", 1024))
    export_format = str(cfg.get("export_format", "JPEG")).upper()
    jpeg_quality = int(cfg.get("jpeg_quality", 95))

    paths = cfg.get("paths", {}) or {}
    borders_dir = root / paths.get("borders_dir", "./borders")
    output_dir = root / paths.get("output_dir", "./output")
    review_dir = root / paths.get("review_dir", "./review")
    cache_dir = root / paths.get("cache_dir", "./cache")
    dataset_cache_dir = root / paths.get("dataset_cache_dir", "./dataset_cache")

    for d in [borders_dir, output_dir, review_dir, cache_dir, dataset_cache_dir]:
        ensure_dir(d)

    platforms_cfg = cfg.get("platforms", {}) or {}
    platform_aliases = cfg.get("platform_aliases", {}) or {}
    platform_hints_cfg = cfg.get("sgdb_platform_hints", {}) or {}

    # Dataset
    dataset_cfg = cfg.get("dataset", {}) or {}
    repo_zip_url = dataset_cfg.get("repo_zip_url")
    gamesdb_subdir = dataset_cfg.get("gamesdb_subdir", "EveryVideoGameEver-main/GamesDB")
    cfg_limit = int(dataset_cfg.get("per_platform_limit", 0))
    per_platform_limit = limit if limit > 0 else cfg_limit
    if not repo_zip_url:
        return False, "dataset.repo_zip_url is missing in config.yaml"

    # Art source configuration - migrate legacy format
    art_sources = migrate_legacy_art_sources(cfg.get("art_sources", {}) or {})

    # Build provider_order and settings
    provider_order = []
    provider_settings = {}

    # UI-provided source_order takes precedence
    if source_order is not None:
        providers_config = source_order
    else:
        providers_config = art_sources.get("providers", [])

    for prov_cfg in providers_config:
        prov_id = prov_cfg.get("id")
        if prov_cfg.get("enabled", False):
            provider_order.append(prov_id)
            provider_settings[prov_id] = prov_cfg

    # Legacy override from UI if source_mode provided (backward compat)
    if source_mode:
        mode = source_mode
        if mode == "steamgriddb":
            provider_order = ["steamgriddb"]
        elif mode == "libretro":
            provider_order = ["libretro"]
        elif mode == "libretro_then_steamgriddb":
            provider_order = ["libretro", "steamgriddb"]
        else:  # steamgriddb_then_libretro
            provider_order = ["steamgriddb", "libretro"]

        # Rebuild settings for legacy mode
        provider_settings = {}
        for pid in provider_order:
            provider_settings[pid] = {"id": pid, "enabled": True}
            if pid == "steamgriddb" and steamgriddb_square_only is not None:
                provider_settings[pid]["square_only"] = steamgriddb_square_only

    # Validate we have at least one provider
    if not provider_order:
        return False, "No artwork sources enabled. Enable at least one source in config or UI."

    # SteamGridDB config
    sg = cfg.get("steamgriddb", {}) or {}
    api_env = sg.get("api_key_env", "SGDB_API_KEY")
    api_key = os.environ.get(api_env, "").strip()
    base_url = sg.get("base_url", "https://www.steamgriddb.com/api/v2")
    timeout_s = int(sg.get("request_timeout_seconds", 40))
    delay_s = float(sg.get("delay_seconds", 0.25))
    allow_animated = bool(sg.get("allow_animated", False))
    prefer_dimensions = sg.get("prefer_dimensions", ["1024x1024"])
    prefer_dim = prefer_dimensions[0] if prefer_dimensions else "1024x1024"
    # Valid SteamGridDB styles: alternate, material, white_logo, blurred, no_logo
    # Invalid styles: official, black_logo (will cause 400 errors)
    square_styles = sg.get("square_styles", ["alternate", "material", "white_logo", "blurred", "no_logo"])
    # Get square_only from provider settings if steamgriddb is enabled
    sg_square_only = True  # Default value
    if "steamgriddb" in provider_settings:
        sg_square_only = bool(provider_settings["steamgriddb"].get("square_only", True))

    # Libretro config
    lr = cfg.get("libretro", {}) or {}
    lr_base = lr.get("base_url", "https://thumbnails.libretro.com")
    lr_type_dir = lr.get("type_dir", "Named_Boxarts")
    lr_playlist_map = lr.get("playlist_names", {}) or {}
    use_index_matching = bool(lr.get("use_index_matching", True))
    index_cache_hours = int(lr.get("index_cache_hours", 168))

    # IGDB config
    igdb_cfg = cfg.get("igdb", {}) or {}
    igdb_client_id_env = igdb_cfg.get("client_id_env", "IGDB_CLIENT_ID")
    igdb_client_secret_env = igdb_cfg.get("client_secret_env", "IGDB_CLIENT_SECRET")
    igdb_client_id = os.environ.get(igdb_client_id_env, "").strip()
    igdb_client_secret = os.environ.get(igdb_client_secret_env, "").strip()
    igdb_base_url = igdb_cfg.get("base_url", "https://api.igdb.com/v4")
    igdb_timeout = int(igdb_cfg.get("request_timeout_seconds", 30))
    igdb_delay = float(igdb_cfg.get("delay_seconds", 0.25))
    igdb_cover_size = igdb_cfg.get("cover_size", "cover_big")
    igdb_platform_map = igdb_cfg.get("platform_map", {}) or {}

    # TheGamesDB config
    tgdb_cfg = cfg.get("thegamesdb", {}) or {}
    tgdb_api_key_env = tgdb_cfg.get("api_key_env", "TGDB_API_KEY")
    tgdb_api_key = os.environ.get(tgdb_api_key_env, "").strip()
    tgdb_base_url = tgdb_cfg.get("base_url", "https://api.thegamesdb.net/v1")
    tgdb_timeout = int(tgdb_cfg.get("request_timeout_seconds", 30))
    tgdb_delay = float(tgdb_cfg.get("delay_seconds", 0.5))
    tgdb_image_type = tgdb_cfg.get("prefer_image_type", "boxart")
    tgdb_platform_map = tgdb_cfg.get("platform_map", {}) or {}

    # Auto-centering config
    ac = cfg.get("auto_centering", {}) or {}
    ac_enabled = bool(ac.get("enabled", True))
    ac_sources = set(ac.get("sources", ["libretro_boxart"]))
    ac_tolerance = float(ac.get("tolerance", 0.06))
    ac_steps = int(ac.get("search_steps", 5))
    ac_span = float(ac.get("search_span", 0.22))
    ac_alpha_threshold = int(ac.get("alpha_threshold", 16))
    ac_margin_pct = float(ac.get("margin_pct", 0.06))

    # Logo detection config
    ld = cfg.get("logo_detection", {}) or {}
    ld_enabled = bool(ld.get("enabled", False))
    ld_method = str(ld.get("method", "auto"))
    ld_sources = set(ld.get("sources", ["libretro_boxart", "steamgriddb_square"]))
    ld_min_content = float(ld.get("min_content_ratio", 0.15))
    ld_max_crop = float(ld.get("max_crop_ratio", 0.85))

    # Fallback icon config (from UI or config)
    fallback_cfg = fallback_settings or cfg.get("fallback_icons", {}) or {}
    use_fallback = bool(fallback_cfg.get("use_platform_icon_fallback", False))
    skip_scraping = bool(fallback_cfg.get("skip_scraping_use_platform_icon", False))
    fallback_icons_path = fallback_cfg.get("fallback_icons_path", "")
    if not fallback_icons_path:
        # Default to fallback_icons folder next to app
        fallback_icons_dir = root / "fallback_icons"
    else:
        fallback_icons_dir = Path(fallback_icons_path)

    # Platform icons dir (used as fallback source if fallback_icons doesn't have the platform)
    platform_icons_dir = root / paths.get("platform_icons_dir", "./platform_icons")

    _emit_log(callbacks, f"[CONFIG] Fallback icons: use_fallback={use_fallback}, skip_scraping={skip_scraping}")

    # Log provider order for debugging
    _emit_log(callbacks, f"[CONFIG] Provider order: {provider_order}")
    _emit_log(callbacks, f"[CONFIG] Provider settings: {provider_settings}")

    # Validate required API keys for enabled providers
    if "steamgriddb" in provider_order and not api_key:
        return False, f"Missing SteamGridDB API key env var: {api_env}"
    if "igdb" in provider_order and (not igdb_client_id or not igdb_client_secret):
        return False, f"Missing IGDB credentials: {igdb_client_id_env}, {igdb_client_secret_env}"
    if "thegamesdb" in provider_order and not tgdb_api_key:
        return False, f"Missing TheGamesDB API key env var: {tgdb_api_key_env}"

    # Log API key status
    _emit_log(callbacks, f"[CONFIG] SteamGridDB API key: {'SET' if api_key else 'NOT SET'}")
    _emit_log(callbacks, f"[CONFIG] IGDB Client ID: {'SET' if igdb_client_id else 'NOT SET'}")
    _emit_log(callbacks, f"[CONFIG] IGDB Client Secret: {'SET' if igdb_client_secret else 'NOT SET'}")
    _emit_log(callbacks, f"[CONFIG] TheGamesDB API key: {'SET' if tgdb_api_key else 'NOT SET'}")

    _emit_log(callbacks, f"[CONFIG] Using providers: {', '.join(provider_order)}")

    if cancel.is_cancelled:
        return False, "Cancelled."

    # Load dataset
    _emit_log(callbacks, "[DATASET] Loading game database...")
    dataset_root = download_and_extract_zip(repo_zip_url, dataset_cache_dir, log_cb=callbacks)
    dataset_platform_to_titles = load_dataset_platform_titles(dataset_root, gamesdb_subdir)
    _emit_log(callbacks, f"[DATASET] Found {len(dataset_platform_to_titles)} platform JSONs.")

    # Build task list
    tasks = []

    for platform_key in platforms:
        if cancel.is_cancelled:
            return False, "Cancelled."

        pconf = platforms_cfg.get(platform_key, {})

        # Check for custom border override - now supports per-platform borders
        custom_border_enabled = custom_border_settings.get("enabled", False) if custom_border_settings else False
        custom_border_path_str = custom_border_settings.get("path", "") if custom_border_settings else ""
        per_platform_borders = custom_border_settings.get("per_platform", {}) if custom_border_settings else {}

        # Priority: 1) Per-platform custom border, 2) Global custom border, 3) Platform default border
        if platform_key in per_platform_borders and per_platform_borders[platform_key] and Path(per_platform_borders[platform_key]).exists():
            # Use per-platform custom border
            border_path = Path(per_platform_borders[platform_key])
            _emit_log(callbacks, f"[INFO] Using per-platform custom border for {platform_key}")
        elif custom_border_enabled and custom_border_path_str and Path(custom_border_path_str).exists():
            # Use global custom border for all platforms
            border_path = Path(custom_border_path_str)
            _emit_log(callbacks, f"[INFO] Using global custom border for {platform_key}")
        else:
            # Use platform-specific border (default)
            border_file = pconf.get("border_file")
            # For custom platforms, the border_file might be an absolute path
            if border_file and Path(border_file).is_absolute() and Path(border_file).exists():
                border_path = Path(border_file)
            else:
                border_path = borders_dir / border_file if border_file else None
            if not border_path or not border_path.exists():
                _emit_log(callbacks, f"[WARN] Missing border for {platform_key}: {border_path}")
                continue

        try:
            _, titles = resolve_platform_titles(
                dataset_platform_to_titles,
                platform_aliases,
                platform_key,
                platform_config=pconf,
                callbacks=callbacks
            )
        except Exception as e:
            _emit_log(callbacks, f"[WARN] {e}")
            # If we have a search_term, we can still proceed without a database match
            if search_term:
                titles = []
                _emit_log(callbacks, f"[INFO] Platform {platform_key} not in database, will use search term directly")
            else:
                continue

        # Apply search/filter before limit
        if search_term:
            # When user explicitly searches for something, only return that specific game
            # Don't return multiple fuzzy matches - user wants exactly what they searched for
            if titles:
                # Try to find an exact or near-exact match in the database
                fuzzy_matches = fuzzy_match_title(search_term, titles, threshold=0.7)  # Higher threshold for explicit search

                if fuzzy_matches:
                    # Only use the BEST match, not multiple - user searched for a specific game
                    best_match, best_score = fuzzy_matches[0]
                    # Only use database match if it's a very good match (>= 0.85)
                    # Otherwise use the search term directly to let the API find it
                    if best_score >= 0.85:
                        titles = [best_match]
                        _emit_log(callbacks, f"[FILTER] Search '{search_term}' on {platform_key}: Found exact match '{best_match}' (score: {best_score:.2f})")
                    else:
                        # Score not high enough - use search term directly
                        titles = [search_term]
                        _emit_log(callbacks, f"[FILTER] Search '{search_term}' on {platform_key}: No exact match (best: {best_score:.2f}), using search term directly")
                else:
                    # No fuzzy matches - use search term directly
                    titles = [search_term]
                    _emit_log(callbacks, f"[FILTER] Search '{search_term}' on {platform_key}: No database match, using search term directly")
            else:
                # No database titles available - use search term directly
                titles = [search_term]
                _emit_log(callbacks, f"[FILTER] Search '{search_term}' on {platform_key}: No database, using search term directly")
        elif letter_filter and letter_filter != "All":
            # Filter by starting letter
            if letter_filter == "0-9":
                titles = [t for t in titles if t[0].isdigit()]
            elif letter_filter == "#":
                titles = [t for t in titles if not t[0].isalnum()]
            else:
                titles = [t for t in titles if t[0].upper() == letter_filter.upper()]
            _emit_log(callbacks, f"[FILTER] Letter '{letter_filter}' on {platform_key}: {len(titles)} matches")

        if per_platform_limit > 0:
            titles = titles[:per_platform_limit]

        # Use iiSU folder naming convention (lowercase shorthand like "gb", "gc", "n3ds")
        iisu_folder_name = get_iisu_folder_name(platform_key)
        out_plat = output_dir / iisu_folder_name
        rev_plat = review_dir / iisu_folder_name
        ensure_dir(out_plat)
        ensure_dir(rev_plat)

        # Get the correct file extension for the export format
        file_ext = get_export_extension(export_format)

        for title in titles:
            # Create folder per game with icon and title images
            game_folder = out_plat / safe_slug(title)
            out_path = game_folder / f"icon.{file_ext}"
            if out_path.exists():
                continue
            tasks.append((platform_key, title, border_path, out_path, rev_plat))

    total = len(tasks)
    if total == 0:
        return True, "Nothing to do (already generated / missing borders / no matches)."

    _emit_progress(callbacks, 0, total)
    _emit_log(callbacks, f"[PLAN] Queued {total} images. Workers={workers}")

    done = 0
    done_lock = threading.Lock()
    errors = 0

    # Prefetch cache for interactive mode - stores artwork fetched in background
    prefetch_cache: Dict[str, List[Dict[str, Any]]] = {}
    prefetch_lock = threading.Lock()
    prefetch_thread: Optional[threading.Thread] = None

    def prefetch_artwork(platform_key: str, title: str, hints: List[str], cache_key: str):
        """Prefetch artwork in background and store in cache."""
        try:
            options = fetch_all_artwork_options_impl(platform_key, title, hints)
            with prefetch_lock:
                prefetch_cache[cache_key] = options
        except Exception as e:
            _emit_log(callbacks, f"[PREFETCH] Failed for {title}: {e}")

    def start_prefetch(platform_key: str, title: str, hints: List[str]):
        """Start prefetching artwork for a game in the background."""
        nonlocal prefetch_thread
        cache_key = f"{platform_key}:{title}"
        with prefetch_lock:
            if cache_key in prefetch_cache:
                return  # Already cached
        prefetch_thread = threading.Thread(
            target=prefetch_artwork,
            args=(platform_key, title, hints, cache_key),
            daemon=True
        )
        prefetch_thread.start()

    def get_prefetched_or_fetch(platform_key: str, title: str, hints: List[str]) -> List[Dict[str, Any]]:
        """Get prefetched artwork if available, otherwise fetch now."""
        nonlocal prefetch_thread
        cache_key = f"{platform_key}:{title}"

        # Check if prefetch is in progress for this game
        if prefetch_thread is not None and prefetch_thread.is_alive():
            # Wait for prefetch to complete (with timeout)
            prefetch_thread.join(timeout=35)

        # Check cache
        with prefetch_lock:
            if cache_key in prefetch_cache:
                options = prefetch_cache.pop(cache_key)
                _emit_log(callbacks, f"[PREFETCH] Using cached artwork for {title} ({len(options)} options)")
                return options

        # Not in cache, fetch now
        return fetch_all_artwork_options_impl(platform_key, title, hints)

    def fetch_all_artwork_options(platform_key: str, title: str, hints: List[str]) -> List[Dict[str, Any]]:
        """Wrapper that uses prefetch cache when available."""
        return get_prefetched_or_fetch(platform_key, title, hints)

    def fetch_all_artwork_options_impl(platform_key: str, title: str, hints: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch ALL artwork options from ALL providers IN PARALLEL (doesn't stop at first match).
        Returns list of dicts with keys: 'image_data' (bytes), 'source' (str), 'provider' (str)
        """
        options = []
        options_lock = threading.Lock()

        def fetch_from_steamgriddb():
            if cancel.is_cancelled:
                return
            try:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Fetching from steamgriddb...")
                results = fetch_multiple_art_from_steamgriddb(
                    api_key=api_key,
                    base_url=base_url,
                    timeout_s=timeout_s,
                    delay_s=delay_s,
                    cache_dir=cache_dir,
                    allow_animated=allow_animated,
                    prefer_dim=prefer_dim,
                    square_styles=square_styles,
                    square_only=sg_square_only,
                    platform_key=platform_key,
                    title=title,
                    platform_hints=hints,
                    max_results=5,
                    callbacks=callbacks,
                )
                with options_lock:
                    for img_bytes, source_tag in results:
                        options.append({
                            'image_data': img_bytes,
                            'source': source_tag,
                            'provider': 'steamgriddb'
                        })
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Found {len(results)} from steamgriddb")
            except Exception as e:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - steamgriddb failed: {type(e).__name__}: {e}")

        def fetch_from_libretro():
            if cancel.is_cancelled:
                return
            try:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Fetching from libretro...")
                got = fetch_art_from_libretro(
                    lr_base=lr_base,
                    lr_type_dir=lr_type_dir,
                    lr_playlist_map=lr_playlist_map,
                    timeout_s=timeout_s,
                    platform_key=platform_key,
                    title=title,
                    cache_dir=cache_dir,
                    use_index_matching=use_index_matching,
                    index_cache_hours=index_cache_hours,
                    debug_log=lambda m: _emit_log(callbacks, m),
                )
                if got:
                    img_bytes, source_tag = got
                    with options_lock:
                        options.append({
                            'image_data': img_bytes,
                            'source': source_tag,
                            'provider': 'libretro'
                        })
                    _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Found 1 from libretro")
            except Exception as e:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - libretro failed: {type(e).__name__}: {e}")

        def fetch_from_igdb():
            if cancel.is_cancelled:
                return
            try:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Fetching from igdb...")
                got = fetch_art_from_igdb(
                    client_id=igdb_client_id,
                    client_secret=igdb_client_secret,
                    base_url=igdb_base_url,
                    timeout_s=igdb_timeout,
                    delay_s=igdb_delay,
                    platform_map=igdb_platform_map,
                    cover_size=igdb_cover_size,
                    platform_key=platform_key,
                    title=title,
                    cache_dir=cache_dir,
                    debug_log=lambda m: _emit_log(callbacks, m),
                )
                if got:
                    img_bytes, source_tag = got
                    with options_lock:
                        options.append({
                            'image_data': img_bytes,
                            'source': source_tag,
                            'provider': 'igdb'
                        })
                    _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Found 1 from igdb")
            except Exception as e:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - igdb failed: {type(e).__name__}: {e}")

        def fetch_from_thegamesdb():
            if cancel.is_cancelled:
                return
            try:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Fetching from thegamesdb...")
                got = fetch_art_from_thegamesdb(
                    api_key=tgdb_api_key,
                    base_url=tgdb_base_url,
                    timeout_s=tgdb_timeout,
                    delay_s=tgdb_delay,
                    platform_map=tgdb_platform_map,
                    prefer_image_type=tgdb_image_type,
                    platform_key=platform_key,
                    title=title,
                    cache_dir=cache_dir,
                    debug_log=lambda m: _emit_log(callbacks, m),
                )
                if got:
                    img_bytes, source_tag = got
                    with options_lock:
                        options.append({
                            'image_data': img_bytes,
                            'source': source_tag,
                            'provider': 'thegamesdb'
                        })
                    _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Found 1 from thegamesdb")
            except Exception as e:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - thegamesdb failed: {type(e).__name__}: {e}")

        def fetch_from_custom_http():
            if cancel.is_cancelled:
                return
            try:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Fetching from custom_http...")
                got = fetch_art_from_custom_http(
                    timeout_s=timeout_s,
                    platform_key=platform_key,
                    title=title
                )
                if got:
                    img_bytes, source_tag = got
                    with options_lock:
                        options.append({
                            'image_data': img_bytes,
                            'source': source_tag,
                            'provider': 'custom_http'
                        })
                    _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Found 1 from custom_http")
            except Exception as e:
                _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - custom_http failed: {type(e).__name__}: {e}")

        # Map provider names to fetch functions
        provider_funcs = {
            'steamgriddb': fetch_from_steamgriddb,
            'libretro': fetch_from_libretro,
            'igdb': fetch_from_igdb,
            'thegamesdb': fetch_from_thegamesdb,
            'custom_http': fetch_from_custom_http,
        }

        # Run all enabled providers in parallel
        threads = []
        for prov in provider_order:
            if prov in provider_funcs:
                t = threading.Thread(target=provider_funcs[prov], daemon=True)
                threads.append(t)
                t.start()

        # Wait for all threads to complete (with timeout)
        for t in threads:
            t.join(timeout=30)  # 30 second timeout per provider

        return options

    def find_fallback_icon(platform_key: str) -> Optional[bytes]:
        """
        Find and load a fallback icon for the given platform.
        Looks in fallback_icons_dir first, then platform_icons_dir.
        Returns image bytes or None if not found.
        """
        # Normalize platform key for file matching (handle variations)
        possible_names = [
            platform_key,
            platform_key.upper(),
            platform_key.lower(),
            platform_key.replace("_", " "),
            platform_key.replace(" ", "_"),
        ]

        # Try fallback_icons_dir first
        for name in possible_names:
            for ext in [".png", ".PNG", ".jpg", ".jpeg"]:
                fallback_path = fallback_icons_dir / f"{name}{ext}"
                if fallback_path.exists():
                    try:
                        with open(fallback_path, "rb") as f:
                            _emit_log(callbacks, f"[FALLBACK] Found fallback icon: {fallback_path}")
                            return f.read()
                    except Exception as e:
                        _emit_log(callbacks, f"[FALLBACK] Error reading {fallback_path}: {e}")

        # Try platform_icons_dir as secondary fallback
        for name in possible_names:
            for ext in [".png", ".PNG", ".jpg", ".jpeg"]:
                platform_icon_path = platform_icons_dir / f"{name}{ext}"
                if platform_icon_path.exists():
                    try:
                        with open(platform_icon_path, "rb") as f:
                            _emit_log(callbacks, f"[FALLBACK] Using platform icon: {platform_icon_path}")
                            return f.read()
                    except Exception as e:
                        _emit_log(callbacks, f"[FALLBACK] Error reading {platform_icon_path}: {e}")

        return None

    def work_item(platform_key: str, title: str, border_path: Path, out_path: Path, rev_dir: Path) -> bool:
        nonlocal errors

        if cancel.is_cancelled:
            return False

        slug = safe_slug(title)
        hints = platform_hints_cfg.get(platform_key, []) or []

        img_bytes = None
        source_tag = None

        # Skip scraping mode - just use platform icon directly
        if skip_scraping:
            _emit_log(callbacks, f"[SKIP_SCRAPING] {platform_key}: {title} - Using platform icon (scraping disabled)")
            img_bytes = find_fallback_icon(platform_key)
            if img_bytes:
                source_tag = "fallback_platform_icon"
            else:
                _emit_log(callbacks, f"[FAIL] {platform_key}: {title} - No fallback icon found for platform")
                (rev_dir / f"{slug}__no_fallback.json").write_text(
                    json.dumps({
                        "title": title,
                        "platform": platform_key,
                        "error": "no fallback icon found for platform"
                    }, indent=2),
                    encoding="utf-8"
                )
                return False
        else:
            _emit_log(callbacks, f"[SEARCH] {platform_key}: {title} - Trying providers: {provider_order}")

        # Check if provider_order is empty (only relevant when not skip_scraping)
        if not skip_scraping and not provider_order:
            _emit_log(callbacks, f"[ERROR] {platform_key}: {title} - No providers configured!")
            (rev_dir / f"{slug}__no_providers.json").write_text(
                json.dumps({
                    "title": title,
                    "platform": platform_key,
                    "error": "no providers configured"
                }, indent=2),
                encoding="utf-8"
            )
            return False

        # Interactive mode: fetch from ALL providers and let user choose
        if interactive_mode and not skip_scraping:
            _emit_log(callbacks, f"[INTERACTIVE] {platform_key}: {title} - Fetching from all providers...")
            artwork_options = fetch_all_artwork_options(platform_key, title, hints)

            if not artwork_options:
                # Try fallback icon if enabled
                if use_fallback:
                    _emit_log(callbacks, f"[FALLBACK] {platform_key}: {title} - No artwork found, trying fallback icon")
                    img_bytes = find_fallback_icon(platform_key)
                    if img_bytes:
                        source_tag = "fallback_platform_icon"
                        _emit_log(callbacks, f"[FALLBACK] {platform_key}: {title} - Using fallback platform icon")
                        # Skip to compositing
                    else:
                        _emit_log(callbacks, f"[FAIL] {platform_key}: {title} - No artwork and no fallback icon found")
                        (rev_dir / f"{slug}__no_art.json").write_text(
                            json.dumps({
                                "title": title,
                                "platform": platform_key,
                                "provider_order": provider_order,
                                "error": "no art found and no fallback icon"
                            }, indent=2),
                            encoding="utf-8"
                        )
                        return False
                else:
                    _emit_log(callbacks, f"[FAIL] {platform_key}: {title} - No artwork found from any provider")
                    (rev_dir / f"{slug}__no_art.json").write_text(
                        json.dumps({
                            "title": title,
                            "platform": platform_key,
                            "provider_order": provider_order,
                            "error": "no art found from any provider"
                        }, indent=2),
                        encoding="utf-8"
                    )
                    return False

            # Request user selection from all options (only if we have options and didn't use fallback)
            if artwork_options and img_bytes is None:
                selected_index = _request_user_selection(callbacks, title, platform_key, artwork_options)

                if selected_index == -1:
                    # User cancelled all - set cancel token
                    _emit_log(callbacks, f"[STOP] User cancelled interactive mode")
                    cancel.cancel()
                    return False
                elif selected_index is None:
                    # User skipped this title
                    _emit_log(callbacks, f"[SKIP] {platform_key}: {title} - Skipped by user")
                    return False
                elif 0 <= selected_index < len(artwork_options):
                    # User selected an option
                    selected = artwork_options[selected_index]
                    img_bytes = selected['image_data']
                    source_tag = selected['source']
                    _emit_log(callbacks, f"[SELECTED] {platform_key}: {title} - User selected from {source_tag}")
                else:
                    _emit_log(callbacks, f"[ERROR] {platform_key}: {title} - Invalid selection index")
                    return False

        # Automatic mode: try each provider in order until one works
        elif not skip_scraping:
            for prov in provider_order:
                if cancel.is_cancelled:
                    return False

                if prov == "steamgriddb":
                    _emit_log(callbacks, f"[DB] {platform_key}: {title} - Searching SteamGridDB...")
                    try:
                        got = fetch_art_from_steamgriddb_square(
                            api_key=api_key,
                            base_url=base_url,
                            timeout_s=timeout_s,
                            delay_s=delay_s,
                            cache_dir=cache_dir,
                            allow_animated=allow_animated,
                            prefer_dim=prefer_dim,
                            square_styles=square_styles,
                            square_only=sg_square_only,
                            platform_key=platform_key,
                            title=title,
                            platform_hints=hints,
                            callbacks=callbacks,
                        )
                    except Exception as e:
                        _emit_log(callbacks, f"[ERROR] {platform_key}: {title} - SteamGridDB call failed: {type(e).__name__}: {e}")
                        got = None
                    if got:
                        img_bytes, source_tag = got
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Found in SteamGridDB")
                        break
                    else:
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Not found in SteamGridDB")

                elif prov == "libretro":
                    _emit_log(callbacks, f"[DB] {platform_key}: {title} - Searching Libretro...")
                    got = fetch_art_from_libretro(
                        lr_base=lr_base,
                        lr_type_dir=lr_type_dir,
                        lr_playlist_map=lr_playlist_map,
                        timeout_s=timeout_s,
                        platform_key=platform_key,
                        title=title,
                        cache_dir=cache_dir,
                        use_index_matching=use_index_matching,
                        index_cache_hours=index_cache_hours,
                        debug_log=lambda m: _emit_log(callbacks, m),
                    )
                    if got:
                        img_bytes, source_tag = got
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Found in Libretro")
                        break
                    else:
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Not found in Libretro")

                elif prov == "igdb":
                    _emit_log(callbacks, f"[DB] {platform_key}: {title} - Searching IGDB...")
                    got = fetch_art_from_igdb(
                        client_id=igdb_client_id,
                        client_secret=igdb_client_secret,
                        base_url=igdb_base_url,
                        timeout_s=igdb_timeout,
                        delay_s=igdb_delay,
                        platform_map=igdb_platform_map,
                        cover_size=igdb_cover_size,
                        platform_key=platform_key,
                        title=title,
                        cache_dir=cache_dir,
                        debug_log=lambda m: _emit_log(callbacks, m),
                    )
                    if got:
                        img_bytes, source_tag = got
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Found in IGDB")
                        break
                    else:
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Not found in IGDB")

                elif prov == "thegamesdb":
                    _emit_log(callbacks, f"[DB] {platform_key}: {title} - Searching TheGamesDB...")
                    got = fetch_art_from_thegamesdb(
                        api_key=tgdb_api_key,
                        base_url=tgdb_base_url,
                        timeout_s=tgdb_timeout,
                        delay_s=tgdb_delay,
                        platform_map=tgdb_platform_map,
                        prefer_image_type=tgdb_image_type,
                        platform_key=platform_key,
                        title=title,
                        cache_dir=cache_dir,
                        debug_log=lambda m: _emit_log(callbacks, m),
                    )
                    if got:
                        img_bytes, source_tag = got
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Found in TheGamesDB")
                        break
                    else:
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Not found in TheGamesDB")

                elif prov == "custom_http":
                    _emit_log(callbacks, f"[DB] {platform_key}: {title} - Searching Custom HTTP...")
                    got = fetch_art_from_custom_http(timeout_s=timeout_s, platform_key=platform_key, title=title)
                    if got:
                        img_bytes, source_tag = got
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Found in Custom HTTP")
                        break
                    else:
                        _emit_log(callbacks, f"[DB] {platform_key}: {title} - Not found in Custom HTTP")

        if img_bytes is None:
            # Try fallback icon if enabled
            if use_fallback:
                _emit_log(callbacks, f"[FALLBACK] {platform_key}: {title} - No artwork found, trying fallback icon")
                img_bytes = find_fallback_icon(platform_key)
                if img_bytes:
                    source_tag = "fallback_platform_icon"
                    _emit_log(callbacks, f"[FALLBACK] {platform_key}: {title} - Using fallback platform icon")
                else:
                    _emit_log(callbacks, f"[FAIL] {platform_key}: {title} - No artwork and no fallback icon found")
                    (rev_dir / f"{slug}__no_art.json").write_text(
                        json.dumps({
                            "title": title,
                            "platform": platform_key,
                            "provider_order": provider_order,
                            "error": "no art found and no fallback icon"
                        }, indent=2),
                        encoding="utf-8"
                    )
                    return False
            else:
                _emit_log(callbacks, f"[FAIL] {platform_key}: {title} - No art found from any provider")
                (rev_dir / f"{slug}__no_art.json").write_text(
                    json.dumps({
                        "title": title,
                        "platform": platform_key,
                        "provider_order": provider_order,
                        "error": "no art found from any provider"
                    }, indent=2),
                    encoding="utf-8"
                )
                return False

        try:
            src_img = Image.open(BytesIO(img_bytes))

            # Logo detection and cropping if enabled and source matches
            if ld_enabled and source_tag in ld_sources:
                src_img = detect_and_crop_logo(
                    src_img,
                    method=ld_method,
                    min_content_ratio=ld_min_content,
                    max_crop_ratio=ld_max_crop,
                    debug_log=lambda m: _emit_log(callbacks, m)
                )

            # Auto-centering if enabled and source is in configured sources
            centering = (0.5, 0.5)
            if ac_enabled and source_tag in ac_sources:
                centering, (mx, my, cnt) = _best_centering_for_img(
                    src_img, out_size,
                    steps=ac_steps, span=ac_span,
                    alpha_threshold=ac_alpha_threshold, margin_pct=ac_margin_pct
                )
                dx, dy = abs(mx - 0.5), abs(my - 0.5)
                if dx > ac_tolerance or dy > ac_tolerance:
                    (rev_dir / f"{slug}__offcenter.json").write_text(
                        json.dumps({
                            "title": title,
                            "platform": platform_key,
                            "source": source_tag,
                            "centering": [centering[0], centering[1]],
                            "content_centroid": [mx, my],
                            "deviation": [dx, dy],
                            "count": cnt
                        }, indent=2),
                        encoding="utf-8"
                    )
                    _emit_log(callbacks, f"[ALIGN] Off-center: {platform_key}: {title} centroid=({mx:.3f},{my:.3f})")

            out_img = compose_with_border(src_img, border_path, out_size, centering=centering)
            # Ensure game folder exists
            ensure_dir(out_path.parent)
            # Save as icon
            save_image_for_export(out_img, out_path, export_format, jpeg_quality)

            # Handle title image - either scrape logo or duplicate boxart
            file_ext = get_export_extension(export_format)
            title_path = out_path.parent / f"title.{file_ext}"
            logo_saved = False

            if scrape_logos and api_key:
                # Try to fetch logo from SteamGridDB
                try:
                    logo_cfg = cfg.get("logos", {}) or {}
                    logo_styles = logo_cfg.get("styles", ["official", "white", "black"])

                    logo_result = fetch_logos_from_steamgriddb(
                        api_key=api_key,
                        base_url=base_url,
                        timeout_s=timeout_s,
                        delay_s=delay_s,
                        cache_dir=cache_dir,
                        allow_animated=allow_animated,
                        styles=logo_styles,
                        platform_key=platform_key,
                        title=title,
                        platform_hints=hints,
                        callbacks=callbacks
                    )

                    if logo_result:
                        logo_bytes, _ = logo_result
                        try:
                            logo_img = Image.open(BytesIO(logo_bytes))
                            logo_img = ImageOps.exif_transpose(logo_img).convert("RGBA")
                            save_image_for_export(logo_img, title_path, export_format, jpeg_quality)
                            logo_saved = True
                            _emit_log(callbacks, f"[LOGO] Saved logo as title for {title}")
                        except Exception as le:
                            _emit_log(callbacks, f"[LOGO] Failed to save logo: {le}")
                except Exception as logo_err:
                    _emit_log(callbacks, f"[LOGO] Error fetching logo for {title}: {logo_err}")

            # If no logo was saved and fallback is enabled, use boxart duplicate
            if not logo_saved and (logo_fallback_to_boxart or not scrape_logos):
                save_image_for_export(out_img, title_path, export_format, jpeg_quality)
                if scrape_logos:
                    _emit_log(callbacks, f"[LOGO] No logo found, using boxart as fallback for title")

            _emit_preview(callbacks, out_path)
            if source_tag:
                _emit_log(callbacks, f"[OK] {platform_key}: {title} ({source_tag}) -> {out_path.parent.name}/")
            else:
                _emit_log(callbacks, f"[OK] {platform_key}: {title} -> {out_path.parent.name}/")

            # Download hero images if enabled
            if download_heroes and api_key:
                try:
                    hero_cfg = cfg.get("hero_images", {}) or {}
                    hero_dimensions = hero_cfg.get("prefer_dimensions", ["1920x620", "3840x1240"])
                    hero_styles = hero_cfg.get("styles", ["alternate", "blurred", "material"])

                    heroes = fetch_heroes_from_steamgriddb(
                        api_key=api_key,
                        base_url=base_url,
                        timeout_s=timeout_s,
                        delay_s=delay_s,
                        cache_dir=cache_dir,
                        allow_animated=allow_animated,
                        prefer_dimensions=hero_dimensions,
                        styles=hero_styles,
                        platform_key=platform_key,
                        title=title,
                        platform_hints=hints,
                        max_heroes=hero_count,
                        callbacks=callbacks
                    )

                    for hero_bytes, hero_filename in heroes:
                        hero_path = out_path.parent / f"{hero_filename}.{file_ext}"
                        try:
                            hero_img = Image.open(BytesIO(hero_bytes))
                            hero_img = ImageOps.exif_transpose(hero_img).convert("RGBA")
                            save_image_for_export(hero_img, hero_path, export_format, jpeg_quality)
                            _emit_log(callbacks, f"[HERO] Saved {hero_filename} for {title}")
                        except Exception as he:
                            _emit_log(callbacks, f"[HERO] Failed to save {hero_filename}: {he}")

                except Exception as hero_err:
                    _emit_log(callbacks, f"[HERO] Error downloading heroes for {title}: {hero_err}")

            # Download screenshots if enabled
            if download_screenshots:
                try:
                    screenshots = []

                    # Try IGDB first if credentials available
                    if igdb_client_id and igdb_client_secret and not screenshots:
                        screenshots = fetch_screenshots_from_igdb(
                            client_id=igdb_client_id,
                            client_secret=igdb_client_secret,
                            base_url=igdb_base_url,
                            timeout_s=igdb_timeout,
                            delay_s=igdb_delay,
                            platform_map=igdb_platform_map,
                            platform_key=platform_key,
                            title=title,
                            cache_dir=cache_dir,
                            max_screenshots=screenshot_count,
                            callbacks=callbacks
                        )

                    # Try TheGamesDB if IGDB didn't have screenshots
                    if not screenshots and tgdb_api_key:
                        screenshots = fetch_screenshots_from_thegamesdb(
                            api_key=tgdb_api_key,
                            base_url=tgdb_base_url,
                            timeout_s=tgdb_timeout,
                            delay_s=tgdb_delay,
                            platform_map=tgdb_platform_map,
                            platform_key=platform_key,
                            title=title,
                            cache_dir=cache_dir,
                            max_screenshots=screenshot_count,
                            callbacks=callbacks
                        )

                    # Try Libretro snapshots as fallback
                    if not screenshots:
                        screenshots = fetch_screenshots_from_libretro(
                            lr_base=lr_base,
                            lr_playlist_map=lr_playlist_map,
                            timeout_s=timeout_s,
                            platform_key=platform_key,
                            title=title,
                            cache_dir=cache_dir,
                            max_screenshots=screenshot_count,
                            callbacks=callbacks
                        )

                    # Save screenshots with slide_Y naming
                    for screenshot_bytes, screenshot_filename in screenshots:
                        screenshot_path = out_path.parent / f"{screenshot_filename}.{file_ext}"
                        try:
                            screenshot_img = Image.open(BytesIO(screenshot_bytes))
                            screenshot_img = ImageOps.exif_transpose(screenshot_img).convert("RGBA")
                            save_image_for_export(screenshot_img, screenshot_path, export_format, jpeg_quality)
                            _emit_log(callbacks, f"[SCREENSHOT] Saved {screenshot_filename} for {title}")
                        except Exception as se:
                            _emit_log(callbacks, f"[SCREENSHOT] Failed to save {screenshot_filename}: {se}")

                except Exception as screenshot_err:
                    _emit_log(callbacks, f"[SCREENSHOT] Error downloading screenshots for {title}: {screenshot_err}")

            return True
        except Exception as e:
            _emit_log(callbacks, f"[ERROR] {platform_key}: {title} - Compose error: {e}")
            (rev_dir / f"{slug}__compose_error.json").write_text(
                json.dumps({"title": title, "platform": platform_key, "source": source_tag, "error": str(e)}, indent=2),
                encoding="utf-8"
            )
            return False

    max_workers = max(1, int(workers))

    # For interactive mode, process sequentially but with prefetching
    if interactive_mode:
        _emit_log(callbacks, "[INTERACTIVE] Using sequential processing with prefetching")
        for i, (p, t, b, o, r) in enumerate(tasks):
            if cancel.is_cancelled:
                _emit_log(callbacks, "[STOP] Cancelled by user.")
                break

            # Start prefetching next game's artwork while processing current
            if i + 1 < len(tasks):
                next_p, next_t, _, _, _ = tasks[i + 1]
                next_hints = platform_hints_cfg.get(next_p, []) or []
                start_prefetch(next_p, next_t, next_hints)

            ok = False
            try:
                ok = work_item(p, t, b, o, r)
            except Exception as e:
                _emit_log(callbacks, f"[ERROR] {p}: {t} - {e}")
                ok = False

            if not ok:
                errors += 1

            with done_lock:
                done += 1
                _emit_progress(callbacks, done, total)
    else:
        # Non-interactive mode: use parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(work_item, p, t, b, o, r) for (p, t, b, o, r) in tasks]

            for fut in as_completed(futures):
                if cancel.is_cancelled:
                    _emit_log(callbacks, "[STOP] Cancelled by user. Cancelling remaining tasks...")
                    # Cancel all pending futures
                    for f in futures:
                        f.cancel()
                    # Shutdown executor immediately
                    ex.shutdown(wait=False, cancel_futures=True)
                    break

                ok = False
                try:
                    ok = fut.result(timeout=1.0)  # Add timeout to prevent hanging
                except Exception:
                    ok = False

                if not ok:
                    errors += 1

                with done_lock:
                    done += 1
                    _emit_progress(callbacks, done, total)

    if cancel.is_cancelled:
        return False, f"Cancelled. Completed {done}/{total} (errors={errors})."

    # Copy to device if enabled
    if copy_to_device and device_path:
        _emit_log(callbacks, f"[DEVICE] Starting copy to device: {device_path}")
        try:
            copied, copy_errors = copy_output_to_device(
                output_dir=output_dir,
                device_base_path=device_path,
                callbacks=callbacks
            )
            _emit_log(callbacks, f"[DEVICE] Copied {copied} items to device ({copy_errors} errors)")
        except Exception as copy_err:
            _emit_log(callbacks, f"[DEVICE] Failed to copy to device: {copy_err}")

    return True, f"Finished. Completed {done}/{total} (errors={errors})."


def copy_output_to_device(
    output_dir: Path,
    device_base_path: str,
    callbacks=None
) -> Tuple[int, int]:
    """
    Copy generated output to connected Android device via ADB.

    Args:
        output_dir: Local output directory containing platform folders
        device_base_path: Base path on device (e.g., /sdcard/Android/media/com.iisulauncher/iiSULauncher/assets/media/roms/consoles)
        callbacks: Progress callbacks

    Returns:
        Tuple of (files_copied, errors)
    """
    import subprocess
    import shutil

    copied = 0
    errors = 0

    # Find ADB
    adb_path = shutil.which("adb")
    if not adb_path:
        # Try common locations
        from adb_setup import is_adb_installed
        is_installed, adb_exe = is_adb_installed()
        if is_installed and adb_exe:
            adb_path = str(adb_exe)
        else:
            _emit_log(callbacks, "[DEVICE] ADB not found. Please install Android SDK Platform Tools.")
            return 0, 1

    # Check for connected devices
    try:
        result = subprocess.run(
            [adb_path, "devices"],
            capture_output=True, text=True, timeout=10,
            **_get_subprocess_flags()
        )
        lines = result.stdout.strip().split('\n')[1:]  # Skip header
        devices = [l.split('\t')[0] for l in lines if '\tdevice' in l]

        if not devices:
            _emit_log(callbacks, "[DEVICE] No Android devices connected. Enable USB debugging and connect device.")
            return 0, 1

        _emit_log(callbacks, f"[DEVICE] Found {len(devices)} connected device(s)")

    except Exception as e:
        _emit_log(callbacks, f"[DEVICE] Failed to check devices: {e}")
        return 0, 1

    # Iterate through platform folders in output directory
    output_dir = Path(output_dir)
    if not output_dir.exists():
        _emit_log(callbacks, f"[DEVICE] Output directory not found: {output_dir}")
        return 0, 1

    for platform_folder in output_dir.iterdir():
        if not platform_folder.is_dir():
            continue

        platform_name = platform_folder.name
        _emit_log(callbacks, f"[DEVICE] Processing platform: {platform_name}")

        # Iterate through game folders
        for game_folder in platform_folder.iterdir():
            if not game_folder.is_dir():
                continue

            game_name = game_folder.name
            device_game_path = f"{device_base_path}/{platform_name}/{game_name}"

            # Create directory on device
            try:
                subprocess.run(
                    [adb_path, "shell", "mkdir", "-p", device_game_path],
                    capture_output=True, timeout=30,
                    **_get_subprocess_flags()
                )
            except Exception as e:
                _emit_log(callbacks, f"[DEVICE] Failed to create directory for {game_name}: {e}")
                errors += 1
                continue

            # Copy all files in game folder
            for file_path in game_folder.iterdir():
                if not file_path.is_file():
                    continue

                device_file_path = f"{device_game_path}/{file_path.name}"

                try:
                    result = subprocess.run(
                        [adb_path, "push", str(file_path), device_file_path],
                        capture_output=True, text=True, timeout=60,
                        **_get_subprocess_flags()
                    )

                    if result.returncode == 0:
                        copied += 1
                    else:
                        _emit_log(callbacks, f"[DEVICE] Failed to copy {file_path.name}: {result.stderr}")
                        errors += 1

                except subprocess.TimeoutExpired:
                    _emit_log(callbacks, f"[DEVICE] Timeout copying {file_path.name}")
                    errors += 1
                except Exception as e:
                    _emit_log(callbacks, f"[DEVICE] Error copying {file_path.name}: {e}")
                    errors += 1

    return copied, errors
