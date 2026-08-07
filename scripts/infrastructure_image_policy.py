"""
Module: infrastructure_image_policy.py

Description:
    Defines registry-tag compatibility and exact-digest reminder policy for
    infrastructure images. The module is intentionally registry-agnostic so
    audit, reporting, and update commands share one interpretation of a
    PostgreSQL, Redis, or management-image compatibility track.

Dependencies:
    - Python standard library only.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any


VERSION_TAG_PATTERN = re.compile(
    r"^v?(?P<version>[0-9]+(?:\.[0-9]+){0,2})"
    r"(?:-(?P<suffix>[a-z0-9][a-z0-9._-]*))?$",
    re.IGNORECASE,
)
UNSTABLE_TAG_WORDS = frozenset(
    {"alpha", "beta", "candidate", "dev", "nightly", "preview", "rc"}
)


@dataclass(frozen=True)
class VersionTag:
    """One stable numeric infrastructure-image tag.

    Attributes:
        value: Original registry tag.
        version: One to three numeric version components.
        suffix: Optional operating-system or image-variant suffix.
        family: Normalized suffix family such as ``alpine`` or ``bookworm``.
    """

    value: str
    version: tuple[int, ...]
    suffix: str
    family: str


def _suffix_family(value: str) -> str:
    """Normalize a tag suffix to its compatibility family.

    Args:
        value: Optional suffix following the numeric version.

    Returns:
        Lowercase family identifier, or an empty string for the default image.
    """

    lowered = value.lower()
    for family in ("alpine", "bookworm", "bullseye", "trixie"):
        if lowered.startswith(family):
            return family
    match = re.match(r"[a-z]+", lowered)
    return match.group(0) if match else lowered


def parse_version_tag(value: str) -> VersionTag | None:
    """Parse a stable numeric infrastructure-image tag.

    Args:
        value: Registry tag candidate.

    Returns:
        Parsed tag, or ``None`` for floating, prerelease, or unsafe tags.
    """

    lowered = value.lower()
    if any(word in lowered for word in UNSTABLE_TAG_WORDS):
        return None
    match = VERSION_TAG_PATTERN.fullmatch(value)
    if match is None:
        return None
    suffix = match.group("suffix") or ""
    version = tuple(int(part) for part in match.group("version").split("."))
    return VersionTag(value, version, suffix, _suffix_family(suffix))


def compatible_release_tags(
    values: Iterable[str],
    track_tag: str,
    *,
    limit: int = 24,
) -> list[str]:
    """Select recent stable tags compatible with one tracked image channel.

    Numeric tracks lock their numeric prefix and image family. For example,
    ``16-alpine`` accepts stable PostgreSQL 16.x Alpine releases but never 17.x
    or Debian variants. ``latest`` accepts stable unsuffixed numeric releases,
    which is appropriate for stateless tools such as pgAdmin.

    Args:
        values: Registry tags.
        track_tag: Configured compatibility channel.
        limit: Maximum returned tag count; defaults to 24.

    Returns:
        Compatible release tags in descending numeric order.
    """

    track = parse_version_tag(track_tag)
    accepted: list[VersionTag] = []
    for value in values:
        candidate = parse_version_tag(value)
        if candidate is None:
            continue
        if track is None:
            if track_tag != "latest" or candidate.suffix or len(candidate.version) < 2:
                continue
        else:
            prefix = track.version
            if candidate.version[: len(prefix)] != prefix:
                continue
            if candidate.family != track.family or len(candidate.version) <= len(prefix):
                continue
        accepted.append(candidate)
    accepted.sort(
        key=lambda item: (*item.version, *(0 for _ in range(3 - len(item.version)))),
        reverse=True,
    )
    return [item.value for item in accepted[: max(1, limit)]]


def apply_update_ignores(
    results: Iterable[Mapping[str, Any]],
    ignored_updates: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply exact-target reminder ignores to fresh registry audit results.

    An ignore remains active only while the tracked target digest is exactly
    unchanged. New registry content therefore reappears automatically. This
    function affects freshness reminders only; vulnerability evidence is held
    separately and cannot be suppressed here.

    Args:
        results: Fresh registry audit results.
        ignored_updates: Persisted identifier-to-ignore mapping.

    Returns:
        Updated result dictionaries and non-expired ignore entries.
    """

    active = dict(ignored_updates)
    updated: list[dict[str, Any]] = []
    observed: set[str] = set()
    for raw_result in results:
        result = dict(raw_result)
        identifier = str(result.get("identifier", ""))
        if result.get("kind") != "infrastructure" or not identifier:
            updated.append(result)
            continue
        observed.add(identifier)
        entry = active.get(identifier)
        target_digest = result.get("trackedDigest")
        ignored_digest = entry.get("digest") if isinstance(entry, Mapping) else None
        if result.get("status") == "update" and ignored_digest == target_digest:
            result["status"] = "ignored"
            result["ignoredReason"] = str(entry.get("reason", "operator snooze"))
        elif entry is not None and ignored_digest != target_digest:
            active.pop(identifier, None)
        updated.append(result)
    active = {
        key: value for key, value in active.items() if key in observed
    }
    return updated, active


def store_exact_digest_ignore(
    payload: MutableMapping[str, Any],
    identifier: str,
    label: str,
    digest: str,
    reason: str,
) -> None:
    """Store one public reminder snooze in an image-audit cache payload.

    Args:
        payload: Mutable audit-cache payload.
        identifier: Stable infrastructure record identifier.
        label: Operator-facing service label.
        digest: Exact target SHA-256 digest being ignored.
        reason: Public operator reason; must not contain secrets.

    Returns:
        Nothing.

    Raises:
        ValueError: If identity, digest, or reason is missing or unsafe.
    """

    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier):
        raise ValueError("Ignore identifier is invalid.")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Ignore target must be an exact SHA-256 digest.")
    normalized_reason = " ".join(reason.split())
    if not normalized_reason or len(normalized_reason) > 160:
        raise ValueError("Ignore reason must contain 1-160 visible characters.")
    existing = payload.get("ignoredInfrastructureUpdates")
    ignores = dict(existing) if isinstance(existing, Mapping) else {}
    ignores[identifier] = {
        "label": label[:80],
        "digest": digest,
        "reason": normalized_reason,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    payload["ignoredInfrastructureUpdates"] = ignores


def clear_exact_digest_ignore(
    payload: MutableMapping[str, Any], identifier: str
) -> bool:
    """Remove one persisted infrastructure reminder snooze.

    Args:
        payload: Mutable audit-cache payload.
        identifier: Stable infrastructure record identifier.

    Returns:
        ``True`` when an entry was removed; otherwise ``False``.
    """

    existing = payload.get("ignoredInfrastructureUpdates")
    if not isinstance(existing, Mapping) or identifier not in existing:
        return False
    ignores = dict(existing)
    del ignores[identifier]
    payload["ignoredInfrastructureUpdates"] = ignores
    return True


__all__ = [
    "VersionTag",
    "apply_update_ignores",
    "clear_exact_digest_ignore",
    "compatible_release_tags",
    "parse_version_tag",
    "store_exact_digest_ignore",
]
