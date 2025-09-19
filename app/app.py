#!/usr/bin/env python3
"""
RDfin Flask GUI (complete)
- index: lists recently fetched movies/tv by reading .strm files under MEDIA_ROOT
- add-movie / add-episode: call rd_strm.py
- refresh-log: spawn background jobs to re-run links from a chosen daily log
  - movies: single add-movie-links job
  - tv: groups links by inferred (show,season) and spawns add-episode-links per group
- delete-log: delete a chosen daily log file

Notes:
- Background jobs are detached; stdout/stderr are discarded (no run logs saved).
- Temp link files are left on disk so background job can read them.
"""
from flask import Flask, render_template, request, redirect, url_for, flash
from pathlib import Path
from datetime import datetime
import subprocess, tempfile, shlex, os, re

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_this")

# Configuration (override via environment)
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/media"))
LOG_ROOT = Path(os.environ.get("LOG_ROOT", "/fetch_logs"))
RD_SCRIPT = os.environ.get("RD_SCRIPT", "/app/rd_strm.py")

# ---------- Helpers ----------

def find_strms(base: Path, limit: int = 200):
    """Return list of relative POSIX paths to .strm files under base (newest first)."""
    if not base.exists():
        return []
    files = list(base.rglob("*.strm"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:limit]:
        try:
            out.append(str(p.relative_to(MEDIA_ROOT).as_posix()))
        except Exception:
            out.append(str(p.as_posix()))
    return out

def list_logs(media_type: str):
    """Return list of daily log filenames for given media_type ('movies'|'tv'), newest first."""
    d = LOG_ROOT / media_type
    if not d.exists():
        return []
    files = [p.name for p in d.glob("*.log") if p.is_file()]
    files.sort(reverse=True)
    return files

def parse_log_entries(path: Path):
    """
    Parse log file lines and return list of dicts:
      { 'link': <url or None>, 'target': <target path or None>, 'raw': <original line> }
    Looks for tokens like 'link=' and 'target=' in pipe-separated lines (robust).
    """
    entries = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            parts = [p.strip() for p in ln.split("|")]
            link = None
            target = None
            for p in parts:
                lp = p.lower()
                if lp.startswith("link="):
                    link = p.partition("=")[2].strip()
                elif lp.startswith("target="):
                    target = p.partition("=")[2].strip()
            if not link:
                for p in parts[::-1]:
                    if p.startswith("http://") or p.startswith("https://"):
                        link = p
                        break
            entries.append({"link": link, "target": target, "raw": ln})
    return entries

def infer_show_and_season_from_target(target: str):
    """
    Try to infer (show_name, season_number) from a logged target path.
    Examples:
      /media/tv/Show Name/Season 01/Show Name - S01E01.strm
    Returns (show, season) or (None, None).
    """
    if not target:
        return None, None
    try:
        p = Path(target)
        parts = [part for part in p.parts if part and part != '/']
        lower_parts = [x.lower() for x in parts]
        if 'tv' in lower_parts:
            idx = lower_parts.index('tv')
            show = parts[idx + 1] if len(parts) > idx + 1 else None
            season_folder = parts[idx + 2] if len(parts) > idx + 2 else None
            if season_folder:
                m = re.search(r'(\d{1,2})', season_folder)
                season_num = int(m.group(1)) if m else None
            else:
                season_num = None
            return (show, season_num)
        # fallback: assume /Show/Season/filename
        if len(parts) >= 3:
            show = parts[-3]
            season_folder = parts[-2]
            m = re.search(r'(\d{1,2})', season_folder)
            season_num = int(m.group(1)) if m else None
            return (show, season_num)
    except Exception:
        pass
    return None, None

def infer_from_filename_for_season(fname: str):
    """
    Try to infer (show, season) from filename (like Show.Name.S01E02.mkv or Show - S01E02.mkv).
    Returns (show, season) or (None, None).
    """
    if not fname:
        return None, None
    base = Path(fname).stem
    # find SxxEyy pattern
    m = re.search(r'([Ss](\d{1,2})[Ee]\d{1,2})', base)
    if m:
        season_num = int(m.group(2))
        show_part = base.split(m.group(1))[0].strip(" -._.")
        show = show_part.replace(".", " ").strip() if show_part else None
        return (show, season_num)
    # pattern: Season 01 or Season.01
    m2 = re.search(r'[Ss]eason[ ._-]?(\d{1,2})', base, re.IGNORECASE)
    if m2:
        season_num = int(m2.group(1))
        show = base.split(m2.group(0))[0].replace(".", " ").strip() or None
        return (show, season_num)
    return None, None

def spawn_refresh_job_simple(media_type: str, logfile_name: str):
    """
    Create temporary links file(s) and spawn rd_strm.py background jobs.
    - movies: one add-movie-links job with a links-file
    - tv: group entries by inferred (show,season) and spawn add-episode-links per group
    Background jobs are detached; stdout/stderr are discarded. Temp files are left on disk.
    Returns a list summarising started jobs.
    """
    logpath = LOG_ROOT / media_type / logfile_name
    if not logpath.exists():
        raise FileNotFoundError("log not found")
    entries = parse_log_entries(logpath)
    if not entries:
        raise RuntimeError("no links found in log")

    started = []

    if media_type == "movies":
        links = [e["link"] for e in entries if e.get("link")]
        if not links:
            raise RuntimeError("no links found in movie log")
        tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, prefix="rdlinks_", suffix=".txt")
        try:
            for l in links:
                tmp.write(l + "\n")
            tmp.flush()
            tmp_path = Path(tmp.name)
        finally:
            tmp.close()
        cmd = ["python", RD_SCRIPT, "add-movie-links", "--links-file", str(tmp_path)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True)
        started.append({"type": "movies", "tmp": str(tmp_path), "cmd": " ".join(shlex.quote(x) for x in cmd)})
        return started

    # TV: group by inferred (show, season)
    groups = {}  # (show, season) -> [links]
    for e in entries:
        link = e.get("link")
        target = e.get("target")
        if not link:
            continue
        show, season = None, None
        if target:
            s, sn = infer_show_and_season_from_target(target)
            if s:
                show, season = s, sn
        if not show and target:
            try:
                fname = Path(target).name
                s, sn = infer_from_filename_for_season(fname)
                if s or sn:
                    show, season = s, sn
            except Exception:
                pass
        if not show:
            s, sn = infer_from_filename_for_season(link)
            if s or sn:
                show, season = s, sn
        if not show:
            show = "Unknown"
        if not season:
            season = 1
        key = (show, int(season))
        groups.setdefault(key, []).append(link)

    # spawn jobs per group
    for (show, season), links in groups.items():
        tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, prefix="rdlinks_", suffix=".txt")
        try:
            for l in links:
                tmp.write(l + "\n")
            tmp.flush()
            tmp_path = Path(tmp.name)
        finally:
            tmp.close()
        cmd = ["python", RD_SCRIPT, "add-episode-links", "--show", show, "--season", str(season), "--links-file", str(tmp_path)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True)
        started.append({"type": "tv", "show": show, "season": season, "tmp": str(tmp_path), "cmd": " ".join(shlex.quote(x) for x in cmd)})

    return started

