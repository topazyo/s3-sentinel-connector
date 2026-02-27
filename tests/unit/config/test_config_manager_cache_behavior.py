from unittest.mock import Mock

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
    }

    with open(tmp_path / "base.yaml", "w") as file:
        yaml.dump(base_config, file)

    with open(tmp_path / "dev.yaml", "w") as file:
        yaml.dump({}, file)

    return tmp_path


def test_apply_env_variables_caches_override_paths(config_dir, monkeypatch):
    monkeypatch.setenv("APP_AWS_REGION", "us-west-2")

    manager = ConfigManager(
        config_path=str(config_dir),
        environment="dev",
        enable_hot_reload=False,
    )

    original_parse = manager._parse_env_override_path
    manager._parse_env_override_path = Mock(wraps=original_parse)

    manager._apply_env_variables()
    manager._apply_env_variables()

    assert manager._parse_env_override_path.call_count == 0


def test_get_config_avoids_reload_when_component_cached(config_dir, monkeypatch):
    manager = ConfigManager(
        config_path=str(config_dir),
        environment="dev",
        enable_hot_reload=False,
    )

    reload_spy = Mock(wraps=manager.reload_config)
    monkeypatch.setattr(manager, "reload_config", reload_spy)

    aws_config = manager.get_config("aws")

    assert aws_config["region"] == "us-east-1"
    reload_spy.assert_not_called()
