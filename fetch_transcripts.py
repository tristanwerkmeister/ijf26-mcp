#!/usr/bin/env python3
"""
Fetch IJF26 session videos from YouTube venue playlists, download transcripts,
store in SQLite. Run once to populate the database before starting the MCP server.
"""

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "ijf26.db"

# One playlist per venue/room
IJF26_PLAYLISTS = {
    "Sala del Dottorato":          "PLKD4nfGTHZ_MukdvzcyItchBOMBgN_KTk",
    "Salone d'Onore":              "PLKD4nfGTHZ_MgchWaVKXTvqSKss5sgdYv",
    "Teatro del Pavone":           "PLKD4nfGTHZ_OHONXZIC6QjukHBWtZHNjC",
    "Sala dei Notari":             "PLKD4nfGTHZ_PhiJxfia307E8p2iSjLZn5",
    "Sala Brugnoli":               "PLKD4nfGTHZ_PbveFc7zBjH6U8PpksCm7h",
    "Sala delle Colonne":          "PLKD4nfGTHZ_NzonY0iX7VDA9yLjYMvI26",
    "Auditorium San Francesco":    "PLKD4nfGTHZ_NaF3di3Tmn7NCvu2N42I-I",
    "Sala Raffaello":              "PLKD4nfGTHZ_OMpRrkVFHlE3aI0XeRfZIL",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            video_id    TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT,
            upload_date TEXT,
            duration    INTEGER,
            url         TEXT,
            thumbnail   TEXT,
            venue       TEXT
        );
        CREATE TABLE IF NOT EXISTS transcripts (
            video_id    TEXT PRIMARY KEY REFERENCES sessions(video_id),
            text        TEXT NOT NULL,
            segments    TEXT  -- JSON array of {start, end, text}
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts
            USING fts5(video_id UNINDEXED, text, content=transcripts, content_rowid=rowid);
        CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
            INSERT INTO transcripts_fts(rowid, video_id, text)
                VALUES (new.rowid, new.video_id, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
            INSERT INTO transcripts_fts(transcripts_fts, rowid, video_id, text)
                VALUES('delete', old.rowid, old.video_id, old.text);
        END;
    """)
    conn.commit()


def fetch_playlist_videos(venue: str, playlist_id: str) -> list[dict]:
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s\t%(duration)s\t%(upload_date)s\t%(description)s",
        "--no-warnings",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    videos = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 4)
        if len(parts) < 2:
            continue
        vid_id = parts[0].strip()
        title  = parts[1].strip()
        duration = int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else 0
        upload_date = parts[3].strip() if len(parts) > 3 else ""
        description = parts[4].strip() if len(parts) > 4 else ""
        if not vid_id or vid_id.startswith("ERROR"):
            continue
        videos.append({
            "video_id":    vid_id,
            "title":       title,
            "description": description,
            "upload_date": upload_date if upload_date != "NA" else "",
            "duration":    duration,
            "url":         f"https://www.youtube.com/watch?v={vid_id}",
            "thumbnail":   f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
            "venue":       venue,
        })
    return videos


def parse_vtt(vtt_text: str) -> tuple[str, list[dict]]:
    """Parse WebVTT into (full_text, segments)."""
    segments: list[dict] = []
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines) and not re.match(r"\d{2}:\d{2}", lines[i]):
        i += 1

    current_start = current_end = None
    current_text: list[str] = []

    def flush():
        nonlocal current_start, current_end, current_text
        if current_text and current_start is not None:
            text = " ".join(current_text).strip()
            text = re.sub(r"<[^>]+>", "", text)  # strip HTML tags
            if text:
                segments.append({"start": current_start, "end": current_end, "text": text})
        current_start = current_end = None
        current_text = []

    for line in lines[i:]:
        ts = re.match(
            r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})", line
        )
        if ts:
            flush()
            current_start, current_end = ts.group(1), ts.group(2)
        elif line.strip() and not line.strip().isdigit() and current_start:
            current_text.append(line.strip())

    flush()

    # Deduplicate consecutive identical lines (YouTube auto-caption artifact)
    deduped = [segments[0]] if segments else []
    for seg in segments[1:]:
        if seg["text"] != deduped[-1]["text"]:
            deduped.append(seg)

    full_text = " ".join(s["text"] for s in deduped)
    return full_text, deduped


def download_transcript(video_id: str) -> tuple[str, list[dict]] | None:
    import tempfile
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        for extra in [["--sub-langs", "en.*"], []]:
            cmd = [
                "yt-dlp",
                "--write-subs", "--write-auto-subs",
                "--sub-format", "vtt",
                "--skip-download", "--no-warnings",
                "-o", f"{tmpdir}/%(id)s",
                url,
            ] + extra
            subprocess.run(cmd, capture_output=True, text=True)
            vtt_files = list(Path(tmpdir).glob("*.vtt"))
            if vtt_files:
                break
        if not vtt_files:
            return None
        manual = [f for f in vtt_files if "auto" not in f.name]
        chosen = (manual or vtt_files)[0]
        return parse_vtt(chosen.read_text(encoding="utf-8", errors="replace"))


def run():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    all_videos: list[dict] = []
    for venue, playlist_id in IJF26_PLAYLISTS.items():
        print(f"  Fetching {venue} …", flush=True)
        videos = fetch_playlist_videos(venue, playlist_id)
        print(f"    → {len(videos)} videos", flush=True)
        all_videos.extend(videos)

    # Deduplicate (same video can appear in multiple playlists)
    seen: set[str] = set()
    unique_videos = []
    for v in all_videos:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            unique_videos.append(v)

    print(f"\nTotal unique sessions: {len(unique_videos)}", flush=True)

    conn.executemany(
        """INSERT OR IGNORE INTO sessions
           (video_id, title, description, upload_date, duration, url, thumbnail, venue)
           VALUES (:video_id,:title,:description,:upload_date,:duration,:url,:thumbnail,:venue)""",
        unique_videos,
    )
    conn.commit()

    total = len(unique_videos)
    for i, v in enumerate(unique_videos, 1):
        vid = v["video_id"]
        if conn.execute("SELECT 1 FROM transcripts WHERE video_id=?", (vid,)).fetchone():
            print(f"[{i}/{total}] {v['title'][:55]} — skip (cached)")
            continue
        print(f"[{i}/{total}] {v['title'][:55]} … ", end="", flush=True)
        result = download_transcript(vid)
        if result:
            full_text, segments = result
            conn.execute(
                "INSERT OR REPLACE INTO transcripts (video_id,text,segments) VALUES (?,?,?)",
                (vid, full_text, json.dumps(segments)),
            )
            conn.commit()
            print(f"✓ ({len(full_text):,} chars)")
        else:
            print("✗ no transcript")

    done = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    print(f"\nDone. {done}/{total} sessions have transcripts.")
    conn.close()


if __name__ == "__main__":
    run()
