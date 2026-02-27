"""Failed-batch replay helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.sentinel_router import SentinelRouter


async def replay_failed_batches(
    router: SentinelRouter,
    log_type: str,
    failed_batches_dir: str,
    archive_subdir: str = "archived",
) -> dict[str, Any]:
    """Replay failed batches and archive successful replays.

    Returns summary with processed, failed, and archived counts.
    """
    root = Path(failed_batches_dir)
    archive_dir = root / archive_subdir
    archive_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    failed = 0
    archived = 0
    errors: list[dict[str, str]] = []

    for batch_file in sorted(root.glob("*.json")):
        processed += 1
        try:
            payload = json.loads(batch_file.read_text(encoding="utf-8"))
            logs = payload.get("data", [])
            if not isinstance(logs, list):
                raise ValueError("Failed-batch payload 'data' must be a list")

            await router.route_logs(log_type, logs)

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archived_path = archive_dir / f"{batch_file.stem}-{timestamp}.json"
            batch_file.rename(archived_path)
            archived += 1
        except Exception as exc:
            failed += 1
            errors.append({"file": batch_file.name, "error": str(exc)})

    return {
        "processed": processed,
        "failed": failed,
        "archived": archived,
        "errors": errors,
    }
