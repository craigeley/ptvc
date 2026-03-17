# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ptvc (Pro Tools Version Control) — a Python CLI that creates versioned snapshots of Pro Tools sessions via the PTSL gRPC API. It saves copies of `.ptx` session files into a `Versions/` folder alongside the session, with a human-readable markdown log and configurable version numbering.

The tool is aliased as `ptvc` in the user's `~/.zshrc`.

## Setup

```bash
pip3 install -e .
./generate_proto.sh /path/to/PTSL_SDK/Source
```

`pip install -e .` installs the package in editable mode with the `ptvc` console entry point. `generate_proto.sh` takes the path to the PTSL C++ SDK's `Source/` directory (containing `PTSL.proto`) and generates proto stubs into `src/ptvc/proto/`. The generated stubs are committed to the repo (required for Homebrew distribution).

## How It Works

Pro Tools runs a gRPC server on `localhost:31416` automatically when it launches. No middleware or extra services needed. The connection uses an insecure channel (no TLS).

**Connection flow:** Connect to gRPC → `RegisterConnection` (returns a `session_id`) → use `session_id` in all subsequent request headers.

**Snapshot flow:** `SaveSession` via PTSL → `shutil.copy2` the `.ptx` file into `Versions/` folder. We do NOT use `SaveSessionAs` because it creates a full session folder structure. Pro Tools does non-destructive editing, so the `.ptx` file is just a manifest of references to audio files — copying it alone is sufficient for versioning. The working session file always stays at the top level; snapshots are copies in the subfolder.

## Files

- **src/ptvc/cli.py** — CLI entry point with subcommands: `snapshot`, `log`, `info`, `config`
- **src/ptvc/client.py** — Thin gRPC client wrapper around PTSL. Sends JSON-bodied commands, handles response parsing.
- **src/ptvc/proto/** — Generated gRPC stubs (committed; required for distribution)
- **pyproject.toml** — Package metadata, dependencies, and `ptvc` console entry point
- **generate_proto.sh** — Generates Python proto stubs from the PTSL SDK's `.proto` file into `src/ptvc/proto/`
- **requirements.txt** — Legacy; dependencies now in pyproject.toml

## Per-Session Data

Each Pro Tools session's version data lives in a `Versions/` folder (name configurable) next to the session file:

- `.pt_versions.json` — Machine-readable index with config, session-level metadata, and per-version records
- `version_log.md` — Human-readable version history, regenerated on each snapshot

`find_version_dir()` scans sibling directories for an existing `.pt_versions.json` to find the versions folder regardless of its name.

## PTSL API Gotchas Discovered During Development

- **TaskStatus enum values:** 3 = Completed, 4 = Failed (not 2/3 as you might assume from zero-indexing)
- **`GetSessionPath` response:** Returns a dict `{"info": {...}, "path": "..."}` not a plain string — need to extract the `path` key
- **`GetSessionBitDepth` / `GetSessionAudioFormat` responses:** Use `current_setting` as the key, not `bit_depth`/`audio_format`
- **`GetTrackList` request format:** Uses `track_filter_list` with filter objects `[{"filter": "All", "is_inverted": false}]`, not a simple string enum
- **`GetClipList`:** Use `pagination_request: {"limit": 0, "offset": 0}` to get all clips. Response field is `clips` (not `clip_list`). Clip count may differ by 1 from Pro Tools' Export Session Info text — this is expected
- **`SaveSessionAs`:** Creates a full session folder, not just a `.ptx` file. Assertion errors occur with some path types (CloudStorage/Dropbox symlinks). We bypass this entirely by using `shutil.copy2` instead.
- **Version headers:** Must send `version` (2025), `version_minor` (10), `version_revision` (0) matching the SDK version. Mismatches cause `SDK_VersionMismatch` errors.
- **`CId_GetClipList`:** Only available since Pro Tools 2025.06

## Packaging

The project is structured as an installable Python package (`pip install -e .`) with a `ptvc` console entry point defined in `pyproject.toml`. Proto stubs are committed to the repo so the package can be distributed without requiring users to have the PTSL SDK. See memory file `project_homebrew_packaging.md` for the Homebrew tap roadmap and Avid licensing details.

## Licensing

The PTSL SDK is Avid proprietary (confidential). Key constraints from the license (Exhibit A):
- SDK cannot be distributed standalone, but can be incorporated in Licensed Products
- Licensed Products require an Avid certificate for distribution (contact audiosdk@avid.com)
- Must run locally — no server/cloud hosting for remote Pro Tools control
- Generated proto stubs can ship as part of a packaged product (executable form)
- Do NOT include the `.proto` source file, SDK source, or SDK docs in this repo
- Personal/internal use for improving Pro Tools workflows is explicitly permitted

See memory file `project_homebrew_packaging.md` for the full distribution roadmap.
