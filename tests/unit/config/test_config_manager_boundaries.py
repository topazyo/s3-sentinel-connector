import pytest
import yaml

from src.config.config_manager import ConfigManager


@pytest.fixture
def config_dir(tmp_path):
    base_config = {
        "aws": {
            "region": "us-east-1",
            "bucket_name": "test-bucket",
        },
        "sentinel": {
            "workspace_id": "base-workspace",
        },
        "monitoring": {
            "log_level": "INFO",
            "metrics": {
                "enabled": True,
            },
        },
    }

    with open(tmp_path / "base.yaml", "w") as file:
        yaml.dump(base_config, file)

    with open(tmp_path / "dev.yaml", "w") as file:
        yaml.dump({}, file)

    return tmp_path


def test_env_override_preserves_underscored_field_names(config_dir, monkeypatch):
    monkeypatch.setenv("APP_SENTINEL_WORKSPACE_ID", "override-workspace")

    manager = ConfigManager(
        config_path=str(config_dir),
        environment="dev",
        enable_hot_reload=False,
    )

    sentinel_config = manager.get_config("sentinel")
    assert sentinel_config["workspace_id"] == "override-workspace"
    assert "workspace" not in sentinel_config


def test_env_override_supports_explicit_nested_path_with_double_underscore(
    config_dir, monkeypatch
):
    monkeypatch.setenv("APP_MONITORING__METRICS__ENABLED", "false")

    manager = ConfigManager(
        config_path=str(config_dir),
        environment="dev",
        enable_hot_reload=False,
    )

    monitoring_config = manager.get_config("monitoring")
    assert monitoring_config["metrics"]["enabled"] == "false"
