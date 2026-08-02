"""
Module: executable_profile.py

Description:
    Exposes the normalized schema-5 executable profile model and coordinates
    strict parsing, tracked configuration validation, operator environment
    validation, runtime allowlist assembly, and public fingerprinting. All
    application identity comes from the selected site-config document.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_config_validation.py.
    - scripts/executable_profile_deployment_validation.py.
    - scripts/executable_profile_runtime.py.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from executable_profile_config_validation import validate_config
from executable_profile_deployment_validation import validate_deployment
from executable_profile_runtime import (
    SecretMount,
    parse_mounts,
    public_fingerprint,
    runtime_environment,
)
from executable_profile_support import (
    ExecutableProfileError,
    config_path,
    load_json,
    mapping,
    read_env,
)


@dataclass(frozen=True)
class ExecutableProfile:
    """Contains one fully validated site-config-driven deployment.

    Attributes:
        root: Repository root.
        config_id: Selected site-config filename stem.
        config_path: Canonical tracked profile path.
        data: Parsed site configuration.
        deployment: Parsed operator-owned root environment.
        environment: Exact API runtime environment allowlist values.
        env_keys: Ordered runtime environment keys.
        secret_mounts: Active API secret mounts.
        fingerprint: Deterministic public profile fingerprint.
    """

    root: Path
    config_id: str
    config_path: Path
    data: Mapping[str, object]
    deployment: Mapping[str, str]
    environment: Mapping[str, str]
    env_keys: tuple[str, ...]
    secret_mounts: tuple[SecretMount, ...]
    fingerprint: str

    @property
    def image_reference(self) -> str:
        """Return the exact versioned API image reference."""

        return (
            f"{self.deployment['IMAGE_NAME']}:"
            f"{self.deployment['IMAGE_VERSION']}"
        )

    @property
    def web_image_reference(self) -> str:
        """Return the exact versioned WebApp image reference or empty text."""

        if self.deployment["WEB_ENABLED"] != "true":
            return ""
        return (
            f"{self.deployment['WEB_IMAGE_NAME']}:"
            f"{self.deployment['WEB_IMAGE_VERSION']}"
        )

    @property
    def app_id(self) -> str:
        """Return the selected profile's application ID."""

        return str(self.data["appId"])

    @property
    def stack_name(self) -> str:
        """Return the configured Docker stack name."""

        return self.deployment["STACK_NAME"]

    def safe_summary(self) -> dict[str, object]:
        """Return deterministic public evidence without secret values."""

        services = mapping(self.data["services"], "services")
        release = mapping(self.data.get("release", {}), "release")
        return {
            "profileId": self.config_id,
            "appId": self.app_id,
            "stackName": self.stack_name,
            "services": [
                name
                for name in ("web", "api", "redis", "database")
                if bool(services.get(name))
            ],
            "apiImage": self.image_reference,
            "webImage": self.web_image_reference or None,
            "releaseStack": (
                {
                    "stackId": release["stackId"],
                    "versionPolicy": release["versionPolicy"],
                    "versionFloor": release["versionFloor"],
                    "components": list(release["components"]),
                }
                if release
                else None
            ),
            "dockerSecrets": [
                mount.name for mount in self.secret_mounts
            ],
            "profileFingerprint": self.fingerprint,
        }


def load_executable_profile(root: Path) -> ExecutableProfile:
    """Load and validate the root-selected executable site profile.

    Args:
        root: Swarm repository root containing ``.env`` and ``site-configs``.

    Returns:
        Fully validated normalized profile.

    Raises:
        ExecutableProfileError: If profile or environment input is unsafe.
    """

    resolved_root = root.resolve()
    deployment = read_env(resolved_root / ".env")
    config_id = deployment["DEPLOYMENT_PROFILE_ID"]
    selected_path = config_path(resolved_root, config_id)
    data = load_json(selected_path)
    validate_config(data)
    validate_deployment(data, config_id, deployment)
    mounts, capability_environment = parse_mounts(data)
    environment, env_keys = runtime_environment(
        data,
        deployment,
        mounts,
        capability_environment,
    )
    return ExecutableProfile(
        root=resolved_root,
        config_id=config_id,
        config_path=selected_path,
        data=data,
        deployment=deployment,
        environment=environment,
        env_keys=env_keys,
        secret_mounts=mounts,
        fingerprint=public_fingerprint(data, deployment),
    )


__all__ = [
    "ExecutableProfile",
    "ExecutableProfileError",
    "SecretMount",
    "load_executable_profile",
]
