"""
Module: registry_image_tool.py

Description:
    Provides registry-backed Docker image discovery for the Swarm operator
    menus. Stable application tags are enumerated through the OCI Distribution
    API, exact selections are resolved to immutable digests and verified for a
    requested platform, and tracked infrastructure tags are compared with
    deployed or profile-pinned digests. The module also owns the small ignored
    cache used by menu overviews; it never mutates deployment configuration.

Dependencies:
    - Python standard library.
    - Docker Buildx only as a credential-aware exact-inspection fallback.
    - scripts/terminal_status.py for TTY-aware semantic status output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from terminal_status import colorize_status_text


SEMVER_PATTERN = re.compile(r"^(?P<major>0|[1-9][0-9]*)\."
                            r"(?P<minor>0|[1-9][0-9]*)\."
                            r"(?P<patch>0|[1-9][0-9]*)$")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
class RegistryToolError(RuntimeError):
    """Report a safe operator-facing registry or input failure."""


@dataclass(frozen=True)
class RepositoryLocation:
    """Normalized registry endpoint and repository path.

    Attributes:
        original: Repository text supplied by the operator.
        registry: Registry hostname used for API requests.
        repository: Registry-local repository path.
    """

    original: str
    registry: str
    repository: str

    @property
    def api_base(self) -> str:
        """Return the HTTPS Distribution API origin.

        Returns:
            HTTPS registry origin, including Docker Hub's API hostname.
        """

        if self.registry in {"docker.io", "index.docker.io"}:
            return "https://registry-1.docker.io"
        return f"https://{self.registry}"


@dataclass(frozen=True)
class ManifestEvidence:
    """Immutable evidence resolved for one repository tag.

    Attributes:
        digest: Registry manifest or index digest.
        platforms: Declared OS/architecture strings.
        source: Resolution mechanism used for the evidence.
    """

    digest: str
    platforms: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class AuditRecord:
    """One application or infrastructure image audit request.

    Attributes:
        identifier: Stable service identifier.
        label: Human-readable service name.
        kind: Either ``application`` or ``infrastructure``.
        repository: Repository without a tag.
        current: Configured version or current image reference.
        track_tag: Infrastructure update channel, empty for applications.
    """

    identifier: str
    label: str
    kind: str
    repository: str
    current: str
    track_tag: str


def semver_key(value: str) -> tuple[int, int, int] | None:
    """Parse one stable semantic-version tag.

    Args:
        value: Candidate ``MAJOR.MINOR.PATCH`` tag without a prefix.

    Returns:
        Numeric semantic-version tuple, or ``None`` for non-stable tags.
    """

    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        return None
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def stable_tags(values: Iterable[str]) -> list[str]:
    """Return unique stable SemVer tags in descending numeric order.

    Args:
        values: Registry tag strings.

    Returns:
        Deduplicated stable tags ordered from highest to lowest.
    """

    unique = {value for value in values if semver_key(value) is not None}
    return sorted(unique, key=lambda value: (semver_key(value), value), reverse=True)


def normalize_repository(value: str) -> RepositoryLocation:
    """Normalize a Docker repository without accepting a tag or digest.

    Args:
        value: Docker repository such as ``postgres`` or ``owner/image``.

    Returns:
        Normalized registry endpoint and repository path.

    Raises:
        RegistryToolError: If the value includes a tag, digest, or unsafe text.
    """

    candidate = value.strip().removeprefix("https://").removeprefix("http://")
    if not candidate or "@" in candidate or any(char.isspace() for char in candidate):
        raise RegistryToolError(f"Unsafe image repository: {value!r}")
    parts = candidate.split("/")
    first = parts[0]
    has_registry = "." in first or ":" in first or first == "localhost"
    registry = first if has_registry else "docker.io"
    repository_parts = parts[1:] if has_registry else parts
    if registry == "docker.io" and len(repository_parts) == 1:
        repository_parts.insert(0, "library")
    repository = "/".join(repository_parts)
    if not re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", repository):
        raise RegistryToolError(f"Unsafe image repository: {value!r}")
    return RepositoryLocation(value.strip(), registry, repository)


def repository_from_reference(value: str) -> str:
    """Remove a tag or digest from one Docker image reference.

    Args:
        value: Docker image reference.

    Returns:
        Repository portion suitable for registry requests.
    """

    without_digest = value.split("@", 1)[0]
    slash = without_digest.rfind("/")
    colon = without_digest.rfind(":")
    if colon > slash:
        return without_digest[:colon]
    return without_digest


def digest_from_reference(value: str) -> str | None:
    """Extract an immutable SHA-256 digest from an image reference.

    Args:
        value: Docker image reference or digest text.

    Returns:
        Digest string, or ``None`` when no digest is present.
    """

    match = DIGEST_PATTERN.search(value)
    return match.group(0) if match is not None else None


class DistributionClient:
    """Minimal read-only OCI Distribution client for one repository."""

    def __init__(self, location: RepositoryLocation, timeout: int = 30) -> None:
        """Initialize a repository-scoped registry client.

        Args:
            location: Normalized repository location.
            timeout: HTTP request timeout in seconds.
        """

        self.location = location
        self.timeout = timeout
        self._token: str | None = None

    def _token_from_challenge(self, challenge: str) -> str:
        """Exchange one Bearer challenge for an anonymous pull token.

        Args:
            challenge: Registry ``WWW-Authenticate`` header.

        Returns:
            Bearer token accepted for read-only repository requests.

        Raises:
            RegistryToolError: If the challenge or token response is invalid.
        """

        if not challenge.lower().startswith("bearer "):
            raise RegistryToolError("Registry requires unsupported authentication.")
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge[7:]))
        realm = fields.pop("realm", "")
        if not realm:
            raise RegistryToolError("Registry Bearer challenge has no token realm.")
        fields.setdefault(
            "scope", f"repository:{self.location.repository}:pull"
        )
        separator = "&" if urllib.parse.urlparse(realm).query else "?"
        token_url = f"{realm}{separator}{urllib.parse.urlencode(fields)}"
        try:
            with urllib.request.urlopen(token_url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as error:
            raise RegistryToolError(f"Registry token request failed: {error}") from error
        token = payload.get("token") or payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RegistryToolError("Registry token response did not contain a token.")
        return token

    def _open(self, url: str, accept: str = "application/json") -> tuple[bytes, Mapping[str, str]]:
        """Open one read-only registry URL with Bearer challenge handling.

        Args:
            url: Absolute registry API URL.
            accept: Requested response media types.

        Returns:
            Response bytes and headers.

        Raises:
            RegistryToolError: If authentication, transport, or HTTP fails.
        """

        headers = {"Accept": accept, "User-Agent": "swarm-image-audit/1"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as error:
            if error.code == 401 and not self._token:
                challenge = error.headers.get("WWW-Authenticate", "")
                self._token = self._token_from_challenge(challenge)
                return self._open(url, accept)
            detail = error.read(512).decode("utf-8", errors="replace")
            raise RegistryToolError(
                f"Registry HTTP {error.code} for {url}: {detail or error.reason}"
            ) from error
        except OSError as error:
            raise RegistryToolError(f"Registry request failed for {url}: {error}") from error

    def tags(self) -> list[str]:
        """Enumerate all repository tags exposed by the registry.

        Returns:
            Registry tag strings in registry-provided order.

        Raises:
            RegistryToolError: If enumeration is unavailable or malformed.
        """

        repository = urllib.parse.quote(self.location.repository, safe="/")
        url = f"{self.location.api_base}/v2/{repository}/tags/list?n=10000"
        values: list[str] = []
        for _ in range(20):
            body, headers = self._open(url)
            try:
                payload = json.loads(body.decode("utf-8"))
            except ValueError as error:
                raise RegistryToolError("Registry tag response was not JSON.") from error
            page = payload.get("tags") or []
            if not isinstance(page, list) or any(not isinstance(tag, str) for tag in page):
                raise RegistryToolError("Registry tag response had an invalid tags list.")
            values.extend(page)
            next_url = _next_link(headers.get("Link", ""), url)
            if next_url is None:
                return values
            url = next_url
        raise RegistryToolError("Registry tag pagination exceeded the safety limit.")

    def manifest(self, tag: str) -> ManifestEvidence:
        """Resolve one exact tag to digest and declared platforms.

        Args:
            tag: Exact registry tag.

        Returns:
            Immutable manifest evidence.

        Raises:
            RegistryToolError: If the tag or manifest metadata is unavailable.
        """

        repository = urllib.parse.quote(self.location.repository, safe="/")
        reference = urllib.parse.quote(tag, safe="._-")
        url = f"{self.location.api_base}/v2/{repository}/manifests/{reference}"
        body, headers = self._open(url, MANIFEST_ACCEPT)
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError as error:
            raise RegistryToolError("Registry manifest response was not JSON.") from error
        digest = headers.get("Docker-Content-Digest") or (
            "sha256:" + hashlib.sha256(body).hexdigest()
        )
        platforms = self._manifest_platforms(payload, repository)
        return ManifestEvidence(digest, tuple(sorted(set(platforms))), "registry-api")

    def _manifest_platforms(self, payload: Mapping[str, Any], repository: str) -> list[str]:
        """Derive platform strings from an index or image config.

        Args:
            payload: Decoded manifest or index object.
            repository: URL-escaped repository path.

        Returns:
            Declared platform strings, possibly empty for legacy manifests.
        """

        manifests = payload.get("manifests")
        if isinstance(manifests, list):
            return [
                _platform_text(entry.get("platform", {}))
                for entry in manifests
                if isinstance(entry, Mapping) and _platform_text(entry.get("platform", {}))
            ]
        config = payload.get("config")
        if not isinstance(config, Mapping) or not isinstance(config.get("digest"), str):
            return []
        digest = urllib.parse.quote(config["digest"], safe=":")
        url = f"{self.location.api_base}/v2/{repository}/blobs/{digest}"
        body, _ = self._open(url)
        try:
            config_payload = json.loads(body.decode("utf-8"))
        except ValueError:
            return []
        platform = _platform_text(config_payload)
        return [platform] if platform else []


def _platform_text(value: Mapping[str, Any]) -> str:
    """Format one OCI platform object.

    Args:
        value: Mapping containing OS, architecture, and optional variant.

    Returns:
        Slash-delimited platform text, or an empty string when incomplete.
    """

    operating_system = value.get("os")
    architecture = value.get("architecture")
    if not isinstance(operating_system, str) or not isinstance(architecture, str):
        return ""
    variant = value.get("variant")
    suffix = f"/{variant}" if isinstance(variant, str) and variant else ""
    return f"{operating_system}/{architecture}{suffix}"


def _next_link(header: str, current_url: str) -> str | None:
    """Resolve an OCI pagination Link header.

    Args:
        header: Raw HTTP Link header.
        current_url: URL used for relative-link resolution.

    Returns:
        Absolute next-page URL, or ``None`` when pagination is complete.
    """

    for part in header.split(","):
        match = re.search(r"<([^>]+)>\s*;\s*rel=\"?next\"?", part.strip())
        if match:
            return urllib.parse.urljoin(current_url, match.group(1))
    return None


def _docker_manifest_fallback(repository: str, tag: str) -> ManifestEvidence:
    """Use Docker credentials to inspect an exact tag when HTTP auth fails.

    Args:
        repository: Docker repository without a tag.
        tag: Exact tag.

    Returns:
        Digest and any platforms printed by Buildx.

    Raises:
        RegistryToolError: If Docker cannot inspect the image.
    """

    reference = f"{repository}:{tag}"
    completed = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RegistryToolError(f"Docker could not inspect {reference}: {detail}")
    digest_match = DIGEST_PATTERN.search(completed.stdout)
    if digest_match is None:
        raise RegistryToolError(f"Docker returned no digest for {reference}.")
    platforms = tuple(sorted(set(re.findall(r"linux/[a-z0-9_]+(?:/[a-z0-9]+)?", completed.stdout))))
    return ManifestEvidence(digest_match.group(0), platforms, "docker-buildx")


def inspect_tag(repository: str, tag: str) -> ManifestEvidence:
    """Resolve one exact image tag using HTTP and Docker fallback.

    Args:
        repository: Docker repository without a tag.
        tag: Exact tag.

    Returns:
        Immutable manifest evidence.

    Raises:
        RegistryToolError: If neither mechanism can inspect the tag.
    """

    location = normalize_repository(repository)
    try:
        return DistributionClient(location).manifest(tag)
    except RegistryToolError as registry_error:
        try:
            return _docker_manifest_fallback(repository, tag)
        except (RegistryToolError, OSError, subprocess.SubprocessError) as docker_error:
            raise RegistryToolError(
                f"{registry_error} Docker credential fallback also failed: {docker_error}"
            ) from docker_error


def enumerate_stable_tags(repository: str) -> list[str]:
    """Enumerate stable semantic-version tags for one repository.

    Args:
        repository: Docker repository without a tag.

    Returns:
        Stable tags from highest to lowest.

    Raises:
        RegistryToolError: If public tag enumeration is unavailable.
    """

    location = normalize_repository(repository)
    return stable_tags(DistributionClient(location).tags())


def parse_record(value: str) -> AuditRecord:
    """Parse one shell-safe pipe-delimited audit record.

    Args:
        value: ``id|label|kind|repository|current|track-tag`` text.

    Returns:
        Validated audit record.

    Raises:
        RegistryToolError: If fields are missing or unsupported.
    """

    fields = value.split("|")
    if len(fields) != 6:
        raise RegistryToolError("Audit records require exactly six fields.")
    record = AuditRecord(*fields)
    if record.kind not in {"application", "infrastructure"}:
        raise RegistryToolError(f"Unsupported audit record kind: {record.kind}")
    if not record.identifier or not record.label or not record.current:
        raise RegistryToolError("Audit record identity and current value are required.")
    return record


def _audit_application(record: AuditRecord, platform: str) -> dict[str, Any]:
    """Audit one application repository and configured tag.

    Args:
        record: Application audit request.
        platform: Required deployment platform.

    Returns:
        Serializable registry evidence and update status.
    """

    tags = enumerate_stable_tags(record.repository)
    if not tags:
        raise RegistryToolError("No stable MAJOR.MINOR.PATCH tags were published.")
    current_evidence = inspect_tag(record.repository, record.current)
    current_key = semver_key(record.current)
    highest = tags[0]
    highest_key = semver_key(highest)
    platform_verified = platform in current_evidence.platforms
    update_available = (
        current_key is not None and highest_key is not None and highest_key > current_key
    )
    status = "update" if update_available else "ok"
    if current_key is None or not platform_verified:
        status = "unknown"
    return {
        **asdict(record),
        "status": status,
        "highestStable": highest,
        "stableTagCount": len(tags),
        "currentDigest": current_evidence.digest,
        "platformVerified": platform_verified,
        "platforms": list(current_evidence.platforms),
        "evidenceSource": current_evidence.source,
    }


def _audit_infrastructure(record: AuditRecord, platform: str) -> dict[str, Any]:
    """Compare one pinned infrastructure digest with its tracked tag.

    Args:
        record: Infrastructure audit request.
        platform: Required deployment platform.

    Returns:
        Serializable digest comparison evidence.
    """

    if not record.track_tag:
        raise RegistryToolError("Infrastructure image has no tracked update tag.")
    repository = record.repository or repository_from_reference(record.current)
    current_digest = digest_from_reference(record.current)
    evidence = inspect_tag(repository, record.track_tag)
    platform_verified = platform in evidence.platforms
    status = "unknown"
    if current_digest is not None and platform_verified:
        status = "ok" if current_digest == evidence.digest else "update"
    return {
        **asdict(record),
        "repository": repository,
        "status": status,
        "trackedDigest": evidence.digest,
        "currentDigest": current_digest,
        "platformVerified": platform_verified,
        "platforms": list(evidence.platforms),
        "evidenceSource": evidence.source,
    }


def audit_records(records: Iterable[AuditRecord], platform: str) -> list[dict[str, Any]]:
    """Audit records independently so one registry failure stays local.

    Args:
        records: Application and infrastructure records.
        platform: Required deployment platform.

    Returns:
        Serializable result mappings, including safe error summaries.
    """

    results: list[dict[str, Any]] = []
    for record in records:
        try:
            result = (
                _audit_application(record, platform)
                if record.kind == "application"
                else _audit_infrastructure(record, platform)
            )
        except RegistryToolError as error:
            result = {**asdict(record), "status": "unknown", "error": str(error)}
        results.append(result)
    return results


def write_cache(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically write public image-audit metadata.

    Args:
        path: Ignored cache destination.
        payload: JSON-compatible audit object.

    Returns:
        Nothing.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_cache(path: Path) -> dict[str, Any]:
    """Read one audit cache without trusting malformed content.

    Args:
        path: Cache path.

    Returns:
        Parsed cache mapping, or an empty mapping when unavailable.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timestamp_is_fresh(value: object, max_age_hours: int) -> bool | None:
    """Evaluate one cached UTC timestamp against the evidence age limit.

    Args:
        value: ISO-8601 timestamp candidate.
        max_age_hours: Maximum accepted age in hours.

    Returns:
        ``True`` when fresh, ``False`` when stale, or ``None`` when invalid.
    """

    if not isinstance(value, str):
        return None
    try:
        generated = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if generated.tzinfo is None:
        return None
    age = dt.datetime.now(dt.timezone.utc) - generated
    return age <= dt.timedelta(hours=max_age_hours)


