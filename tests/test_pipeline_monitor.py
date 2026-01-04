import pytest

from src.monitoring.pipeline_monitor import PipelineMonitor


class _FakeMetricsClient:
    def ingest_metrics(self, metrics):
        # pretend ingest succeeded
        return None


@pytest.fixture(autouse=True)
def no_background_tasks(monkeypatch):
    monkeypatch.setattr("asyncio.create_task", lambda *args, **kwargs: None)


@pytest.fixture()
def monitor(monkeypatch):
    monkeypatch.setattr(
        "src.monitoring.pipeline_monitor.MetricsIngestionClient",
        lambda endpoint, credential: _FakeMetricsClient(),
    )
    return PipelineMonitor(
        metrics_endpoint="https://metrics",
        app_name="app",
        environment="dev",
        teams_webhook=None,
        slack_webhook=None,
        s3_health_url=None,
        sentinel_health_url=None,
        enable_background_tasks=False,
    )


@pytest.mark.asyncio
async def test_record_metric_caches_value(monkeypatch, monitor):
    await monitor.record_metric("pipeline_lag", 5)
    assert monitor._metric_cache["pipeline_lag"]["value"] == 5


@pytest.mark.asyncio
async def test_health_checks_without_urls(monkeypatch, monitor):
    s3 = await monitor._check_s3_health()
    sentinel = await monitor._check_sentinel_health()
    assert s3["status"] is True
    assert sentinel["status"] is True


@pytest.mark.asyncio
async def test_alert_condition_triggers(monkeypatch, monitor):
    # ensure metric cache has value above threshold for pipeline_lag (default 300)
    monitor._metric_cache["pipeline_lag"] = {"value": 400}
    cfg = next(c for c in monitor.alert_configs if c.name == "pipeline_lag")
    await monitor._check_alert_condition(cfg)
    assert monitor._active_alerts


class _FakeResp:
    def __init__(self, status: int, text: str = ""):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, status: int):
        self._status = status

    async def post(self, url, json=None):
        return _FakeResp(self._status, "fail")

    async def get(self, url):
        return _FakeResp(self._status, "fail")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_teams_alert_missing_webhook(monkeypatch, monitor):
    await monitor._send_teams_alert({"name": "test"})  # should no-op and not raise


@pytest.mark.asyncio
async def test_slack_alert_missing_webhook(monkeypatch, monitor):
    await monitor._send_slack_alert({"name": "test"})  # should no-op and not raise


@pytest.mark.asyncio
async def test_health_check_http_failure(monkeypatch, monitor):
    # simulate configured URLs with failing status
    monitor.s3_health_url = "https://s3-health"
    monitor.sentinel_health_url = "https://sentinel-health"

    fake_session = _FakeSession(status=500)

    async def _fake_session_factory(*args, **kwargs):
        return fake_session

    monkeypatch.setattr("aiohttp.ClientSession", _fake_session_factory)

    s3 = await monitor._check_s3_health()
    sentinel = await monitor._check_sentinel_health()

    assert s3["status"] is False
    assert sentinel["status"] is False


@pytest.mark.asyncio
async def test_record_metric_handles_ingest_failure(monkeypatch, monitor):
    monitor.metrics_client.ingest_metrics = lambda payload: (_ for _ in ()).throw(
        RuntimeError("boom")
    )

    await monitor.record_metric("pipeline_lag", 7)

    assert monitor._metric_cache["pipeline_lag"]["value"] == 7


@pytest.mark.asyncio
async def test_teams_alert_http_error(monkeypatch, monitor):
    monitor.teams_webhook = "https://teams-webhook"

    fake_session = _FakeSession(status=500)

    def _fake_session_factory(*args, **kwargs):
        return fake_session

    monkeypatch.setattr("aiohttp.ClientSession", _fake_session_factory)

    await monitor._send_teams_alert(
        {
            "name": "test",
            "severity": "high",
            "threshold": 1,
            "current_value": 2,
            "environment": "dev",
            "description": "failure path",
        }
    )  # should not raise


@pytest.mark.asyncio
async def test_slack_alert_http_error(monkeypatch, monitor):
    monitor.slack_webhook = "https://slack-webhook"

    fake_session = _FakeSession(status=500)

    def _fake_session_factory(*args, **kwargs):
        return fake_session

    monkeypatch.setattr("aiohttp.ClientSession", _fake_session_factory)

    await monitor._send_slack_alert(
        {
            "name": "test",
            "severity": "high",
            "threshold": 1,
            "current_value": 2,
            "environment": "dev",
            "description": "failure path",
        }
    )  # should not raise
