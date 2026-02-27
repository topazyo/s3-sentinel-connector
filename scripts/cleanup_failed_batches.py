"""Cleanup utility for failed batch payload files."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class CleanupSummary:
    """Summary of cleanup results."""

    files_examined: int
    files_deleted: int
    bytes_reclaimed: int


def cleanup_failed_batches(
    directory: str,
    max_age_days: int,
    dry_run: bool = False,
) -> CleanupSummary:
    """Delete failed-batch JSON files older than max_age_days."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    files_examined = 0
    files_deleted = 0
    bytes_reclaimed = 0

    for json_file in sorted(root.glob("*.json")):
        files_examined += 1
        modified = datetime.fromtimestamp(json_file.stat().st_mtime, tz=timezone.utc)
        if modified >= cutoff:
            continue

        size = json_file.stat().st_size
        if not dry_run:
            json_file.unlink(missing_ok=True)

        files_deleted += 1
        bytes_reclaimed += size

    return CleanupSummary(
        files_examined=files_examined,
        files_deleted=files_deleted,
        bytes_reclaimed=bytes_reclaimed,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build cleanup CLI parser."""
    parser = argparse.ArgumentParser(
        description="Delete old failed-batch JSON files based on retention.",
    )
    parser.add_argument(
        "--directory",
        default="failed_batches",
        help="Directory containing failed batch JSON files.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=30,
        help="Delete files older than this many days.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without removing files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute cleanup script."""
    args = build_parser().parse_args(argv)
    summary = cleanup_failed_batches(
        directory=args.directory,
        max_age_days=args.max_age_days,
        dry_run=args.dry_run,
    )

    mode = "DRY RUN" if args.dry_run else "DELETE"
    print(
        f"[{mode}] examined={summary.files_examined} "
        f"deleted={summary.files_deleted} "
        f"bytes_reclaimed={summary.bytes_reclaimed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