def cache_summary(path: Path, max_age_hours: int) -> str:
    """Summarize cached registry and security state for a menu line.

    Args:
        path: Audit cache path.
        max_age_hours: Age after which evidence is stale.

    Returns:
        Pipe-delimited ``level|text`` status for shell colorization.
    """

    payload = read_cache(path)
    generated_at = payload.get("generatedAt")
    records = payload.get("records")
    if not isinstance(generated_at, str) or not isinstance(records, list):
        return "off|[UNKNOWN] registry/security audit not run"
    registry_fresh = _timestamp_is_fresh(generated_at, max_age_hours)
    if registry_fresh is None:
        return "off|[UNKNOWN] image-audit cache is invalid"
    if not registry_fresh:
        return "warning|[STALE] image audit is older than configured cache age"
    updates = sum(item.get("status") == "update" for item in records if isinstance(item, dict))
    unknown = sum(item.get("status") == "unknown" for item in records if isinstance(item, dict))
    security = payload.get("security")
    security_status = security.get("status") if isinstance(security, dict) else "unknown"
    security_fresh = (
        _timestamp_is_fresh(security.get("checkedAt"), max_age_hours)
        if isinstance(security, dict)
        else None
    )
    if updates:
        return f"warning|[UPDATE] {updates} registry image update(s) available"
    if security_status == "warning":
        return "warning|[WARN] fixable HIGH/CRITICAL vulnerabilities found"
    if unknown:
        return f"warning|[UNKNOWN] {unknown} image check(s) need attention"
    if security_status == "unknown" and security_fresh is True:
        return "warning|[UNKNOWN] image security scan did not complete"
    if isinstance(security, dict) and security_fresh is None:
        return "warning|[UNKNOWN] image security cache is invalid"
    if security_fresh is False:
        return "warning|[STALE] image security scan needs to be rerun"
    if security_status == "ok" and security_fresh is True:
        return "ok|[OK] registry and security evidence current"
    return "ok|[OK] registry images current; security scan not run"


