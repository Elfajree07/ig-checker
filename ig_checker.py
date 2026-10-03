#!/usr/bin/env python3

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


# ---------- Reading data ----------

def collect(obj, out):
    """Collect usernames from an Instagram export JSON structure or a snapshot file."""
    if isinstance(obj, list):
        for item in obj:
            collect(item, out)
    elif isinstance(obj, dict):
        sld = obj.get("string_list_data")
        if isinstance(sld, list):
            first = sld[0] if sld and isinstance(sld[0], dict) else {}
            href = first.get("href") or ""
            name = first.get("value") or obj.get("title") or href.rstrip("/").split("/")[-1]
            if name:
                out[name.lower()] = {"username": name, "timestamp": first.get("timestamp", 0)}
        elif isinstance(obj.get("users"), list) and all(isinstance(u, str) for u in obj["users"]):
            for name in obj["users"]:
                out[name.lower()] = {"username": name, "timestamp": 0}
        else:
            for value in obj.values():
                collect(value, out)


def load_users(paths):
    users = {}
    for path in paths:
        if not path.is_file():
            sys.exit(f"File not found: {path}")
        try:
            with open(path, encoding="utf-8") as f:
                collect(json.load(f), users)
        except json.JSONDecodeError:
            sys.exit(f"{path} is not valid JSON. Make sure you chose JSON (not HTML) as the Instagram export format.")
    return users


def discover(data_dir):
    """Find followers_*.json and following.json inside the export folder."""
    followers = sorted(data_dir.rglob("followers_*.json"))
    following = sorted(data_dir.rglob("following.json"))
    return followers, (following[0] if following else None)


# ---------- Snapshots ----------

def latest_snapshot(snap_dir):
    files = sorted(snap_dir.glob("followers_*.json")) if snap_dir.is_dir() else []
    return files[-1] if files else None


def save_snapshot(snap_dir, users):
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"followers_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {"date": datetime.now().isoformat(timespec="seconds"),
               "users": sorted(u["username"] for u in users.values())}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------- Analysis & output ----------

def diff(a, b):
    return sorted((v for k, v in a.items() if k not in b), key=lambda v: v["username"].lower())


def fmt_date(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "-"


def show(title, desc, rows):
    console.print(f"\n[bold]{title}[/bold] ({len(rows)})")
    console.print(f"[dim]{desc}[/dim]")
    if not rows:
        console.print("  No accounts.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Username")
    table.add_column("Profile")
    table.add_column("Date")
    for i, r in enumerate(rows, 1):
        table.add_row(str(i), r["username"], f"instagram.com/{r['username']}", fmt_date(r["timestamp"]))
    console.print(table)


def write_csv(folder, name, rows):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "url", "date"])
        for r in rows:
            w.writerow([r["username"], f"https://www.instagram.com/{r['username']}/", fmt_date(r["timestamp"])])


def main():
    p = argparse.ArgumentParser(description="Check who unfollowed you using your own Instagram data export.")
    p.add_argument("data_dir", nargs="?", type=Path,
                   help="Extracted Instagram export folder (followers_*.json and following.json are found automatically)")
    p.add_argument("--followers", nargs="+", type=Path, help="One or more followers_*.json files")
    p.add_argument("--following", type=Path, help="The following.json file")
    p.add_argument("--old", nargs="+", type=Path,
                   help="Older followers data (a previous export or a snapshot) used to detect unfollowers")
    p.add_argument("--snapshot-dir", type=Path, default=Path("snapshots"),
                   help="Snapshot folder (default: ./snapshots)")
    p.add_argument("--save-snapshot", action="store_true", help="Save the current followers as a snapshot")
    p.add_argument("--csv", type=Path, metavar="FOLDER", help="Save results as CSV files in this folder")
    args = p.parse_args()

    followers_files, following_file = args.followers, args.following
    if args.data_dir:
        if not args.data_dir.is_dir():
            p.error(f"Folder not found: {args.data_dir}")
        found_followers, found_following = discover(args.data_dir)
        followers_files = followers_files or found_followers
        following_file = following_file or found_following
    if not followers_files:
        p.error("Followers file not found. Provide the export folder, or use --followers.")

    current = load_users(followers_files)
    following = load_users([following_file]) if following_file else {}

    if args.old:
        old, old_label = load_users(args.old), "old followers file"
    else:
        snap = latest_snapshot(args.snapshot_dir)
        old, old_label = (load_users([snap]), f"snapshot {snap.name}") if snap else ({}, "")

    console.print(f"Followers: [bold]{len(current)}[/bold]"
                  + (f"   Following: [bold]{len(following)}[/bold]" if following else "")
                  + (f"   Compared against: {old_label}" if old else ""))

    sections = []
    if old:
        sections.append(("unfollowed", "Unfollowed",
                         "Present in the old data, but no longer in your current followers. "
                         "This can also happen if the account was deleted or deactivated.", diff(old, current)))
        sections.append(("new_followers", "New followers",
                         "Present in your current followers, but not in the old data.", diff(current, old)))
    else:
        console.print("[yellow]No comparison data yet. Use --save-snapshot now, "
                      "then run again after your next export to see who unfollowed.[/yellow]")
    if following:
        sections.append(("not_following_back", "Not following back",
                         "You follow them, but they don't follow you.", diff(following, current)))
        sections.append(("not_followed_by_you", "Not followed by you",
                         "They follow you, but you don't follow them back.", diff(current, following)))

    for key, title, desc, rows in sections:
        show(title, desc, rows)
        if args.csv:
            write_csv(args.csv, key, rows)
    if args.csv:
        console.print(f"\nCSV saved to: {args.csv.resolve()}")

    if args.save_snapshot:
        path = save_snapshot(args.snapshot_dir, current)
        console.print(f"Snapshot saved: {path}")


if __name__ == "__main__":
    main()
