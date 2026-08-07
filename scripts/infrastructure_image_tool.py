"""
Module: infrastructure_image_tool.py

Description:
    Reports current and available infrastructure-image releases, resolves
    compatibility-track targets to immutable digests, and manages exact-digest
    reminder snoozes. It never changes deployment files or Docker services;
    repository-specific menu adapters own those transactional effects.

Dependencies:
    - Python standard library.
    - registry_image_tool.py for read-only registry access and cache I/O.
    - infrastructure_image_policy.py for compatibility and ignore policy.
    - infrastructure_image_metadata.py for immutable-image version fallback.
    - terminal_status.py for TTY-safe status colors.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from infrastructure_image_policy import (
    clear_exact_digest_ignore,
    compatible_release_tags,
    store_exact_digest_ignore,
)
from infrastructure_image_metadata import release_version_from_image
from registry_image_tool import (
    DistributionClient,
    RegistryToolError,
    digest_from_reference,
    inspect_tag,
    normalize_repository,
    read_cache,
    repository_from_reference,
    write_cache,
)
from terminal_status import print_status


@dataclass(frozen=True)
class InfrastructureRecord:
    """One profile-driven infrastructure-image operation record.

    Attributes:
        identifier: Stable cache and menu identifier.
        label: Operator-facing service label.
        service: Swarm service suffix.
        environment_key: Public exact-image override key.
        current: Deployed or configured exact image reference.
        track_tag: Profile-approved compatibility channel.
        state_kind: ``database``, ``cache``, or ``management-ui``.
        documentation_url: Official upgrade or release documentation.
    """

    identifier: str
    label: str
    service: str
    environment_key: str
    current: str
    track_tag: str
    state_kind: str
    documentation_url: str


@dataclass(frozen=True)
class ResolvedInfrastructure:
    """Current and tracked immutable evidence for one infrastructure image.

    Attributes:
        record: Source adapter record.
        repository: Normalized registry repository.
        current_digest: Current manifest digest when resolvable.
        target_digest: Track-tag manifest digest.
        target_reference: Repository plus immutable target digest.
        status: ``ok`` when current, otherwise ``update`` or ``unknown``.
    """

    record: InfrastructureRecord
    repository: str
    current_digest: str | None
    target_digest: str
    target_reference: str
    status: str


@dataclass(frozen=True)
class ReleaseEvidence:
    """One compatible release tag resolved to immutable registry evidence.

    Attributes:
        tag: Published release tag.
        digest: Manifest or index digest.
        platform_verified: Whether the required platform is declared.
    """

    tag: str
    digest: str
    platform_verified: bool


def parse_record(value: str) -> InfrastructureRecord:
    """Parse one shell-safe infrastructure operation record.

    Args:
        value: Eight pipe-delimited adapter fields.

    Returns:
        Validated infrastructure record.

    Raises:
        ValueError: If field count, identity, key, state, or URL is invalid.
    """

    fields = value.split("|")
    if len(fields) != 8 or any("\n" in field or "\r" in field for field in fields):
        raise ValueError("Infrastructure records require exactly eight safe fields.")
    record = InfrastructureRecord(*fields)
    if not record.identifier or not record.label or not record.current or not record.track_tag:
        raise ValueError("Infrastructure identity, current image, and track are required.")
    if (
        record.environment_key != record.environment_key.upper()
        or not record.environment_key.replace("_", "").isalnum()
    ):
        raise ValueError("Infrastructure environment key is invalid.")
    if record.state_kind not in {"database", "cache", "management-ui"}:
        raise ValueError(f"Unsupported infrastructure state kind: {record.state_kind}")
    if not record.documentation_url.startswith("https://"):
        raise ValueError("Infrastructure documentation URL must use HTTPS.")
    return record


def _tag_from_reference(value: str) -> str | None:
    """Extract a mutable tag from an image reference without a digest.

    Args:
        value: Docker image reference.

    Returns:
        Tag text, or ``None`` when absent or digest-pinned.
    """

    if "@" in value:
        return None
    slash = value.rfind("/")
    colon = value.rfind(":")
    return value[colon + 1 :] if colon > slash else None


def _resolve_current_digest(repository: str, current: str) -> str | None:
    """Resolve the current exact digest from a digest or tag reference.

    Args:
        repository: Normalized repository.
        current: Current image reference.

    Returns:
        SHA-256 digest, or ``None`` when no tag can be resolved.
    """

    digest = digest_from_reference(current)
    if digest is not None:
        return digest
    tag = _tag_from_reference(current)
    return inspect_tag(repository, tag).digest if tag else None


def resolve_record(value: str, platform: str) -> ResolvedInfrastructure:
    """Resolve current and compatibility-track evidence for one record.

    Args:
        value: Pipe-delimited infrastructure record.
        platform: Required OCI platform.

    Returns:
        Immutable current/target comparison.

    Raises:
        RegistryToolError: If the target tag is absent or lacks the platform.
        ValueError: If the record is malformed.
    """

    record = parse_record(value)
    repository = repository_from_reference(record.current)
    target = inspect_tag(repository, record.track_tag)
    if platform not in target.platforms:
        raise RegistryToolError(
            f"{repository}:{record.track_tag} does not declare {platform}."
        )
    current_digest = _resolve_current_digest(repository, record.current)
    status = "unknown" if current_digest is None else (
        "ok" if current_digest == target.digest else "update"
    )
    return ResolvedInfrastructure(
        record=record,
        repository=repository,
        current_digest=current_digest,
        target_digest=target.digest,
        target_reference=f"{repository}@{target.digest}",
        status=status,
    )


def _release_evidence(
    resolved: ResolvedInfrastructure,
    platform: str,
    limit: int,
) -> list[ReleaseEvidence]:
    """Resolve recent compatible release tags for one infrastructure image.

    Args:
        resolved: Current/target registry evidence.
        platform: Required OCI platform.
        limit: Maximum compatible tags inspected.

    Returns:
        Successfully inspected release evidence in descending version order.
    """

    client = DistributionClient(normalize_repository(resolved.repository))
    tags = compatible_release_tags(
        client.tags(), resolved.record.track_tag, limit=limit
    )
    releases: list[ReleaseEvidence] = []
    for tag in tags:
        try:
            evidence = inspect_tag(resolved.repository, tag)
        except RegistryToolError:
            continue
        releases.append(
            ReleaseEvidence(tag, evidence.digest, platform in evidence.platforms)
        )
    return releases


def _digest_aliases(
    releases: Iterable[ReleaseEvidence], digest: str | None
) -> list[str]:
    """Return release tags that resolve to one exact digest.

    Args:
        releases: Inspected compatible releases.
        digest: Digest to match, or ``None``.

    Returns:
        Matching release tags in input order.
    """

    if digest is None:
        return []
    return [release.tag for release in releases if release.digest == digest]


def _version_label(values: list[str]) -> str:
    """Format a compact release-alias label.

    Args:
        values: Matching release tags.

    Returns:
        Up to three aliases, or an explicit unresolved marker.
    """

    return ", ".join(values[:3]) if values else "not identified from recent tags"


def _metadata_release_version(
    resolved: ResolvedInfrastructure,
    platform: str,
) -> str | None:
    """Best-effort release lookup from an immutable image configuration.

    Args:
        resolved: Current/target registry evidence.
        platform: Required OCI platform.

    Returns:
        Product version, or ``None`` when metadata is absent/unavailable.
    """

    if resolved.current_digest is None:
        return None
    try:
        return release_version_from_image(
            resolved.repository,
            resolved.current_digest,
            platform,
            resolved.record.identifier,
        )
    except RegistryToolError:
        return None


def print_report(value: str, platform: str, limit: int) -> None:
    """Print detailed current and available version evidence for one record.

    Args:
        value: Pipe-delimited infrastructure record.
        platform: Required OCI platform.
        limit: Maximum recent compatible tags inspected.

    Returns:
        Nothing.
    """

    resolved = resolve_record(value, platform)
    releases = _release_evidence(resolved, platform, limit)
    current_aliases = _digest_aliases(releases, resolved.current_digest)
    target_aliases = _digest_aliases(releases, resolved.target_digest)
    metadata_version = (
        None if current_aliases else _metadata_release_version(resolved, platform)
    )
    current_version = (
        _version_label(current_aliases)
        if metadata_version is None
        else f"{metadata_version} (image metadata)"
    )
    print("")
    print(resolved.record.label)
    print("-" * len(resolved.record.label))
    print(f"  Deployed/configured: {resolved.record.current}")
    print(f"  Repository:          {resolved.repository}")
    print(f"  Compatibility track: {resolved.record.track_tag}")
    print(f"  Current release:     {current_version}")
    print(f"  Track target:        {_version_label(target_aliases)}")
    print(f"  Target digest:       {resolved.target_digest}")
    if resolved.status == "ok":
        print_status("[OK] Current digest matches the compatibility track.", "ok")
    elif resolved.status == "update":
        print_status("[UPDATE] Compatible immutable refresh available.", "warning")
    else:
        print_status("[UNKNOWN] Current digest could not be resolved.", "warning")
    print("  Recent compatible published tags:")
    for release in releases[:10]:
        markers = []
        if release.digest == resolved.current_digest:
            markers.append("current")
        if release.digest == resolved.target_digest:
            markers.append("track target")
        if not release.platform_verified:
            markers.append(f"missing {platform}")
        suffix = f" ({', '.join(markers)})" if markers else ""
        print(f"    - {release.tag}{suffix}")
    print(f"  Upgrade guidance: {resolved.record.documentation_url}")


def _candidate_line(
    resolved: ResolvedInfrastructure, status_override: str | None = None
) -> str:
    """Serialize resolved evidence for the shared Bash update menu.

    Args:
        resolved: Current/target comparison.
        status_override: Optional operator-facing status such as ``ignored``.

    Returns:
        Thirteen pipe-delimited safe fields.
    """

    record = resolved.record
    fields = (
        record.identifier,
        record.label,
        record.service,
        record.environment_key,
        record.current,
        record.track_tag,
        record.state_kind,
        resolved.repository,
        resolved.target_reference,
        resolved.current_digest or "",
        resolved.target_digest,
        status_override or resolved.status,
        record.documentation_url,
    )
    return "|".join(fields)


def _command_report(arguments: argparse.Namespace) -> int:
    """Execute the detailed infrastructure version report command.

    Args:
        arguments: Parsed CLI namespace.

    Returns:
        Zero when every record resolves; otherwise one.
    """

    status = 0
    for raw_record in arguments.record:
        try:
            label = raw_record.split("|", 2)[1] if "|" in raw_record else "image"
            print_status(f"[CHECK] Resolving {label} registry evidence...", "info")
            print_report(raw_record, arguments.platform, arguments.limit)
        except (RegistryToolError, ValueError) as error:
            label = raw_record.split("|", 2)[1] if "|" in raw_record else "image"
            print_status(f"[ERROR] {label}: {error}", "error", sys.stderr)
            status = 1
    return status


def _command_candidates(arguments: argparse.Namespace) -> int:
    """Emit machine-readable current/target records for the Bash menu.

    Args:
        arguments: Parsed CLI namespace.

    Returns:
        Zero when all records resolve; otherwise one.
    """

    status = 0
    ignores: Mapping[str, object] = {}
    if arguments.cache:
        raw_ignores = read_cache(Path(arguments.cache)).get(
            "ignoredInfrastructureUpdates"
        )
        if isinstance(raw_ignores, Mapping):
            ignores = raw_ignores
    for raw_record in arguments.record:
        try:
            resolved = resolve_record(raw_record, arguments.platform)
            entry = ignores.get(resolved.record.identifier)
            ignored_digest = (
                entry.get("digest") if isinstance(entry, Mapping) else None
            )
            override = (
                "ignored"
                if resolved.status == "update"
                and ignored_digest == resolved.target_digest
                else None
            )
            print(_candidate_line(resolved, override))
        except (RegistryToolError, ValueError) as error:
            print_status(f"[ERROR] {error}", "error", sys.stderr)
            status = 1
    return status


def _command_ignore(arguments: argparse.Namespace) -> int:
    """Persist one exact-target reminder snooze.

    Args:
        arguments: Parsed CLI namespace.

    Returns:
        Zero after atomic cache persistence.
    """

    path = Path(arguments.cache)
    payload = read_cache(path)
    store_exact_digest_ignore(
        payload,
        arguments.identifier,
        arguments.label,
        arguments.digest,
        arguments.reason,
    )
    write_cache(path, payload)
    print_status(
        f"[OK] Ignored {arguments.label} target {arguments.digest[:19]}...",
        "ok",
    )
    return 0


def _command_clear_ignore(arguments: argparse.Namespace) -> int:
    """Remove one exact-target reminder snooze.

    Args:
        arguments: Parsed CLI namespace.

    Returns:
        Zero when removed; otherwise two when no entry existed.
    """

    path = Path(arguments.cache)
    payload = read_cache(path)
    if not clear_exact_digest_ignore(payload, arguments.identifier):
        print_status("[WARN] No matching ignored reminder exists.", "warning")
        return 2
    write_cache(path, payload)
    print_status(f"[OK] Restored {arguments.identifier} update reminders.", "ok")
    return 0


def _command_list_ignores(arguments: argparse.Namespace) -> int:
    """List persisted exact-digest reminder snoozes.

    Args:
        arguments: Parsed CLI namespace.

    Returns:
        Zero after output.
    """

    payload = read_cache(Path(arguments.cache))
    ignores = payload.get("ignoredInfrastructureUpdates")
    if not isinstance(ignores, Mapping) or not ignores:
        print_status("[OK] No infrastructure update reminders are ignored.", "ok")
        return 0
    for identifier, raw_entry in sorted(ignores.items()):
        if not isinstance(raw_entry, Mapping):
            continue
        print(
            "|".join(
                (
                    str(identifier),
                    str(raw_entry.get("label", identifier)),
                    str(raw_entry.get("digest", "")),
                    str(raw_entry.get("reason", "")),
                )
            )
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the infrastructure-image command-line parser.

    Returns:
        Configured top-level argument parser.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    handlers = (
        ("report", _command_report),
        ("candidates", _command_candidates),
    )
    for name, handler in handlers:
        child = commands.add_parser(name)
        child.add_argument("--record", action="append", required=True)
        child.add_argument("--platform", default="linux/amd64")
        child.add_argument("--limit", type=int, default=12)
        child.add_argument("--cache")
        child.set_defaults(handler=handler)
    ignore = commands.add_parser("ignore")
    ignore.add_argument("--cache", required=True)
    ignore.add_argument("--id", dest="identifier", required=True)
    ignore.add_argument("--label", required=True)
    ignore.add_argument("--digest", required=True)
    ignore.add_argument("--reason", required=True)
    ignore.set_defaults(handler=_command_ignore)
    clear = commands.add_parser("clear-ignore")
    clear.add_argument("--cache", required=True)
    clear.add_argument("--id", dest="identifier", required=True)
    clear.set_defaults(handler=_command_clear_ignore)
    listing = commands.add_parser("list-ignores")
    listing.add_argument("--cache", required=True)
    listing.set_defaults(handler=_command_list_ignores)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the infrastructure-image helper with safe diagnostics.

    Args:
        argv: Optional argument list; defaults to process arguments.

    Returns:
        Process exit status.
    """

    arguments = build_parser().parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except (OSError, RegistryToolError, ValueError) as error:
        print_status(f"[ERROR] {error}", "error", sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