def update_security_cache(path: Path, status: str, summary: str) -> None:
    """Attach one scanner result to existing registry evidence.

    Args:
        path: Audit cache path.
        status: ``ok``, ``warning``, or ``unknown``.
        summary: Short public scanner summary.

    Returns:
        Nothing.

    Raises:
        RegistryToolError: If status is unsupported.
    """

    if status not in {"ok", "warning", "unknown"}:
        raise RegistryToolError(f"Unsupported security status: {status}")
    payload = read_cache(path)
    payload["security"] = {
        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status,
        "summary": summary,
    }
    write_cache(path, payload)


def _print_audit_result(result: Mapping[str, Any]) -> None:
    """Print one compact human-readable audit result.

    Args:
        result: Serializable record result.

    Returns:
        Nothing.
    """

    status = str(result.get("status", "unknown")).upper()
    level = "ok" if status == "OK" else "warning"
    if status == "ERROR":
        level = "error"
    label = result.get("label", result.get("identifier", "image"))
    current = result.get("current", "unknown")
    if result.get("kind") == "application":
        target = result.get("highestStable", "unknown")
        line = f"[{status}] {label}: {current} -> highest published {target}"
    else:
        tag = result.get("track_tag", "unknown")
        current_digest = result.get("currentDigest") or "unresolved deployed digest"
        target_digest = result.get("trackedDigest") or "unknown"
        line = (
            f"[{status}] {label}: track {tag}; "
            f"{current_digest} -> {target_digest}"
        )
    print(colorize_status_text(line, level, sys.stdout))
    if result.get("platformVerified") is False:
        warning = (
            "        [WARN] required platform was not declared by the resolved image"
        )
        print(colorize_status_text(warning, "warning", sys.stdout))
    if result.get("error"):
        error_text = f"        [ERROR] {result['error']}"
        print(colorize_status_text(error_text, "error", sys.stdout))


