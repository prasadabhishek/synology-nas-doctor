---
name: synology-nas-doctor
description: >-
  Audits Synology NAS / DSM storage over mounted SMB shares or SFTP (including
  non-admin accounts), breaks down folder space hogs, finds exact SHA-256
  duplicate media and mirrored directories, and outputs a safe dry-run storage
  reclamation plan. Use when the user asks to audit NAS disk usage, deduplicate
  Synology photos/videos, or safely reclaim NAS storage.
---

# Synology NAS Doctor

## Overview

Safely audits Synology DSM (or any mounted NAS/SMB volume) to uncover hidden space hogs, duplicate mirror directories, and misrouted camera media—using **non-admin-safe** SMB mount or SFTP access and **strict read-only dry-run verification** before any deletion.

## Quick Start

Mount your Synology share in Finder (`Cmd+K` → `smb://<nas-ip>/<share>`), then run:

```bash
# 1. Folder space breakdown (top space hogs + file-type stats)
uv run scripts/nas_audit.py space --root /Volumes/<share> --output /tmp/nas-space.json

# 2. Exact SHA-256 duplicate finder (size pre-filter + partial hash + full hash)
uv run scripts/nas_audit.py dedup --root /Volumes/<share> --min-mb 1 --output /tmp/nas-dedup.json

# 3. Cross-folder mirror verification (verify Folder A is 100% backed up in Folder B)
uv run scripts/nas_audit.py verify-mirror \
  --source /Volumes/<share>/BackupMirror \
  --target /Volumes/<share>/PrimaryPhotos \
  --output /tmp/nas-mirror-audit.json
```

## Utility Scripts

`scripts/nas_audit.py` uses Python 3 standard library only (zero external packages) and is **strictly read-only**—it never deletes or modifies files.

### Subcommands
- **`space --root <dir> --depth <N> --output <path.json>`**: Computes recursive folder sizes, file counts, and extension breakdown (RAW, JPEG, MP4/MOV, etc.) up to `--depth` (default `2`).
- **`dedup --root <dir> --min-mb <MB> --output <path.json>`**: 3-stage fast deduplicator (groups by exact byte size → 64 KB head+tail hash → full SHA-256) to identify exact duplicates and calculate total reclaimable GB.
- **`verify-mirror --source <dir> --target <dir> --output <path.json>`**: Proves whether every file in `--source` has an identical SHA-256 match inside `--target`, explicitly listing any **unique/unmatched** files in `--source` that must be preserved.

## Workflow

### 1. Non-Admin Access Check
On Synology DSM, SSH shell login is restricted to `administrators`. If the user has a non-admin account, do **not** waste time debugging SSH shell keys—use:
1. **SMB Share Mount (Recommended):** `open smb://<nas-ip>/<share>` or Finder `Cmd+K` → mounts under `/Volumes/<share>`.
2. **SFTP Subsystem:** Works even when interactive SSH shell is disabled.

### 2. Space Breakdown & Duplicate Deep Dive
- Run `nas_audit.py space` to locate oversized folders and suspected duplicate mirrors (e.g., `Photos-Backup` vs. `Photos`).
- Run `nas_audit.py dedup` to quantify exact reclaimable bytes.
- If a suspected mirror directory exists, run `nas_audit.py verify-mirror` to prove with SHA-256 checksums which files are 100% duplicated vs. unique.

### 3. Safe Remediation Plan
- Present a concise table of **Reclaimable Space**, **Verified Duplicate Sets**, and **Unique Files to Preserve**.
- **NEVER delete files automatically.** Only after explicit user confirmation, output or execute targeted cleanup commands on verified duplicates only, preserving all unique files.

## Common Mistakes

- **Deleting based on filename alone:** Cameras reset filenames (`DSC00001.ARW`, `IMG_0001.JPG`). Always verify by exact byte size + SHA-256 hash.
- **Trying to enable SSH shell for a non-admin Synology user:** DSM blocks non-admin shell access by design; use SMB mount or SFTP instead.
- **Deleting an entire mirror folder without `verify-mirror`:** A "backup" folder often contains a handful of unique files never copied to the primary library.
