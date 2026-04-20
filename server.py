#!/usr/bin/env python3
"""
IJF26 MCP Server — search and browse transcripts from the
International Journalism Festival 2026 (Perugia, April 15-18).

Tools:
  list_sessions       — list all sessions (optionally filter by venue)
  search_transcripts  — full-text search across all transcripts
  get_transcript      — full transcript + metadata for one session
  get_session_info    — metadata only for one session
"""

import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "ijf26.db"

mcp = FastMCP(
    "IJF26 Sessions",
    instructions=(
        "Search and explore transcripts from the International Journalism Festival 2026 "
        "(Perugia, Italy, April 15-18 — the festival's 20th edition, #ijf26). "
        "161 sessions across 8 venues; 127 have transcripts. "
        "Use list_sessions to browse, search_transcripts to find sessions by topic or keyword, "
        "and get_transcript to read the full content of a session."
    ),
)

VENUES = [
    "Sala del Dottorato",
    "Salone d'Onore",
    "Teatro del Pavone",
    "Sala dei Notari",
    "Sala Brugnoli",
    "Sala delle Colonne",
    "Auditorium San Francesco",
    "Sala Raffaello",
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _check_db() -> str | None:
    if not DB_PATH.exists():
        return (
            "Database not found. Run `uv run python fetch_transcripts.py` first "
            "to download session transcripts."
        )
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    c.close()
    if n == 0:
        return "Database is empty. Run `uv run python fetch_transcripts.py` to populate it."
    return None


@mcp.tool()
def list_sessions(venue: str = "") -> str:
    """
    List all IJF26 sessions.

    Args:
        venue: Optional venue filter (partial match OK). Available venues:
               Sala del Dottorato, Salone d'Onore, Teatro del Pavone,
               Sala dei Notari, Sala Brugnoli, Sala delle Colonne,
               Auditorium San Francesco, Sala Raffaello.
    """
    err = _check_db()
    if err:
        return err

    conn = _conn()
    query = """
        SELECT s.video_id, s.title, s.duration, s.venue, s.url,
               CASE WHEN t.video_id IS NOT NULL THEN 1 ELSE 0 END AS has_transcript
        FROM sessions s
        LEFT JOIN transcripts t ON t.video_id = s.video_id
    """
    params: list = []
    if venue:
        query += " WHERE s.venue LIKE ?"
        params.append(f"%{venue}%")
    query += " ORDER BY s.venue, s.title"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return f"No sessions found{' for venue: ' + venue if venue else ''}."

    # Group by venue
    by_venue: dict[str, list] = {}
    for r in rows:
        by_venue.setdefault(r["venue"] or "Unknown", []).append(r)

    lines = [f"Found {len(rows)} sessions across {len(by_venue)} venue(s):\n"]
    for v_name, v_rows in by_venue.items():
        lines.append(f"## {v_name} ({len(v_rows)} sessions)")
        for r in v_rows:
            dur = f"{r['duration'] // 60}m" if r["duration"] else "?"
            flag = "✓" if r["has_transcript"] else "✗"
            lines.append(f"  {flag} [{r['video_id']}] {r['title']}  ({dur})")
            lines.append(f"     {r['url']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def search_transcripts(query: str, limit: int = 10) -> str:
    """
    Full-text search across all IJF26 session transcripts.

    Args:
        query: Search terms. Supports FTS5 syntax:
               - plain terms:   artificial intelligence
               - phrase:        "investigative journalism"
               - AND/OR/NOT:    Gaza AND ceasefire
               - prefix:        disinform*
        limit: Max results to return (default 10, max 50).
    """
    err = _check_db()
    if err:
        return err

    limit = min(max(1, limit), 50)
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT s.video_id, s.title, s.venue, s.url,
                   snippet(transcripts_fts, 1, '>>>', '<<<', '…', 40) AS snippet
            FROM transcripts_fts
            JOIN sessions s ON s.video_id = transcripts_fts.video_id
            WHERE transcripts_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        conn.close()
        return f"Search error: {e}\nTry simpler terms or quote phrases: \"your phrase here\""
    conn.close()

    if not rows:
        return f"No sessions found matching '{query}'."

    lines = [f"{len(rows)} session(s) matching '{query}':\n"]
    for r in rows:
        lines.append(
            f"• [{r['video_id']}] {r['title']}\n"
            f"  Venue: {r['venue'] or 'Unknown'}\n"
            f"  URL:   {r['url']}\n"
            f"  …{r['snippet']}…\n"
        )
    return "\n".join(lines)


@mcp.tool()
def get_transcript(video_id: str, include_timestamps: bool = False) -> str:
    """
    Get the full transcript for one IJF26 session.

    Args:
        video_id:           YouTube video ID shown in list_sessions or search results.
        include_timestamps: If True, prefix each segment with its start timestamp.
    """
    err = _check_db()
    if err:
        return err

    conn = _conn()
    session = conn.execute("SELECT * FROM sessions WHERE video_id=?", (video_id,)).fetchone()
    if not session:
        conn.close()
        return f"Session '{video_id}' not found. Use list_sessions to browse available IDs."

    transcript = conn.execute(
        "SELECT text, segments FROM transcripts WHERE video_id=?", (video_id,)
    ).fetchone()
    conn.close()

    dur_min = session["duration"] // 60 if session["duration"] else "?"
    header = (
        f"# {session['title']}\n"
        f"Venue:    {session['venue'] or 'Unknown'}\n"
        f"Duration: {dur_min} min\n"
        f"URL:      {session['url']}\n\n"
    )

    if not transcript:
        return header + "No transcript available for this session."

    if not include_timestamps:
        return header + transcript["text"]

    segments = json.loads(transcript["segments"])
    lines = [f"[{s['start']}] {s['text']}" for s in segments]
    return header + "\n".join(lines)


@mcp.tool()
def get_session_info(video_id: str) -> str:
    """
    Get metadata for one IJF26 session (no transcript text).

    Args:
        video_id: YouTube video ID.
    """
    err = _check_db()
    if err:
        return err

    conn = _conn()
    session = conn.execute("SELECT * FROM sessions WHERE video_id=?", (video_id,)).fetchone()
    if not session:
        conn.close()
        return f"Session '{video_id}' not found."

    row = conn.execute(
        "SELECT LENGTH(text), LENGTH(text) - LENGTH(REPLACE(text,' ','')) + 1 "
        "FROM transcripts WHERE video_id=?",
        (video_id,),
    ).fetchone()
    conn.close()

    has_transcript = row is not None
    word_count = row[1] if row else 0

    info = (
        f"Title:      {session['title']}\n"
        f"Video ID:   {session['video_id']}\n"
        f"Venue:      {session['venue'] or 'Unknown'}\n"
        f"Duration:   {session['duration'] // 60 if session['duration'] else '?'} min\n"
        f"URL:        {session['url']}\n"
        f"Thumbnail:  {session['thumbnail']}\n"
        f"Transcript: {'yes (~' + str(word_count) + ' words)' if has_transcript else 'not available'}\n"
    )
    if session["description"]:
        desc = session["description"][:600]
        if len(session["description"]) > 600:
            desc += "…"
        info += f"\nDescription:\n{desc}"
    return info


if __name__ == "__main__":
    mcp.run()
