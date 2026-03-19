#!/usr/bin/env python3
"""
Pro Tools Session Version Control

Creates versioned snapshots of Pro Tools sessions with human-readable
markdown logs. In live mode (default), each snapshot advances Pro Tools
to the next version via SaveSessionAs and archives the previous .ptx.

Usage:
    ptvc snapshot "Added background vocals, revised chorus"
    ptvc log
    ptvc info
    ptvc config --mode archive
    ptvc config --start-number 0.00 --increment-by 0.05
    ptvc config --prefix "mix-"
"""

import argparse

from ptvc import __version__
from decimal import Decimal, ROUND_DOWN
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .client import PTSLClient

# Stored alongside the session folder
DEFAULT_VERSION_DIR_NAME = "Versions"
VERSION_LOG_NAME = "version_log.md"
VERSION_INDEX_NAME = ".pt_versions.json"

COMPANY_NAME = "PTVersionControl"
APP_NAME = "pt_snapshot"

# Default config
DEFAULT_CONFIG = {
    "start_number": "1",
    "increment_by": "1",
    "prefix": " v",
    "zero_pad": 3,        # number of digits to pad (e.g., 3 → v001)
    "folder_name": DEFAULT_VERSION_DIR_NAME,
    "date_format": "",    # strftime format string; empty = numeric mode
    "mode": "live",       # "live" = SaveSessionAs + move old .ptx to Versions/; "archive" = copy .ptx only
    "text_export": False,  # export session info as text with each snapshot
    "text_format": "UTF8",  # UTF8, TextEdit, or Excel
}

# Global templates file
TEMPLATES_FILE = Path.home() / ".ptvc_templates.yaml"

# Keys from DEFAULT_CONFIG that are valid in templates
TEMPLATE_KEYS = set(DEFAULT_CONFIG.keys())


def _format_yaml_value(val):
    """Format a Python value as a YAML-friendly string for comments."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, str):
        return f'"{val}"' if val else '""'
    return str(val)


def _templates_header():
    """Build the comment header for the templates file."""
    lines = [
        "# ptvc user templates",
        "#",
        "# Each template is a named set of config settings that can be applied",
        "# to any session with:  ptvc config --template <name>",
        "#",
        "# Templates only need to include the settings you want to change.",
        "# Any omitted settings will keep their current value (or the default).",
        "#",
        "# Available settings and their defaults:",
    ]
    for key, val in DEFAULT_CONFIG.items():
        lines.append(f"#   {key}: {_format_yaml_value(val)}")
    lines += [
        "#",
        "# Example:",
        "#",
        "# templates:",
        '#   podcast:',
        '#     prefix: " ep"',
        "#     zero_pad: 2",
        "#     mode: archive",
        "#     text_export: true",
        "#",
        "",
    ]
    return "\n".join(lines) + "\n"


def load_templates():
    """Load the global templates file, seeding it with defaults if it doesn't exist."""
    if not TEMPLATES_FILE.exists():
        seed_templates_file()
    with open(TEMPLATES_FILE, "r") as f:
        data = yaml.safe_load(f)
    return data.get("templates", {}) if data else {}


def save_templates(templates):
    """Save templates back to the global file, preserving the header."""
    header = _templates_header()
    body = yaml.dump({"templates": templates}, default_flow_style=False, sort_keys=False)
    with open(TEMPLATES_FILE, "w") as f:
        f.write(header + body)


def seed_templates_file():
    """Create the templates file with comments showing defaults and an example."""
    header = _templates_header()
    with open(TEMPLATES_FILE, "w") as f:
        f.write(header + "templates: {}\n")


def connect():
    """Connect to Pro Tools and register."""
    client = PTSLClient()
    try:
        session_id = client.register_connection(COMPANY_NAME, APP_NAME)
        print(f"Connected to Pro Tools (session: {session_id[:8]}...)")
    except Exception as e:
        print(f"Error: Could not connect to Pro Tools.\n"
              f"Make sure Pro Tools is running and a session is open.\n\n{e}")
        sys.exit(1)
    return client


