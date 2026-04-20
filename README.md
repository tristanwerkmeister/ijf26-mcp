# IJF26 MCP

An MCP server that lets you search and browse transcripts from the **[International Journalism Festival 2026](https://www.journalismfestival.com/)** (Perugia, Italy — April 15–18, #ijf26), the festival's 20th edition.

All 161 sessions across 8 venues were livestreamed to [YouTube](https://www.youtube.com/channel/UClUtH75j6Bd7_Ty17jHVDPg). This tool downloads their auto-generated captions, stores them in a local SQLite database, and exposes them through four MCP tools you can use with Claude Desktop or any MCP-compatible client.

## Tools

| Tool | Description |
|------|-------------|
| `list_sessions` | Browse all 161 sessions grouped by venue (optional venue filter) |
| `search_transcripts` | Full-text search across all transcripts — supports phrases, AND/OR/NOT, prefix wildcards |
| `get_transcript` | Full transcript text for a session, with optional timestamps |
| `get_session_info` | Metadata and description for a session without the full text |

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- `yt-dlp` is installed automatically as a dependency

## Setup

### 1. Clone the repo

```sh
git clone https://github.com/YOUR_USERNAME/ijf26-mcp.git
cd ijf26-mcp
```

### 2. Download transcripts

This fetches all session videos from the 8 IJF26 YouTube playlists and downloads their captions. It takes a few minutes and only needs to be run once.

```sh
uv run python fetch_transcripts.py
```

You'll see progress like:

```
  Fetching Sala del Dottorato … → 15 videos
  ...
Total unique sessions: 161
[1/161] Explain your journalism … ✓ (110,199 chars)
...
Done. 127/161 sessions have transcripts.
```

Sessions without transcripts are private/deleted videos or Italian-language sessions without English captions.

### 3. Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add:

```json
{
  "mcpServers": {
    "ijf26": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/ijf26-mcp",
        "python",
        "/absolute/path/to/ijf26-mcp/server.py"
      ]
    }
  }
}
```

Replace `/absolute/path/to/ijf26-mcp` with the actual path. Then restart Claude Desktop.

### Other MCP clients

Run the server directly over stdio:

```sh
uv run python server.py
```

## Example prompts

- *"Which IJF26 sessions covered AI in journalism?"*
- *"Find sessions about press freedom and Gaza"*
- *"What did the session on transnational repression cover?"*
- *"List all sessions from Teatro del Pavone"*
- *"Search for sessions mentioning disinformation and Moldova"*

## Venues

The festival used 8 livestreamed venues:

- Auditorium San Francesco al Prato
- Sala Brugnoli
- Sala dei Notari
- Sala del Dottorato
- Sala delle Colonne
- Sala Raffaello
- Salone d'Onore
- Teatro del Pavone

## Updating

If new videos are added to the YouTube playlists, re-run the fetcher — already-cached transcripts are skipped:

```sh
uv run python fetch_transcripts.py
```

## Project structure

```
ijf26-mcp/
├── server.py            # MCP server (4 tools)
├── fetch_transcripts.py # One-time setup: downloads all transcripts into ijf26.db
├── pyproject.toml
├── uv.lock
└── .gitignore           # ijf26.db is excluded — build it locally
```

## License

MIT
