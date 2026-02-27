"""Edge-case tests for RotationManager (B3-008)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.security.rotation_manager import RotationManager


@pytest.fixture
def credential_manager() -> MagicMock:
    manager = MagicMock()
    manager.rotate_credential = AsyncMock(return_value="rotated-secret")
    return manager


@pytest.fixture
def rotation_config() -> dict:
    return {
        "cred-a": {"max_age_days": 90, "min_rotation_interval_hours": 24},
        "cred-b": {"max_age_days": 30, "min_rotation_interval_hours": 1},
    }


@pytest.fixture
def rotation_manager(
    credential_manager: MagicMock, rotation_config: dict
) -> RotationManager:
    return RotationManager(credential_manager, rotation_config)


class TestRotationManagerEdgeCases:
    def test_needs_rotation_handles_naive_datetime(
        self, rotation_manager: RotationManager
    ):
        """Naive datetimes are normalized to UTC in age calculation."""
        naive_old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=91)

        assert rotation_manager._needs_rotation(naive_old, {"max_age_days": 90}) is True

    def test_can_rotate_handles_naive_last_rotation(
        self, rotation_manager: RotationManager
    ):
        """Naive last_rotation values respect minimum interval checks."""
        rotation_manager._rotation_state = {
            "cred-a": {
                "last_rotation": datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(hours=2)
            }
        }
        rotation_manager.rotation_config["cred-a"]["min_rotation_interval_hours"] = 4

        assert rotation_manager._can_rotate("cred-a") is False

    @pytest.mark.asyncio
    async def test_rotate_credentials_records_failures(
        self, rotation_manager: RotationManager
    ):
        """Rotation failures are reported in failed results without aborting batch."""

        async def rotate_side_effect(name: str):
            if name == "cred-b":
                raise RuntimeError("rotation failed")
            return "ok"

        setattr(  # noqa: B010
            rotation_manager.credential_manager.rotate_credential,
            "side_effect",
            rotate_side_effect,
        )

        results = await rotation_manager.rotate_credentials(["cred-a", "cred-b"])

        assert "cred-a" in results["successful"]
        assert any(item["credential"] == "cred-b" for item in results["failed"])

    @pytest.mark.asyncio
    async def test_rotate_credentials_none_uses_check_rotation_needed(
        self, rotation_manager: RotationManager
    ):
        """When credential_names is None, manager rotates only credentials needing rotation."""
        rotation_manager.check_rotation_needed = AsyncMock(return_value=["cred-a"])

        results = await rotation_manager.rotate_credentials(None)

        rotation_manager.check_rotation_needed.assert_awaited_once()
        assert results["successful"] == ["cred-a"]
        assert results["failed"] == []
        assert results["skipped"] == []