def get_session_info(client):
    """Gather metadata about the current session."""
    name = client.get_session_name()
    path = client.get_session_path()

    if not name or not path:
        print("Error: No session appears to be open in Pro Tools.")
        sys.exit(1)

    info = {
        "session_name": name,
        "session_path": path,
    }

    # Get track count
    try:
        track_data = client.get_track_list()
        tracks = track_data.get("track_list", [])
        info["track_count"] = len(tracks)
        info["track_names"] = [t.get("name", "") for t in tracks]
    except Exception:
        info["track_count"] = "unknown"
        info["track_names"] = []

    # Get clip count
    try:
        info["clip_count"] = client.get_clip_count()
    except Exception:
        info["clip_count"] = "unknown"

    return info


def get_version_dir(session_path, folder_name=None):
    """Return the versions directory, sibling to the session folder."""
    session_folder = Path(session_path).parent
    return session_folder / (folder_name or DEFAULT_VERSION_DIR_NAME)


def load_version_index(version_dir):
    """Load the JSON index of all versions."""
    index_path = version_dir / VERSION_INDEX_NAME
    if index_path.exists():
        with open(index_path, "r") as f:
            return json.load(f)
    return {"config": dict(DEFAULT_CONFIG), "versions": []}


def find_version_dir(session_path):
    """Find the version dir for a session, checking for an existing index first.

    Scans sibling directories for one containing our index file. If none found,
    returns the default location.
    """
    session_folder = Path(session_path).parent
    # Check if any sibling folder already has our index
    for entry in session_folder.iterdir():
        if entry.is_dir() and (entry / VERSION_INDEX_NAME).exists():
            return entry
    return session_folder / DEFAULT_VERSION_DIR_NAME


def save_version_index(version_dir, index):
    """Save the JSON index."""
    index_path = version_dir / VERSION_INDEX_NAME
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def get_config(index):
    """Get the numbering config, falling back to defaults."""
    stored = index.get("config", {})
    config = dict(DEFAULT_CONFIG)
    config.update(stored)
    return config


def format_version_number(number, config):
    """Format a Decimal version number according to the config.

    Examples:
        Decimal("1"), prefix="v", zero_pad=3    → "v001"
        Decimal("0.05"), prefix="", zero_pad=0  → "0.05"
        Decimal("1.10"), prefix="v", zero_pad=0 → "v1.10"
    """
    prefix = config.get("prefix", "")

    # Determine decimal places from the increment
    increment = Decimal(config["increment_by"])
    # e.g., 0.05 has exponent -2, so 2 decimal places
    decimal_places = max(0, -increment.as_tuple().exponent)

    if decimal_places == 0:
        # Integer mode: use zero-padding
        pad = config.get("zero_pad", 3)
        num_str = str(int(number)).zfill(pad) if pad > 0 else str(int(number))
    else:
        # Decimal mode: format with fixed decimal places
        fmt = f"{{:.{decimal_places}f}}"
        num_str = fmt.format(number)

    return f"{prefix}{num_str}"


def format_date_version(config, existing_versions, timestamp=None):
    """Generate a date-based version tag with an auto-incrementing counter.

    Uses config["date_format"] as a strftime format string. If multiple
    snapshots produce the same date string, appends -2, -3, etc.

    Returns (version_tag, date_base) where date_base is the raw strftime output.
    """
    if timestamp is None:
        timestamp = datetime.now()

    prefix = config.get("prefix", "")
    date_str = timestamp.strftime(config["date_format"])
    base_tag = f"{prefix}{date_str}"

    # Count how many existing versions share this date base
    count = 0
    for v in existing_versions:
        tag = v.get("version_tag", "")
        if tag == base_tag or tag.startswith(base_tag + "-"):
            count += 1

    if count == 0:
        return base_tag, date_str
    else:
        return f"{base_tag}-{count + 1}", date_str


