import json
from datetime import datetime, timedelta, timezone

import pytest

from src.core.log_parser import LogParser
from src.core.s3_handler import S3Handler


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakePaginator:
    def __init__(self, objects):
        self._objects = objects

    def paginate(self, Bucket, Prefix, PaginationConfig):
        return [
            {
                "Contents": [
                    {
                        "Key": key,
                        "Size": len(self._objects[key]),
                        "LastModified": datetime.now(timezone.utc)
                        - timedelta(minutes=10),
                        "ETag": "etag",
                        "StorageClass": "STANDARD",
                    }
                    for key in self._objects
                    if key.startswith(Prefix)
                ]
            }
        ]


class _FakeS3Client:
    def __init__(self, objects):
        self._objects = objects

    def get_paginator(self, name):
        return _FakePaginator(self._objects)

    def get_object(self, Bucket, Key):
        return {"Body": _FakeBody(self._objects[Key])}


class _DummyParser(LogParser):
    def parse(self, log_data: bytes):
        return json.loads(log_data)

    def validate(self, parsed_data):
        return True


@pytest.fixture()
def fake_boto3(monkeypatch):
    objects = {
        "logs/firewall/a.json": b'{"a":1}',
        "logs/firewall/b.json": b'{"b":2}',
    }

    def _fake_client(*args, **kwargs):
        return _FakeS3Client(objects)

    monkeypatch.setattr("src.core.s3_handler.boto3.client", _fake_client)
    return objects


@pytest.mark.asyncio
async def test_list_objects_filters_prefix(fake_boto3):
    handler = S3Handler("k", "s", "us-east-1", max_threads=2)
    objs = await handler.list_objects_async("bucket", prefix="logs/firewall")
    assert len(objs) == 2
    assert all(o["Key"].startswith("logs/firewall") for o in objs)


@pytest.mark.asyncio
async def test_process_files_batch_parses_and_validates(fake_boto3):
    handler = S3Handler("k", "s", "us-east-1", batch_size=2, max_threads=2)
    objs = await handler.list_objects_async("bucket", prefix="logs/firewall")

    parsed = []

    async def _cb(batch, log_type=None):
        parsed.extend(batch)

    results = await handler.process_files_batch_async(
        "bucket", objs, parser=_DummyParser(), callback=_cb, log_type="firewall"
    )

    assert len(results["successful"]) == 2
    assert not results["failed"]
    assert len(parsed) == 2
    assert parsed[0] == {"a": 1} or parsed[0] == {"b": 2}
