#!/usr/bin/env python3
"""Read-only Synology / NAS storage breakdown, SHA-256 deduplicator, and mirror verifier."""

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {"@eaDir", "#recycle", ".Trashes", ".Spotlight-V100", ".fseventsd"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname in SKIP_FILES or fname.startswith("._"):
                continue
            fpath = Path(dirpath) / fname
            try:
                if fpath.is_symlink():
                    continue
                st = fpath.stat()
                yield fpath, st.st_size
            except OSError:
                continue


def partial_hash(path: Path, size: int, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read(chunk))
        if size > chunk:
            f.seek(max(0, size - chunk))
            h.update(f.read(chunk))
    return h.hexdigest()


def full_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def fmt_gb(nbytes: int) -> float:
    return round(nbytes / (1024 ** 3), 3)


def cmd_space(root: Path, depth: int, output: Path) -> None:
    if not root.exists():
        print(f"Error: root path does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    folder_bytes: dict[str, int] = defaultdict(int)
    folder_counts: dict[str, int] = defaultdict(int)
    ext_bytes: dict[str, int] = defaultdict(int)
    ext_counts: dict[str, int] = defaultdict(int)
    total_bytes = 0
    total_files = 0

    for fpath, size in iter_files(root):
        total_bytes += size
        total_files += 1
        rel = fpath.relative_to(root)
        parts = rel.parts[:-1]
        bucket = "/".join(parts[:depth]) if parts else "."
        folder_bytes[bucket] += size
        folder_counts[bucket] += 1
        ext = fpath.suffix.lower() or "(no_ext)"
        ext_bytes[ext] += size
        ext_counts[ext] += 1

    top_folders = sorted(folder_bytes.items(), key=lambda kv: kv[1], reverse=True)[:30]
    top_exts = sorted(ext_bytes.items(), key=lambda kv: kv[1], reverse=True)[:20]

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_gb": fmt_gb(total_bytes),
        "top_folders": [
            {"folder": k, "files": folder_counts[k], "bytes": v, "gb": fmt_gb(v)}
            for k, v in top_folders
        ],
        "top_extensions": [
            {"ext": k, "files": ext_counts[k], "bytes": v, "gb": fmt_gb(v)}
            for k, v in top_exts
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(f"Success! Space breakdown written to: {output} ({total_files} files, {fmt_gb(total_bytes)} GB)")


def cmd_dedup(root: Path, min_mb: float, output: Path) -> None:
    if not root.exists():
        print(f"Error: root path does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    min_bytes = int(min_mb * 1024 * 1024)
    by_size: dict[int, list[Path]] = defaultdict(list)
    scanned = 0
    for fpath, size in iter_files(root):
        scanned += 1
        if size >= min_bytes:
            by_size[size].append(fpath)

    by_partial: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        for p in paths:
            try:
                by_partial[(size, partial_hash(p, size))].append(p)
            except OSError:
                continue

    dup_groups = []
    reclaimable_bytes = 0
    for (size, _), paths in by_partial.items():
        if len(paths) < 2:
            continue
        by_full: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            try:
                by_full[full_sha256(p)].append(p)
            except OSError:
                continue
        for digest, group in by_full.items():
            if len(group) >= 2:
                reclaimable_bytes += size * (len(group) - 1)
                dup_groups.append({
                    "sha256": digest,
                    "size_bytes": size,
                    "size_mb": round(size / (1024 ** 2), 2),
                    "count": len(group),
                    "reclaimable_bytes": size * (len(group) - 1),
                    "paths": sorted(str(p) for p in group),
                })

    dup_groups.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "min_mb": min_mb,
        "files_scanned": scanned,
        "duplicate_groups_count": len(dup_groups),
        "reclaimable_bytes": reclaimable_bytes,
        "reclaimable_gb": fmt_gb(reclaimable_bytes),
        "duplicate_groups": dup_groups,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(
        f"Success! Dedup audit written to: {output} "
        f"({len(dup_groups)} groups, {fmt_gb(reclaimable_bytes)} GB reclaimable)"
    )


def cmd_verify_mirror(source: Path, target: Path, output: Path) -> None:
    for label, p in [("source", source), ("target", target)]:
        if not p.exists():
            print(f"Error: {label} path does not exist: {p}", file=sys.stderr)
            sys.exit(1)

    target_by_size: dict[int, list[Path]] = defaultdict(list)
    for fpath, size in iter_files(target):
        target_by_size[size].append(fpath)

    target_hash_cache: dict[Path, str] = {}
    verified = []
    unique_in_source = []
    verified_bytes = 0
    unique_bytes = 0

    for spath, ssize in iter_files(source):
        candidates = target_by_size.get(ssize, [])
        if not candidates:
            unique_in_source.append({"path": str(spath), "size_bytes": ssize})
            unique_bytes += ssize
            continue
        try:
            s_digest = full_sha256(spath)
        except OSError:
            unique_in_source.append({"path": str(spath), "size_bytes": ssize, "note": "read_error"})
            unique_bytes += ssize
            continue

        matched_target = None
        for cpath in candidates:
            if cpath not in target_hash_cache:
                try:
                    target_hash_cache[cpath] = full_sha256(cpath)
                except OSError:
                    target_hash_cache[cpath] = ""
            if target_hash_cache[cpath] == s_digest:
                matched_target = str(cpath)
                break

        if matched_target:
            verified.append({"source": str(spath), "target": matched_target, "size_bytes": ssize, "sha256": s_digest})
            verified_bytes += ssize
        else:
            unique_in_source.append({"path": str(spath), "size_bytes": ssize, "sha256": s_digest})
            unique_bytes += ssize

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "target": str(target),
        "safe_to_delete_source_entirely": len(unique_in_source) == 0,
        "verified_duplicate_files": len(verified),
        "verified_duplicate_gb": fmt_gb(verified_bytes),
        "unique_files_in_source": len(unique_in_source),
        "unique_files_gb": fmt_gb(unique_bytes),
        "unique_files": unique_in_source,
        "verified_samples": verified[:50],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(
        f"Success! Mirror verification written to: {output} "
        f"(verified={len(verified)}, unique_in_source={len(unique_in_source)})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Synology / NAS Storage & Deduplication Doctor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sp = sub.add_parser("space", help="Folder and extension space breakdown")
    p_sp.add_argument("--root", required=True, type=Path)
    p_sp.add_argument("--depth", type=int, default=2)
    p_sp.add_argument("--output", required=True, type=Path)

    p_dd = sub.add_parser("dedup", help="Exact SHA-256 duplicate finder")
    p_dd.add_argument("--root", required=True, type=Path)
    p_dd.add_argument("--min-mb", type=float, default=1.0)
    p_dd.add_argument("--output", required=True, type=Path)

    p_vm = sub.add_parser("verify-mirror", help="Verify every file in --source exists identically in --target")
    p_vm.add_argument("--source", required=True, type=Path)
    p_vm.add_argument("--target", required=True, type=Path)
    p_vm.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "space":
        cmd_space(args.root, args.depth, args.output)
    elif args.command == "dedup":
        cmd_dedup(args.root, args.min_mb, args.output)
    elif args.command == "verify-mirror":
        cmd_verify_mirror(args.source, args.target, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