def get_base_session_name(session_name, config, index):
    """Strip a version suffix from the session name if present.

    In live mode, Pro Tools switches to sessions named like "Song v002".
    We need to recover the base name "Song" for building the next version name.

    Strategy:
    1. Check if the name ends with any known version tag from the index
    2. Fall back to a regex built from the config's prefix + number format
    """
    # Check known version tags (most recent first)
    for v in reversed(index.get("versions", [])):
        tag = v.get("version_tag", "")
        if tag and session_name.endswith(tag):
            return session_name[:-len(tag)]

    # Regex fallback based on config format
    prefix = re.escape(config.get("prefix", ""))
    if config.get("date_format"):
        # Date tags: prefix + non-whitespace chars, optional -N counter
        pattern = f"{prefix}\\S+(?:-\\d+)?$"
    else:
        # Numeric tags: prefix + digits with optional decimal part
        pattern = f"{prefix}\\d+(?:\\.\\d+)?$"

    stripped = re.sub(pattern, "", session_name)
    return stripped if stripped else session_name


def next_version_number(index):
    """Calculate the next version number from config and existing versions."""
    config = get_config(index)
    start = Decimal(config["start_number"])
    increment = Decimal(config["increment_by"])

    # Find the last numbered version (skip --tag one-offs)
    for v in reversed(index["versions"]):
        if v.get("version_number") is not None:
            last_num = Decimal(str(v["version_number"]))
            return last_num + increment

    return start


def cmd_snapshot(args):
    """Create a versioned snapshot of the current session."""
    client = connect()
    info = get_session_info(client)

    session_name = info["session_name"]
    session_path = info["session_path"]
    version_dir = find_version_dir(session_path)

    # Load or create index
    version_dir.mkdir(parents=True, exist_ok=True)
    index = load_version_index(version_dir)
    config = get_config(index)

    # Determine version tag
    if args.bump:
        try:
            bump_num = Decimal(args.bump)
        except Exception:
            print(f"Error: '{args.bump}' is not a valid version number.")
            sys.exit(1)
        version_num_decimal = bump_num
        version_tag = format_version_number(bump_num, config)
        version_num = str(bump_num)
    elif args.tag:
        version_tag = args.tag
        version_num = None
    elif config.get("date_format"):
        version_tag, version_num = format_date_version(
            config, index["versions"]
        )
    else:
        version_num_decimal = next_version_number(index)
        version_tag = format_version_number(version_num_decimal, config)
        version_num = str(version_num_decimal)

    timestamp = datetime.now()
    notes = args.notes

    live_mode = config.get("mode", "live") == "live"

    # In live mode, strip any existing version suffix from the session name
    # so we don't stack tags (e.g., "Song v001 v002")
    if live_mode:
        base_name = get_base_session_name(session_name, config, index)
    else:
        base_name = session_name

    # Snapshot is just a copy of the .ptx file in the Versions folder
    snapshot_filename = f"{base_name}{version_tag}"
    version_dir.mkdir(parents=True, exist_ok=True)

    # Save current session first
    print(f"Saving current session...")
    client.save_session()

    next_session_name = None
    source_ptx = Path(session_path)

    # --tag is a one-off label: just copy the file without advancing,
    # even in live mode (it shouldn't affect the versioning sequence)
    if live_mode and not args.tag:
        # Live mode: advance first, then move the old .ptx into Versions/
        # 1. Calculate next version
        if config.get("date_format"):
            next_version_tag, _ = format_date_version(
                config, index["versions"] + [{"version_tag": version_tag}]
            )
        elif args.bump:
            next_num = Decimal(args.bump) + Decimal(config["increment_by"])
            next_version_tag = format_version_number(next_num, config)
        else:
            next_num = Decimal(version_num) + Decimal(config["increment_by"])
            next_version_tag = format_version_number(next_num, config)

        next_session_name = f"{base_name}{next_version_tag}"

        # 2. SaveSessionAs to advance (PT switches to the new session)
        session_folder = Path(session_path).parent
        # Trailing slash is required — Pro Tools' path parser asserts without it
        session_location = str(session_folder) + "/"

        print(f"Advancing to: {next_session_name}")
        client.save_session_as(next_session_name, session_location)

        # 3. Move the old .ptx into Versions/ (or root if --root)
        if args.root:
            dest_dir = Path(session_path).parent
        else:
            dest_dir = version_dir
        dest_ptx = dest_dir / f"{snapshot_filename}.ptx"
        print(f"Archiving: {snapshot_filename}.ptx")
        shutil.move(str(source_ptx), str(dest_ptx))
    else:
        # Archive mode (or --tag one-off): copy .ptx without advancing
        if args.root:
            dest_dir = Path(session_path).parent
        else:
            dest_dir = version_dir
        print(f"Creating snapshot: {snapshot_filename}.ptx")
        dest_ptx = dest_dir / f"{snapshot_filename}.ptx"
        shutil.copy2(str(source_ptx), str(dest_ptx))

    # Export session info as text
    do_export = config.get("text_export", True)
    if args.no_text_export:
        do_export = False
    if do_export:
        text_format = config.get("text_format", "UTF8")
        session_folder = Path(session_path).parent
        export_path = str(session_folder / f"{session_name} Session Info.txt")
        print(f"Exporting session info: {session_name} Session Info.txt")
        try:
            client.export_session_info_as_text(export_path, text_format=text_format)
        except Exception as e:
            print(f"  Warning: text export failed ({e})")

    # Store session-level metadata once
    if "session_info" not in index:
        index["session_info"] = {
            "sample_rate": client.get_session_sample_rate(),
            "bit_depth": client.get_session_bit_depth(),
            "audio_format": client.get_session_audio_format(),
        }

    # Build version record
    record = {
        "version_number": version_num,
        "version_tag": version_tag,
        "timestamp": timestamp.isoformat(),
        "notes": notes,
        "session_name": session_name,
        "snapshot_filename": snapshot_filename,
        "snapshot_path": str(dest_ptx),
        "track_count": info["track_count"],
        "clip_count": info["clip_count"],
    }

    index["versions"].append(record)
    save_version_index(version_dir, index)

    # Update the markdown log
    update_version_log(version_dir, index)

    client.close()

    print(f"\nSnapshot created successfully!")
    print(f"  Version: {version_tag}")
    print(f"  File: {snapshot_filename}.ptx")
    if next_session_name:
        print(f"  Now working in: {next_session_name}")
    if notes:
        print(f"  Notes: {notes}")


