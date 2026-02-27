# src/security/rotation_manager.py
"""Credential rotation scheduling and execution orchestration."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .credential_manager import CredentialManager


class RotationManager:
    """Coordinates rotation checks, cooldown enforcement, and rotation state."""

    def __init__(
        self, credential_manager: CredentialManager, rotation_config: Dict[str, Any]
    ) -> None:
        """
        Initialize rotation manager

        Args:
            credential_manager: Credential manager instance
            rotation_config: Rotation configuration
        """
        self.credential_manager = credential_manager
        self.rotation_config = rotation_config
        self.logger = logging.getLogger(__name__)

        # Initialize rotation state
        self._rotation_state = {}

    async def check_rotation_needed(self) -> List[str]:
        """Check which credentials need rotation"""
        credentials_to_rotate = []

        try:
            # Get all credentials
            for credential_name in self.rotation_config:
                config = self.rotation_config[credential_name]

                # Check last rotation time
                last_rotation = self._get_last_rotation(credential_name)
                if self._needs_rotation(last_rotation, config):
                    credentials_to_rotate.append(credential_name)

            return credentials_to_rotate

        except Exception as e:
            self.logger.error(f"Failed to check rotation status: {e!s}")
            raise

    async def rotate_credentials(
        self, credential_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Rotate specified credentials

        Args:
            credential_names: List of credentials to rotate

        Returns:
            Dictionary with rotation results
        """
        results = {"successful": [], "failed": [], "skipped": []}

        try:
            # If no specific credentials provided, check all
            if credential_names is None:
                credential_names = await self.check_rotation_needed()

            # Rotate each credential
            for credential_name in credential_names:
                try:
                    if not self._can_rotate(credential_name):
                        results["skipped"].append(credential_name)
                        continue

                    # Generate and set new credential
                    await self.credential_manager.rotate_credential(credential_name)

                    # Update rotation state
                    self._update_rotation_state(credential_name)

                    results["successful"].append(credential_name)

                except Exception as e:
                    self.logger.error(
                        f"Failed to rotate credential {credential_name}: {e!s}"
                    )
                    results["failed"].append(
                        {"credential": credential_name, "error": str(e)}
                    )

            return results

        except Exception as e:
            self.logger.error(f"Credential rotation failed: {e!s}")
            raise

    def _get_last_rotation(self, credential_name: str) -> Optional[datetime]:
        """Get last rotation time for credential"""
        state = self._rotation_state.get(credential_name, {})
        return state.get("last_rotation")

    def _needs_rotation(
        self, last_rotation: Optional[datetime], config: Dict[str, Any]
    ) -> bool:
        """Check if credential needs rotation"""
        if not last_rotation:
            return True

        max_age = config.get("max_age_days", 90)
        now = datetime.now(timezone.utc)
        if last_rotation.tzinfo is None:
            last_rotation = last_rotation.replace(tzinfo=timezone.utc)
        age = now - last_rotation

        return age.days >= max_age

    def _can_rotate(self, credential_name: str) -> bool:
        """Check if credential can be rotated"""
        state = self._rotation_state.get(credential_name, {})

        # Check if minimum time between rotations has passed
        min_interval = self.rotation_config.get(credential_name, {}).get(
            "min_rotation_interval_hours", 24
        )

        last_rotation = state.get("last_rotation")
        if last_rotation:
            now = datetime.now(timezone.utc)
            if last_rotation.tzinfo is None:
                last_rotation = last_rotation.replace(tzinfo=timezone.utc)
            time_since_last = now - last_rotation
            if time_since_last.total_seconds() < (min_interval * 3600):
                return False

        return True

    def _update_rotation_state(self, credential_name: str) -> None:
        """Update rotation state for credential"""
        self._rotation_state[credential_name] = {
            "last_rotation": datetime.now(timezone.utc),
            "rotation_count": self._rotation_state.get(credential_name, {}).get(
                "rotation_count", 0
            )
            + 1,
        }

    async def start_rotation_monitor(self, check_interval: int = 3600) -> None:
        """
        Start background rotation monitoring

        Args:
            check_interval: Interval between checks in seconds
        """
        while True:
            try:
                # Check for credentials needing rotation
                credentials_to_rotate = await self.check_rotation_needed()

                if credentials_to_rotate:
                    self.logger.info(
                        f"Rotating credentials: {', '.join(credentials_to_rotate)}"
                    )
                    await self.rotate_credentials(credentials_to_rotate)

                await asyncio.sleep(check_interval)

            except Exception as e:
                self.logger.error(f"Rotation monitor error: {e!s}")
                await asyncio.sleep(60)  # Short sleep on error
