# Synology NAS Doctor

Read-only agent skill and Python CLI for auditing Synology DSM (or any mounted SMB/NAS volume) storage usage, finding exact SHA-256 duplicates, and verifying mirror directories before reclaiming terabytes safely.

## Install as an Agent Skill

```bash
npx skills add prasadabhishek/synology-nas-doctor
```

## Standalone CLI Usage

Requires Python 3 (standard library only — zero external dependencies).

```bash
# Folder & file-type space breakdown
uv run scripts/nas_audit.py space --root /Volumes/MyNAS --depth 2 --output /tmp/nas-space.json

# Exact SHA-256 duplicate finder
uv run scripts/nas_audit.py dedup --root /Volumes/MyNAS --min-mb 1 --output /tmp/nas-dedup.json

# Verify whether a backup mirror folder is 100% duplicated in your primary library
uv run scripts/nas_audit.py verify-mirror \
  --source /Volumes/MyNAS/OldMirror \
  --target /Volumes/MyNAS/PrimaryPhotos \
  --output /tmp/nas-mirror.json
```

## License

MIT
