# gopro-cloud-sync

CLI tool to sync your entire GoPro cloud media library to local storage. Bypasses the 25-file download limit of the GoPro web interface.

## Features

- Downloads all media types: Video, Photo, TimeLapse, Burst
- Concurrent downloads with progress bars
- Resumes interrupted downloads automatically (`.part` files)
- Organizes files by date: `YYYY/MM/DD/filename.MP4`
- SQLite-backed sync state — re-running only downloads new files
- Supports 2FA accounts via manual token input

## Install

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Gheop/gopro-cloud-sync.git
cd gopro-cloud-sync
uv sync
```

## Authentication

GoPro has no public API. This tool uses the same endpoints as the web app.

### Option 1: Email & password (no 2FA)

```bash
uv run gopro-sync login
```

### Option 2: Manual token (2FA accounts)

1. Log in at [plus.gopro.com/media-library](https://plus.gopro.com/media-library/)
2. Open DevTools → Application → Cookies
3. Copy the value of `gp_access_token`

```bash
uv run gopro-sync login-token "eyJhbGc..."
```

> Tokens expire after a few hours. You'll need to grab a fresh one when it does.

## Usage

```bash
# Sync everything to ~/GoPro (default)
uv run gopro-sync sync

# Custom output directory
uv run gopro-sync sync -o /mnt/nas/gopro

# 10 parallel downloads
uv run gopro-sync sync -c 10

# Preview what would be downloaded
uv run gopro-sync sync --dry-run

# Check sync progress
uv run gopro-sync status

# Re-download everything
uv run gopro-sync reset
```

## How it works

1. Authenticates with `api.gopro.com` using OAuth2 or a manual token
2. Paginates through `/media/search` to discover all cloud media
3. Stores media metadata in a local SQLite database (`~/.local/share/gopro-cloud-sync/sync.db`)
4. Downloads new files concurrently, streaming to `.part` files first
5. On completion, renames `.part` to final filename and marks as done in the database

Re-running `sync` skips already downloaded files. Failed downloads are retried on the next run.

## File structure

Downloaded media is organized by capture date:

```
~/GoPro/
├── 2024/
│   └── 08/
│       └── 15/
│           ├── GX010042.MP4
│           └── GX010043.MP4
└── 2025/
    └── 03/
        └── 02/
            └── GX010100.MP4
```

## Config & data

| Path | Content |
|---|---|
| `~/.config/gopro-cloud-sync/config.json` | Auth tokens (chmod 600) |
| `~/.local/share/gopro-cloud-sync/sync.db` | Sync state database |

## Disclaimer

This tool uses undocumented GoPro API endpoints that may change at any time. Use at your own risk.
