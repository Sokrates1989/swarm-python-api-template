"""
Module: executable_profile_release_validation.py

Description:
    Validates optional site-profile metadata that enrolls independently
    published API, Web, Android, and iOS artifacts in one coordinated semantic-
    version stack. The Swarm profile owns each component's minimum for its next
    release, plus a compatibility fallback and the managed component IDs;
    source repositories remain responsible for publication proof.

Dependencies:
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

from collections.abc import Mapping

from executable_profile_support import (
    NAME_PATTERN,
    SEMVER_PATTERN,
    ExecutableProfileError,
    mapping,
    require_keys,
    sequence,
    text,
)


def validate_release_coordination(
    data: Mapping[str, object],
    services: Mapping[str, object],
) -> None:
    """Validate an optional monotonic release-stack declaration.

    Args:
        data: Full executable site profile.
        services: Profile service capability mapping.

    Returns:
        Nothing. Profiles without ``release`` remain unenrolled.

    Raises:
        ExecutableProfileError: If identity, minimum, policy, or component
            coverage is incomplete or unsafe.
    """

    if "release" not in data:
        return
    release = mapping(data["release"], "release")
    require_keys(
        release,
        {"stackId", "versionPolicy", "versionFloor", "components"},
        "release",
    )
    stack_id = text(release["stackId"], "release.stackId")
    version_floor = text(
        release["versionFloor"],
        "release.versionFloor",
    )
    if not NAME_PATTERN.fullmatch(stack_id):
        raise ExecutableProfileError("release.stackId is unsafe.")
    if release["versionPolicy"] != "monotonic-floor":
        raise ExecutableProfileError(
            "release.versionPolicy must be monotonic-floor."
        )
    if not SEMVER_PATTERN.fullmatch(version_floor):
        raise ExecutableProfileError(
            "release.versionFloor must be stable semantic version."
        )
    components = [
        text(component, f"release.components[{index}]")
        for index, component in enumerate(
            sequence(release["components"], "release.components")
        )
    ]
    if not components or len(components) != len(set(components)):
        raise ExecutableProfileError(
            "release.components must contain unique component IDs."
        )
    if any(not NAME_PATTERN.fullmatch(component) for component in components):
        raise ExecutableProfileError("release.components contains unsafe IDs.")
    if "componentVersionFloors" in release:
        component_floors = mapping(
            release["componentVersionFloors"],
            "release.componentVersionFloors",
        )
        unknown = sorted(set(component_floors).difference(components))
        if unknown:
            raise ExecutableProfileError(
                "release.componentVersionFloors contains unknown components: "
                + ", ".join(unknown)
            )
        for component_id, raw_floor in component_floors.items():
            floor = text(
                raw_floor,
                f"release.componentVersionFloors.{component_id}",
            )
            if not SEMVER_PATTERN.fullmatch(floor):
                raise ExecutableProfileError(
                    f"release.componentVersionFloors.{component_id} must be "
                    "stable semantic version."
                )
    required = {"api"}
    if services.get("web") is True:
        required.add("web")
    missing = sorted(required - set(components))
    if missing:
        raise ExecutableProfileError(
            "release.components omits managed services: "
            + ", ".join(missing)
        )


__all__ = ["validate_release_coordination"]
