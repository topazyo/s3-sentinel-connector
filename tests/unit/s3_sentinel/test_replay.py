from __future__ import annotations

import asyncio
import json

from s3_sentinel.replay import replay_failed_batches


class _FakeRouter:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    async def route_logs(self, log_type: str, logs: list[dict]) -> dict:
        if self.should_fail:
            raise RuntimeError("ingest error")
        return {"log_type": log_type, "count": len(logs)}


def test_replay_failed_batches_archives_successful_files(tmp_path):
    payload = {"data": [{"k": "v"}]}
    batch = tmp_path / "failed-1.json"
    batch.write_text(json.dumps(payload), encoding="utf-8")

    result = asyncio.run(
        replay_failed_batches(
            router=_FakeRouter(),
            log_type="firewall",
            failed_batches_dir=str(tmp_path),
        )
    )

    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["archived"] == 1
    assert not batch.exists()
    archived_files = list((tmp_path / "archived").glob("*.json"))
    assert len(archived_files) == 1


def test_replay_failed_batches_tracks_failures(tmp_path):
    payload = {"data": [{"k": "v"}]}
    batch = tmp_path / "failed-1.json"
    batch.write_text(json.dumps(payload), encoding="utf-8")

    result = asyncio.run(
        replay_failed_batches(
            router=_FakeRouter(should_fail=True),
            log_type="firewall",
            failed_batches_dir=str(tmp_path),
        )
    )

    assert result["processed"] == 1
    assert result["failed"] == 1
    assert result["archived"] == 0
    assert batch.exists()
