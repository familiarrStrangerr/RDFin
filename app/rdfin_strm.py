#!/usr/bin/env python3
"""
rd_strm.py - RealDebrid -> Jellyfin .strm helper (extension-stripping + external logs)

Commands:
  - add-movie --title "Title" --link "hoster/or/direct/link"
  - add-episode --show "Show Name" --season 1 --episode 1 --link "..."
  - add-movie-links --links "line1\nline2\n..."  (or --links-file path)
  - add-episode-links --show "Show" --season 1 --links "line1\nline2\n..." (or --links-file)

Behavior:
 - Writes .strm files under MEDIA_ROOT (/media by default)
 - Directory and base filename are created from RD filename or link, with file extension removed
 - Logs appended to LOG_ROOT/{movies,tv}/YYYY-MM-DD.log (LOG_ROOT default /fetch_logs)
 - .strm contains only the single current direct URL (overwritten on refresh)
"""
from __future__ import annotations
import os
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse, unquote
from datetime import datetime, timezone

load_dotenv()

REALDEBRID_TOKEN = os.getenv("REALDEBRID_TOKEN")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/media"))
LOG_ROOT = Path(os.getenv("LOG_ROOT", "/fetch_logs"))
USER_AGENT = "rd-strm-tool/1.0"
API_BASE = "https://api.real-debrid.com/rest/1.0"

if not REALDEBRID_TOKEN:
    raise SystemExit("Please set REALDEBRID_TOKEN in environment or .env file.")

def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat()