def update_version_log(version_dir, index):
    """Write/overwrite the human-readable markdown version log."""
    log_path = version_dir / VERSION_LOG_NAME

    if not index["versions"]:
        return

    session_name = index["versions"][0]["session_name"]
    config = get_config(index)

    lines = [
        f"# {session_name} — Version History",
        "",
    ]

    # Most recent first
    for v in reversed(index["versions"]):
        ts = datetime.fromisoformat(v["timestamp"])
        date_str = ts.strftime("%Y-%m-%d %H:%M")
        filename = v.get('snapshot_filename', v.get('snapshot_name', ''))

        lines.append(f"{v['version_tag']} — {date_str}")
        if v.get("notes"):
            lines.append(f"  {v['notes']}")
        lines.append(f"  {v.get('track_count', '?')} tracks, {v.get('clip_count', '?')} clips | {filename}.ptx")
        lines.append("")

    with open(log_path, "w") as f:
        f.write("\n".join(lines))


def cmd_log(args):
    """Display the version history."""
    client = connect()
    info = get_session_info(client)
    client.close()

    version_dir = find_version_dir(info["session_path"])
    log_path = version_dir / VERSION_LOG_NAME

    if not log_path.exists():
        print("No version history found for this session.")
        print("Run 'pt_snapshot.py snapshot' to create your first snapshot.")
        return

    print(log_path.read_text())


def cmd_info(args):
    """Show info about the current session (without creating a snapshot)."""
    client = connect()
    info = get_session_info(client)
    client.close()

    print(f"Session: {info['session_name']}")
    print(f"Path:    {info['session_path']}")
    print(f"Tracks:  {info['track_count']}")
    print(f"Clips:   {info['clip_count']}")

    version_dir = find_version_dir(info["session_path"])
    index = load_version_index(version_dir)
    config = get_config(index)
    num_versions = len(index.get("versions", []))

    date_fmt = config.get("date_format", "")

    print(f"\nVersions folder: {version_dir.name}/")
    if date_fmt:
        print(f"Versioning: date-based ({date_fmt}), prefix=\"{config['prefix']}\"")
    else:
        print(f"Versioning: numeric, start={config['start_number']}, "
              f"increment={config['increment_by']}, prefix=\"{config['prefix']}\"")

    if num_versions:
        latest = index["versions"][-1]
        print(f"Versions: {num_versions} snapshots")
        print(f"Latest:   {latest['version_tag']} ({latest['timestamp'][:16]})")
        if date_fmt:
            next_tag, _ = format_date_version(config, index["versions"])
            print(f"Next:     {next_tag}")
        else:
            next_num = next_version_number(index)
            next_tag = format_version_number(next_num, config)
            print(f"Next:     {next_tag}")
    else:
        print("No snapshots yet.")


