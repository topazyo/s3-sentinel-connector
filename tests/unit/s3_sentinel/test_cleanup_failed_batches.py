from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from scripts.cleanup_failed_batches import cleanup_failed_batches


def test_cleanup_failed_batches_dry_run_keeps_files(tmp_path):
    old_file = tmp_path / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    old_time = datetime.now(timezone.utc) - timedelta(days=45)
    old_timestamp = old_time.timestamp()
    old_file.touch()
    old_file_stat = old_file.stat()
    os.utime(old_file, (old_timestamp, old_timestamp))

    summary = cleanup_failed_batches(
        directory=str(tmp_path),
        max_age_days=30,
        dry_run=True,
    )

    assert summary.files_examined == 1
    assert summary.files_deleted == 1
    assert summary.bytes_reclaimed == old_file_stat.st_size
    assert old_file.exists()


def test_cleanup_failed_batches_deletes_old_files(tmp_path):
    old_file = tmp_path / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    old_time = datetime.now(timezone.utc) - timedelta(days=45)
    old_timestamp = old_time.timestamp()
    old_file.touch()
    os.utime(old_file, (old_timestamp, old_timestamp))

    summary = cleanup_failed_batches(
        directory=str(tmp_path),
        max_age_days=30,
        dry_run=False,
    )

    assert summary.files_examined == 1
    assert summary.files_deleted == 1
    assert not old_file.exists()