def unrestrict(link: str) -> dict:
    """
    Call Real-Debrid unrestrict/link endpoint.
    Returns a dict with keys including 'filename' and 'download' (direct link).
    Raises RuntimeError on non-200.
    """
    url = f"{API_BASE}/unrestrict/link"
    headers = {"Authorization": f"Bearer {REALDEBRID_TOKEN}", "User-Agent": USER_AGENT}
    data = {"link": link}
    resp = requests.post(url, headers=headers, data=data, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Real-Debrid error {resp.status_code}: {resp.text}")
    j = resp.json()
    if isinstance(j, list):
        j = j[0]
    # canonicalize
    filename = j.get("filename") or j.get("file") or j.get("name") or None
    direct = j.get("download") or j.get("link") or j.get("main") or j.get("stream") or None
    return {"filename": filename, "direct": direct, "raw": j}

def sanitize_name(name: str) -> str:
    """Remove problematic filesystem chars and trim."""
    if not name:
        return "unnamed"
    # remove control and reserved chars for filenames
    safe = "".join(c for c in name if c not in r'\/:*?"<>|').strip()
    # trim trailing dots/spaces
    return safe.rstrip(". ").strip()

def name_from_url(url: str) -> str:
    """Extract a filename-like base from a URL path if RD didn't provide a name."""
    try:
        p = urlparse(url)
        name = Path(unquote(p.path)).name
        if not name:
            name = p.netloc.replace('.', '_')
        return sanitize_name(name)
    except Exception:
        return "unnamed"

def strip_extension(name: str) -> str:
    """Return the stem (remove extension); handles names with multiple dots."""
    return Path(name).stem if name else "unnamed"

def write_strm_file(dest: Path, direct_url: str):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        fh.write(direct_url.strip() + "\n")
    print(f"Wrote .strm -> {dest}")

def log_entry(media_type: str, original_link: str, target_path: Path, rd_filename: str | None):
    """
    Append log line to LOG_ROOT/{media_type}/YYYY-MM-DD.log
    Format:
      ISO | link=<original_link> | target=<abs_target_path> | rd_filename=<rd_filename>
    """
    assert media_type in ("movies", "tv")
    logs_dir = LOG_ROOT / media_type
    logs_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"{date_str}.log"
    ts = iso_now()
    rdname = rd_filename or ""
    line = f"{ts} | link={original_link} | target={str(target_path)} | rd_filename={rdname}\n"
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(f"Logged to {log_file}")

# --- single movie/episode handlers ---

def add_movie(title: str, link: str):
    """Create folder MEDIA_ROOT/movies/<title_without_ext>/<title_without_ext>.strm"""
    # title might contain extension; strip it
    base = strip_extension(title)
    safe = sanitize_name(base)
    folder = MEDIA_ROOT / "movies" / safe
    strm_path = folder / f"{safe}.strm"
    resp = unrestrict(link)
    direct = resp.get("direct")
    if not direct:
        raise RuntimeError("No direct link returned from Real-Debrid.")
    write_strm_file(strm_path, direct)
    log_entry("movies", link, strm_path, resp.get("filename"))

def add_episode(show: str, season: int, episode: int, link: str):
    """
    Place episodes under MEDIA_ROOT/tv/<Show Name>/Season NN/<basename>.strm
    Basename is taken from RD filename (stem) or from URL.
    If RD filename contains SxxExx it will be preserved (stem), else auto-number.
    """
    show_name = sanitize_name(show)
    season_folder = f"Season {int(season):02d}"
    resp = unrestrict(link)
    direct = resp.get("direct")
    if not direct:
        raise RuntimeError("No direct link returned from Real-Debrid.")
    rd_fname = resp.get("filename")
    if rd_fname:
        base = strip_extension(rd_fname)
    else:
        base = name_from_url(direct)
        base = strip_extension(base)
    base_safe = sanitize_name(base)
    # if filename already contains SxxExx keep it, otherwise include SxxExx from provided episode
    import re
    if re.search(r'S\d{2}E\d{2}', base_safe, re.IGNORECASE):
        final_name = f"{base_safe}.strm"
    else:
        sxxexx = f"S{int(season):02d}E{int(episode):02d}"
        final_name = f"{base_safe} - {sxxexx}.strm"
    dest = MEDIA_ROOT / "tv" / show_name / season_folder / final_name
    write_strm_file(dest, direct)
    log_entry("tv", link, dest, resp.get("filename"))

# --- multi-link handlers ---

def add_movie_links_from_list(links: list[str]):
    written = 0
    errors = []
    for l in links:
        link = l.strip()
        if not link:
            continue
        try:
            resp = unrestrict(link)
            direct = resp.get("direct")
            if not direct:
                raise RuntimeError("No direct URL returned")
            fname = resp.get("filename")
            if not fname and direct:
                fname = name_from_url(direct)
            base = strip_extension(fname or name_from_url(link) or "unnamed")
            safe = sanitize_name(base)
            dest = MEDIA_ROOT / "movies" / safe / f"{safe}.strm"
            write_strm_file(dest, direct)
            log_entry("movies", link, dest, resp.get("filename"))
            written += 1
        except Exception as e:
            errors.append((link, str(e)))
            print(f"[ERR] {link}: {e}")
    print(f"Done. Written: {written}. Errors: {len(errors)}")
    return written, errors

def add_episode_links_from_list(show: str, season: int, links: list[str]):
    written = 0
    errors = []
    show_name = sanitize_name(show)
    season_folder = f"Season {int(season):02d}"
    season_path = MEDIA_ROOT / "tv" / show_name / season_folder
    season_path.mkdir(parents=True, exist_ok=True)
    for l in links:
        link = l.strip()
        if not link:
            continue
        try:
            resp = unrestrict(link)
            direct = resp.get("direct")
            if not direct:
                raise RuntimeError("No direct URL returned")
            fname = resp.get("filename")
            if not fname and direct:
                fname = name_from_url(direct)
            base = strip_extension(fname or name_from_url(link) or f"{show_name}_ep")
            base_safe = sanitize_name(base)
            # detect SxxExx in base_safe
            import re
            m = re.search(r'(S\d{2}E\d{2})', base_safe, re.IGNORECASE)
            if m:
                final_name = f"{base_safe}.strm"
            else:
                # auto index: count existing .strm in season folder and append next
                existing = len(list(season_path.glob("*.strm")))
                idx = existing + 1
                sxxexx = f"S{int(season):02d}E{int(idx):02d}"
                final_name = f"{base_safe} - {sxxexx}.strm"
            dest = season_path / final_name
            write_strm_file(dest, direct)
            log_entry("tv", link, dest, resp.get("filename"))
            written += 1
        except Exception as e:
            errors.append((link, str(e)))
            print(f"[ERR] {link}: {e}")
    print(f"Done. Written: {written}. Errors: {len(errors)}")
    return written, errors

# --- CLI wiring ---

def main():
    p = argparse.ArgumentParser(description="RealDebrid -> Jellyfin .strm helper")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add-movie")
    a.add_argument("--title", required=True)
    a.add_argument("--link", required=True)

    b = sub.add_parser("add-episode")
    b.add_argument("--show", required=True)
    b.add_argument("--season", required=True, type=int)
    b.add_argument("--episode", required=True, type=int)
    b.add_argument("--link", required=True)

    e = sub.add_parser("add-movie-links")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--links", help="Newline separated links", type=str)
    g.add_argument("--links-file", help="Path to file with newline-separated links", type=str)

    f = sub.add_parser("add-episode-links")
    f.add_argument("--show", required=True)
    f.add_argument("--season", required=True, type=int)
    g2 = f.add_mutually_exclusive_group(required=True)
    g2.add_argument("--links", help="Newline separated links", type=str)
    g2.add_argument("--links-file", help="Path to file with newline-separated links", type=str)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return

    if args.cmd == "add-movie":
        add_movie(args.title, args.link)
    elif args.cmd == "add-episode":
        add_episode(args.show, args.season, args.episode, args.link)
    elif args.cmd == "add-movie-links":
        if getattr(args, "links_file", None):
            with open(args.links_file, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
        else:
            lines = [ln.strip() for ln in args.links.splitlines() if ln.strip()]
        add_movie_links_from_list(lines)
    elif args.cmd == "add-episode-links":
        if getattr(args, "links_file", None):
            with open(args.links_file, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
        else:
            lines = [ln.strip() for ln in args.links.splitlines() if ln.strip()]
        add_episode_links_from_list(args.show, args.season, lines)

if __name__ == "__main__":
    main()