def cmd_config(args):
    """View or update the versioning config for the current session."""
    client = connect()
    info = get_session_info(client)
    client.close()

    version_dir = find_version_dir(info["session_path"])
    version_dir.mkdir(parents=True, exist_ok=True)
    index = load_version_index(version_dir)

    if "config" not in index:
        index["config"] = dict(DEFAULT_CONFIG)

    changed = False

    # Apply template first (individual flags can override)
    if args.template is not None:
        templates = load_templates()
        name = args.template
        if name not in templates:
            available = ", ".join(sorted(templates.keys())) if templates else "(none)"
            print(f"Error: No template named '{name}'.")
            print(f"Available templates: {available}")
            sys.exit(1)
        template = templates[name]
        for key, val in template.items():
            if key not in TEMPLATE_KEYS:
                print(f"Warning: Ignoring unknown template key '{key}'.")
                continue
            index["config"][key] = val
        changed = True
        print(f"Applied template: {name}")

    if args.start_number is not None:
        # Validate it's a valid number
        try:
            Decimal(args.start_number)
        except Exception:
            print(f"Error: '{args.start_number}' is not a valid number.")
            sys.exit(1)
        index["config"]["start_number"] = args.start_number
        changed = True

    if args.increment_by is not None:
        try:
            inc = Decimal(args.increment_by)
            if inc <= 0:
                raise ValueError()
        except Exception:
            print(f"Error: '{args.increment_by}' is not a valid positive number.")
            sys.exit(1)
        index["config"]["increment_by"] = args.increment_by
        changed = True

    if args.prefix is not None:
        index["config"]["prefix"] = args.prefix
        changed = True

    if args.zero_pad is not None:
        if args.zero_pad < 0:
            print("Error: --zero-pad must be >= 0.")
            sys.exit(1)
        index["config"]["zero_pad"] = args.zero_pad
        changed = True

    if args.folder_name is not None:
        new_name = args.folder_name.strip()
        if not new_name:
            print("Error: folder name cannot be empty.")
            sys.exit(1)
        session_folder = Path(info["session_path"]).parent
        new_dir = session_folder / new_name
        if new_dir != version_dir:
            if version_dir.exists() and any(version_dir.iterdir()):
                if new_dir.exists():
                    print(f"Error: Cannot rename '{version_dir.name}/' to '{new_name}/' — target already exists.")
                    sys.exit(1)
                version_dir.rename(new_dir)
                print(f"Renamed folder: {version_dir.name}/ → {new_name}/")
                version_dir = new_dir
            else:
                version_dir = new_dir
                version_dir.mkdir(parents=True, exist_ok=True)
        index["config"]["folder_name"] = new_name
        changed = True

    if args.date_format is not None:
        # Validate the format string by trying it
        fmt = args.date_format
        if fmt:
            try:
                datetime.now().strftime(fmt)
            except ValueError as e:
                print(f"Error: Invalid strftime format: {e}")
                sys.exit(1)
        index["config"]["date_format"] = fmt
        changed = True
        if fmt:
            print(f"Switched to date-based versioning: {fmt}")
        else:
            print("Switched back to numeric versioning.")

    if args.mode is not None:
        index["config"]["mode"] = args.mode
        changed = True

    if args.text_export is not None:
        index["config"]["text_export"] = (args.text_export == "on")
        changed = True

    if args.text_format is not None:
        index["config"]["text_format"] = args.text_format
        changed = True

    if changed:
        save_version_index(version_dir, index)
        print("Config updated.\n")

    # Show current config
    config = get_config(index)
    date_fmt = config.get("date_format", "")

    mode = config.get("mode", "archive")
    print(f"Session:      {info['session_name']}")
    print(f"Folder:       {config['folder_name']}/")
    print(f"Snapshot mode: {mode}")
    if date_fmt:
        print(f"Mode:         date-based")
        print(f"Date format:  {date_fmt}")
        print(f"Prefix:       \"{config['prefix']}\"")
    else:
        print(f"Mode:         numeric")
        print(f"Start number: {config['start_number']}")
        print(f"Increment by: {config['increment_by']}")
        print(f"Prefix:       \"{config['prefix']}\"")
        print(f"Zero pad:     {config['zero_pad']} digits")

    text_export = config.get("text_export", True)
    print(f"Text export:  {'on' if text_export else 'off'}", end="")
    if text_export:
        print(f" ({config.get('text_format', 'UTF8')})")
    else:
        print()

    # Show preview of what the next few versions would look like
    print(f"\nPreview of next versions:")
    if date_fmt:
        now = datetime.now()
        prefix = config.get("prefix", "")
        date_str = now.strftime(date_fmt)
        base_tag = f"{prefix}{date_str}"
        print(f"  {base_tag}  (next)")
        print(f"  {base_tag}-2")
        print(f"  {base_tag}-3")
        print(f"  {base_tag}-4")
        print(f"  {base_tag}-5")
    else:
        start = Decimal(config["start_number"])
        inc = Decimal(config["increment_by"])

        # If there are existing versions, start from the next one
        if index["versions"]:
            last = Decimal(str(index["versions"][-1]["version_number"]))
            start = last + inc

        for i in range(5):
            num = start + (inc * i)
            tag = format_version_number(num, config)
            marker = " (next)" if i == 0 else ""
            print(f"  {tag}{marker}")