# ---------- Routes ----------

@app.route("/")
def index():
    movies = find_strms(MEDIA_ROOT / "movies")
    tv = find_strms(MEDIA_ROOT / "tv")
    movie_logs = list_logs("movies")
    tv_logs = list_logs("tv")
    return render_template("index.html", movies=movies, tv=tv, movie_logs=movie_logs, tv_logs=tv_logs)

@app.route("/add-movie", methods=["POST"])
def add_movie():
    links_text = request.form.get("links", "")
    if not links_text.strip():
        flash("Please paste at least one link.", "danger")
        return redirect(url_for("index"))
    cmd = ["python", RD_SCRIPT, "add-movie-links", "--links", links_text]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        flash("Movie links submitted to RDfin for processing.", "success")
    else:
        flash("Error adding movie links: " + (proc.stderr or proc.stdout), "danger")
    return redirect(url_for("index"))

@app.route("/add-episode", methods=["POST"])
def add_episode():
    show = request.form.get("show", "").strip()
    season = request.form.get("season", "").strip()
    links_text = request.form.get("links", "")
    if not show or not season or not links_text.strip():
        flash("Show, season and links are required.", "danger")
        return redirect(url_for("index"))
    cmd = ["python", RD_SCRIPT, "add-episode-links", "--show", show, "--season", str(season), "--links", links_text]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        flash("Episode links submitted to RDfin for processing.", "success")
    else:
        flash("Error adding episode links: " + (proc.stderr or proc.stdout), "danger")
    return redirect(url_for("index"))

@app.route("/refresh-log", methods=["POST"])
def refresh_log():
    media_type = request.form.get("media_type")
    logfile = request.form.get("logfile")
    if media_type not in ("movies", "tv") or not logfile:
        flash("Invalid request", "danger")
        return redirect(url_for("index"))
    try:
        started = spawn_refresh_job_simple(media_type, logfile)
        parts = []
        for s in started:
            if s["type"] == "movies":
                parts.append("movies job started")
            else:
                parts.append(f"{s['show']} S{s['season']}")
        flash("Refresh started for: " + ", ".join(parts) + " — RDfin is processing in background.", "success")
    except FileNotFoundError:
        flash("Selected log file not found", "danger")
    except Exception as e:
        flash("Error starting refresh: " + str(e), "danger")
    return redirect(url_for("index"))

@app.route("/delete-log", methods=["POST"])
def delete_log():
    media_type = request.form.get("media_type")
    logfile = request.form.get("logfile")
    if media_type not in ("movies", "tv") or not logfile:
        flash("Invalid request", "danger")
        return redirect(url_for("index"))
    path = LOG_ROOT / media_type / logfile
    if not path.exists():
        flash("Log file not found", "danger")
        return redirect(url_for("index"))
    try:
        path.unlink()
        flash(f"Deleted log {logfile}", "success")
    except Exception as e:
        flash("Failed to delete log: " + str(e), "danger")
    return redirect(url_for("index"))

# ---------- Run ----------
if __name__ == "__main__":
    try:
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    app.run(host="0.0.0.0", port=3001)