def _command_stable_tags(arguments: argparse.Namespace) -> int:
    """Execute the stable-tags CLI command.

    Args:
        arguments: Parsed command arguments.

    Returns:
        Process exit status.
    """

    for tag in enumerate_stable_tags(arguments.repository):
        print(tag)
    return 0


def _command_verify(arguments: argparse.Namespace) -> int:
    """Execute exact tag/digest/platform verification.

    Args:
        arguments: Parsed command arguments.

    Returns:
        Zero when the platform is present; otherwise nonzero.
    """

    evidence = inspect_tag(arguments.repository, arguments.tag)
    payload = {
        "repository": arguments.repository,
        "tag": arguments.tag,
        "digest": evidence.digest,
        "platforms": list(evidence.platforms),
        "platformVerified": arguments.platform in evidence.platforms,
        "source": evidence.source,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["platformVerified"] else 2


def _command_audit(arguments: argparse.Namespace) -> int:
    """Execute registry audit and cache persistence.

    Args:
        arguments: Parsed command arguments.

    Returns:
        Zero after all independent checks complete.
    """

    records = [parse_record(value) for value in arguments.record]
    results = audit_records(records, arguments.platform)
    cache_path = Path(arguments.cache)
    previous = read_cache(cache_path)
    payload = {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "platform": arguments.platform,
        "records": results,
    }
    if isinstance(previous.get("security"), dict):
        payload["security"] = previous["security"]
    write_cache(cache_path, payload)
    for result in results:
        _print_audit_result(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        Configured top-level argument parser.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    tags_parser = commands.add_parser("stable-tags")
    tags_parser.add_argument("--repository", required=True)
    tags_parser.set_defaults(handler=_command_stable_tags)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--repository", required=True)
    verify_parser.add_argument("--tag", required=True)
    verify_parser.add_argument("--platform", default="linux/amd64")
    verify_parser.set_defaults(handler=_command_verify)

    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--cache", required=True)
    audit_parser.add_argument("--record", action="append", default=[], required=True)
    audit_parser.add_argument("--platform", default="linux/amd64")
    audit_parser.set_defaults(handler=_command_audit)

    summary_parser = commands.add_parser("cache-summary")
    summary_parser.add_argument("--cache", required=True)
    summary_parser.add_argument("--max-age-hours", type=int, default=24)
    summary_parser.set_defaults(
        handler=lambda args: print(
            cache_summary(Path(args.cache), args.max_age_hours)
        )
        or 0
    )

    security_parser = commands.add_parser("security-result")
    security_parser.add_argument("--cache", required=True)
    security_parser.add_argument("--status", required=True)
    security_parser.add_argument("--summary", required=True)
    security_parser.set_defaults(
        handler=lambda args: update_security_cache(
            Path(args.cache), args.status, args.summary
        )
        or 0
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the registry image tool.

    Args:
        argv: Optional argument list; defaults to process arguments.

    Returns:
        Process exit status with safe diagnostics on stderr.
    """

    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except (RegistryToolError, OSError, subprocess.SubprocessError) as error:
        message = colorize_status_text(f"[ERROR] {error}", "error", sys.stderr)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
