"""Get share links for all videos in a Dropbox folder → save to txt.

Usage:
    python dropbox-get-links.py                  # interactive: pick folder
    python dropbox-get-links.py /path/to/folder  # direct path
    python dropbox-get-links.py /2705 -o links.txt

Reads Dropbox token from ~/.vsl-hook-merger.json (same as GUI).
"""

import argparse
import json
import sys
from pathlib import Path

import requests

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mxf"}
SETTINGS_PATH = Path.home() / ".vsl-hook-merger.json"


def get_access_token() -> str:
    if not SETTINGS_PATH.exists():
        print("ERROR: No settings file. Run VSL Hook Merger GUI first to authorize Dropbox.")
        sys.exit(1)
    cfg = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    raw = cfg.get("dropbox_token", "")
    if not raw:
        print("ERROR: No Dropbox token in settings. Authorize in GUI first.")
        sys.exit(1)
    return json.loads(raw)["access_token"]


def list_folder(token: str, path: str) -> list[dict]:
    """List all entries in a Dropbox folder (handles pagination)."""
    entries = []
    r = requests.post(
        "https://api.dropboxapi.com/2/files/list_folder",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"path": path, "limit": 2000},
    )
    r.raise_for_status()
    data = r.json()
    entries.extend(data.get("entries", []))

    while data.get("has_more"):
        r = requests.post(
            "https://api.dropboxapi.com/2/files/list_folder/continue",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"cursor": data["cursor"]},
        )
        r.raise_for_status()
        data = r.json()
        entries.extend(data.get("entries", []))

    return entries


def list_folders_interactive(token: str) -> str:
    """Let user pick a folder interactively."""
    print("\nDropbox folders (root):")
    entries = list_folder(token, "")
    folders = [e for e in entries if e[".tag"] == "folder"]
    for i, f in enumerate(folders, 1):
        print(f"  {i}. {f['name']}")

    choice = input(f"\nPick folder (1-{len(folders)}): ").strip()
    try:
        idx = int(choice) - 1
        return folders[idx]["path_lower"]
    except (ValueError, IndexError):
        print("Invalid choice")
        sys.exit(1)


def create_shared_link(token: str, path: str) -> str:
    """Create or get existing shared link for a file."""
    # Try create
    r = requests.post(
        "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"path": path, "settings": {"requested_visibility": "public"}},
    )
    if r.status_code == 200:
        return r.json()["url"]

    # Already exists — fetch existing
    if r.status_code == 409:
        r2 = requests.post(
            "https://api.dropboxapi.com/2/sharing/list_shared_links",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"path": path, "direct_only": True},
        )
        if r2.status_code == 200:
            links = r2.json().get("links", [])
            if links:
                return links[0]["url"]

    print(f"  WARNING: Could not get link for {path}: {r.text[:200]}")
    return ""


def main():
    parser = argparse.ArgumentParser(description="Get Dropbox share links for videos in a folder")
    parser.add_argument("folder", nargs="?", help="Dropbox folder path (e.g. /2705)")
    parser.add_argument("-o", "--output", default="dropbox_links.txt", help="Output txt file")
    parser.add_argument("--all", action="store_true", help="Include all files, not just videos")
    args = parser.parse_args()

    token = get_access_token()
    print(f"Dropbox connected")

    folder = args.folder
    if not folder:
        folder = list_folders_interactive(token)

    print(f"\nListing: {folder}")
    entries = list_folder(token, folder)
    files = [e for e in entries if e[".tag"] == "file"]

    if not args.all:
        files = [f for f in files if Path(f["name"]).suffix.lower() in VIDEO_EXTS]

    if not files:
        print("No video files found in this folder.")
        sys.exit(0)

    print(f"Found {len(files)} video(s). Getting share links...\n")

    links = []
    for i, f in enumerate(files, 1):
        name = f["name"]
        size_mb = f.get("size", 0) / (1024 * 1024)
        print(f"  [{i}/{len(files)}] {name} ({size_mb:.1f} MB)...", end=" ")
        url = create_shared_link(token, f["path_lower"])
        if url:
            links.append(url)
            print("OK")
        else:
            print("SKIP")

    # Save to txt
    output = Path(args.output)
    output.write_text("\n".join(links) + "\n", encoding="utf-8")
    print(f"\n{len(links)} links saved to: {output.absolute()}")


if __name__ == "__main__":
    main()