def cmd_template(args):
    """Manage global config templates."""
    action = args.action

    if action == "init":
        if TEMPLATES_FILE.exists():
            print(f"Templates file already exists: {TEMPLATES_FILE}")
            print("Open it in any text editor to add or modify templates.")
        else:
            seed_templates_file()
            print(f"Created templates file: {TEMPLATES_FILE}")
            print("Open it in any text editor to get started — it includes")
            print("all available settings and an example template.")
        return

    elif action == "save":
        client = connect()
        info = get_session_info(client)
        client.close()

        version_dir = find_version_dir(info["session_path"])
        index = load_version_index(version_dir)
        config = get_config(index)

        # Build a partial config: only include non-default values
        template = {}
        for key, default_val in DEFAULT_CONFIG.items():
            if config[key] != default_val:
                template[key] = config[key]

        if not template:
            print("Current session config matches all defaults — nothing to save.")
            print("Customize your session config first with: ptvc config --<setting> <value>")
            return

        templates = load_templates()
        name = args.name
        verb = "Updated" if name in templates else "Saved"
        templates[name] = template
        save_templates(templates)
        print(f"{verb} template '{name}' in {TEMPLATES_FILE}")
        for key, val in template.items():
            print(f"  {key}: {val}")

    elif action == "list":
        templates = load_templates()
        if not templates:
            print(f"No templates saved yet.")
            print(f"Use 'ptvc template save <name>' to save your current session config as a template.")
            return
        print("Saved templates:\n")
        for name, settings in templates.items():
            summary = ", ".join(f"{k}={v}" for k, v in settings.items())
            print(f"  {name}: {summary}")

    elif action == "show":
        templates = load_templates()
        name = args.name
        if name not in templates:
            print(f"Error: No template named '{name}'.")
            sys.exit(1)
        print(f"Template: {name}\n")
        for key, val in templates[name].items():
            print(f"  {key}: {val}")
        print(f"\n(All other settings use defaults when applied.)")

    elif action == "delete":
        templates = load_templates()
        name = args.name
        if name not in templates:
            print(f"Error: No template named '{name}'.")
            sys.exit(1)
        del templates[name]
        save_templates(templates)
        print(f"Deleted template '{name}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Pro Tools session version control via PTSL"
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"ptvc {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # snapshot
    snap_parser = subparsers.add_parser(
        "snapshot", aliases=["s"], help="Create a versioned snapshot of the current session"
    )
    snap_parser.add_argument(
        "notes", nargs="?", default="",
        help="Version notes (e.g., 'Added background vocals')"
    )
    snap_parser.add_argument(
        "--tag", "-t", default="",
        help="Custom version tag (overrides auto-numbering for this snapshot)"
    )
    snap_parser.add_argument(
        "--bump", "-b", default="",
        help="Jump to a specific version number (e.g., '1.00'); future versions increment from here"
    )
    snap_parser.add_argument(
        "--no-text-export", action="store_true", default=False,
        help="Skip the session info text export for this snapshot"
    )
    snap_parser.add_argument(
        "--root", action="store_true", default=False,
        help="Save snapshot in the session's top-level folder instead of the Versions folder"
    )
    snap_parser.set_defaults(func=cmd_snapshot)

    # log
    log_parser = subparsers.add_parser(
        "log", help="Display the version history for the current session"
    )
    log_parser.set_defaults(func=cmd_log)

    # info
    info_parser = subparsers.add_parser(
        "info", help="Show current session info and version status"
    )
    info_parser.set_defaults(func=cmd_info)

    # config
    config_parser = subparsers.add_parser(
        "config", help="View or update versioning settings for this session"
    )
    config_parser.add_argument(
        "--template", "-t", default=None,
        help="Apply a named template from ~/.ptvc_templates.yaml"
    )
    config_parser.add_argument(
        "--start-number", default=None,
        help="Starting version number (e.g., '1', '0.00', '100')"
    )
    config_parser.add_argument(
        "--increment-by", default=None,
        help="Version increment (e.g., '1', '0.05', '10')"
    )
    config_parser.add_argument(
        "--prefix", default=None,
        help="Version prefix string (e.g., 'v', 'mix-', '' for none)"
    )
    config_parser.add_argument(
        "--zero-pad", type=int, default=None,
        help="Zero-pad integer versions to this many digits (e.g., 3 → v001)"
    )
    config_parser.add_argument(
        "--folder-name", default=None,
        help=f"Name of the versions folder (default: '{DEFAULT_VERSION_DIR_NAME}')"
    )
    config_parser.add_argument(
        "--mode", default=None, choices=["archive", "live"],
        help="Snapshot mode: 'archive' copies .ptx to Versions/; "
             "'live' archives + uses SaveSessionAs to advance the working session"
    )
    config_parser.add_argument(
        "--date-format", default=None,
        help="strftime format for date-based versioning (e.g., '%%Y.%%-m'). "
             "Pass empty string '' to switch back to numeric mode."
    )
    config_parser.add_argument(
        "--text-export", default=None, choices=["on", "off"],
        help="Enable/disable session info text export with each snapshot (default: on)"
    )
    config_parser.add_argument(
        "--text-format", default=None, choices=["UTF8", "TextEdit", "Excel"],
        help="Format for session info text export (default: UTF8)"
    )
    config_parser.set_defaults(func=cmd_config)

    # template
    template_parser = subparsers.add_parser(
        "template", help="Manage global config templates (~/.ptvc_templates.yaml)"
    )
    template_sub = template_parser.add_subparsers(dest="action", required=True)

    template_sub.add_parser(
        "init", help="Create a starter ~/.ptvc_templates.yaml file with defaults and examples"
    )

    save_tmpl = template_sub.add_parser(
        "save", help="Save the current session's config as a named template: ptvc template save <name>"
    )
    save_tmpl.add_argument("name", help="Template name (e.g., 'podcast', 'song exploder')")

    list_tmpl = template_sub.add_parser(
        "list", help="List all saved templates"
    )

    show_tmpl = template_sub.add_parser(
        "show", help="Show the settings in a template: ptvc template show <name>"
    )
    show_tmpl.add_argument("name", help="Template name to show")

    delete_tmpl = template_sub.add_parser(
        "delete", help="Delete a saved template: ptvc template delete <name>"
    )
    delete_tmpl.add_argument("name", help="Template name to delete")

    template_parser.set_defaults(func=cmd_template)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
