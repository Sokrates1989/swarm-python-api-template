"""
Module: release_profile.py

Description:
    Parses and validates the Swarm candidate-production public profile without
    evaluating shell syntax. The adapter enforces Felix API, CORS, Keycloak,
    stack, and legacy-isolation identities and can materialize a generated
    public-only root `.env` compatibility artifact after validation.

Dependencies:
    - Python 3.10 or newer standard library.

Usage:
    python scripts/release_profile.py
    python scripts/release_profile.py --materialize
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import SplitResult, urlsplit


_PROFILE_KEYS = (
    "PROFILE_SCHEMA_VERSION",
    "APP_ID",
    "APP_ENVIRONMENT",
    "APP_PROFILE",
    "BACKEND_APP_ID",
    "BACKEND_DATA_PROFILE",
    "AUTH_PROVIDER",
    "API_BASE_URL",
    "DOMAIN",
    "CORS_ORIGINS",
    "KEYCLOAK_BASE_URL",
    "KEYCLOAK_ISSUER_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_AUDIENCE",
    "KEYCLOAK_FRONTEND_CLIENT_ID",
    "STACK_NAME",
)
_PROFILE_KEY_SET = frozenset(_PROFILE_KEYS)
_ASSIGNMENT_PATTERN = re.compile(r"([A-Z][A-Z0-9_]*)=(.*)")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,127}")
_SECRET_KEY_MARKERS = (
    "API_KEY",
    "BEARER",
    "CREDENTIAL",
    "KEYSTORE",
    "PASSWORD",
    "PRIVATE",
    "SECRET",
    "TOKEN",
)
_PLACEHOLDER_MARKERS = ("change_me", "changeme", "placeholder", "todo", "xxx")
_PLACEHOLDER_HOSTS = frozenset(("example.com", "example.net", "example.org"))
_LOCAL_HOSTS = frozenset(
    ("0.0.0.0", "10.0.2.2", "host.docker.internal", "localhost")
)
_CANDIDATE_WEB_ORIGIN = "https://felix-app.fe-wi.com"
_CANDIDATE_REALM = "felix-new"
_CANDIDATE_FRONTEND_CLIENT = "felix-new-frontend"
_CANDIDATE_STACK = "felix-new"
_PROTECTED_WEB_ORIGIN = "https://felix.app.fe-wi.com"
_PROTECTED_REALMS = frozenset(("felix", "felixappnew"))
_PROTECTED_CLIENTS = frozenset(("felix-frontend", "felixappnew-frontend"))
_PROTECTED_STACKS = frozenset(("felix", "felixappnew"))
ProfileOperation = Callable[["SwarmReleaseProfile"], int]


class SwarmReleaseProfileError(ValueError):
    """Reports an unsafe, inconsistent, malformed, or missing Swarm profile."""


@dataclass(frozen=True)
class SwarmReleaseProfile:
    """Contains one validated public Swarm production profile.

    Attributes:
        path: Canonical root `prod.env` source path.
        values: Canonically ordered allowlisted public values.
        fingerprint: SHA-256 of canonical public assignments.
    """

    path: Path
    values: Mapping[str, str]
    fingerprint: str

    def safe_summary(self) -> dict[str, object]:
        """Builds non-secret evidence for validation and release receipts.

        Returns:
            App/environment identity, fingerprint, and public field names.
        """

        return {
            "appId": self.values["APP_ID"],
            "environment": self.values["APP_ENVIRONMENT"],
            "profileFingerprint": self.fingerprint,
            "publicFieldNames": list(self.values),
        }


def resolve_profile_path(root: Path, requested_path: Path | None = None) -> Path:
    """Resolves the exact repository-owned `prod.env` input path.

    Args:
        root: Swarm repository root.
        requested_path: Optional override accepted only when it resolves to the
            canonical root `prod.env`.

    Returns:
        Canonical root `prod.env` path.

    Raises:
        SwarmReleaseProfileError: If an override tries to bypass the standard
            production profile boundary.
    """

    resolved_root = root.resolve()
    expected = (resolved_root / "prod.env").resolve()
    if requested_path is not None:
        candidate = (
            requested_path
            if requested_path.is_absolute()
            else resolved_root / requested_path
        ).resolve()
        if candidate != expected:
            raise SwarmReleaseProfileError(
                f"Profile override must resolve to repository-owned path: {expected}"
            )
    return expected


def _parse_assignments(path: Path) -> dict[str, str]:
    """Parses strict public dotenv data without shell evaluation.

    Args:
        path: Root production profile to read.

    Returns:
        Canonically ordered public value mapping.

    Raises:
        SwarmReleaseProfileError: If the file is absent, non-UTF-8, malformed,
            duplicated, unknown, secret-looking, or incomplete.
        OSError: If another filesystem read failure occurs.
    """

    if not path.is_file():
        raise SwarmReleaseProfileError(
            f"Profile is missing: {path}. Copy prod.env.example and replace placeholders."
        )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise SwarmReleaseProfileError(
            f"{path}: profile must be valid UTF-8."
        ) from error

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT_PATTERN.fullmatch(raw_line)
        if match is None:
            raise SwarmReleaseProfileError(
                f"{path}:{line_number}: expected one unquoted KEY=value assignment."
            )
        key, value = match.groups()
        if any(marker in key for marker in _SECRET_KEY_MARKERS):
            raise SwarmReleaseProfileError(
                f"{path}:{line_number}: secret-looking public key is forbidden: {key}"
            )
        if key not in _PROFILE_KEY_SET:
            raise SwarmReleaseProfileError(
                f"{path}:{line_number}: unknown key: {key}"
            )
        if key in values:
            raise SwarmReleaseProfileError(
                f"{path}:{line_number}: duplicate key: {key}"
            )
        if not value or value != value.strip():
            raise SwarmReleaseProfileError(
                f"{path}:{line_number}: {key} must be non-empty without edge whitespace."
            )
        values[key] = value

    missing = [key for key in _PROFILE_KEYS if key not in values]
    if missing:
        raise SwarmReleaseProfileError(
            f"{path}: missing required public keys: {', '.join(missing)}"
        )
    return {key: values[key] for key in _PROFILE_KEYS}


def _is_placeholder(value: str) -> bool:
    """Reports whether a value contains an obvious placeholder.

    Args:
        value: Public profile text.

    Returns:
        True for a common placeholder marker; otherwise False.
    """

    lowered = value.casefold()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_non_public_host(hostname: str) -> bool:
    """Reports whether a host is local, emulator-only, private, or link-local.

    Args:
        hostname: Lowercase parsed URL hostname.

    Returns:
        True when the host is unsuitable for production.
    """

    if (
        hostname in _LOCAL_HOSTS
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return not address.is_global


def _is_placeholder_host(hostname: str) -> bool:
    """Reports whether a host belongs to reserved example space.

    Args:
        hostname: Lowercase parsed URL hostname.

    Returns:
        True for `.invalid` and conventional example domains.
    """

    return (
        hostname.endswith(".invalid")
        or hostname in _PLACEHOLDER_HOSTS
        or any(hostname.endswith(f".{item}") for item in _PLACEHOLDER_HOSTS)
    )


def _parse_public_url(
    key: str,
    value: str,
    *,
    origin_only: bool,
) -> SplitResult:
    """Validates one HTTPS production URL.

    Args:
        key: Profile field used in diagnostics.
        value: Candidate absolute public URL.
        origin_only: Whether paths other than `/` are forbidden.

    Returns:
        Parsed URL after production plausibility checks.

    Raises:
        SwarmReleaseProfileError: If the URL is unsafe, local, placeholder, or
            not an origin where an origin is required.
    """

    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SwarmReleaseProfileError(f"{key} must be an absolute HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise SwarmReleaseProfileError(f"{key} must not contain URL credentials.")
    if parsed.query or parsed.fragment:
        raise SwarmReleaseProfileError(
            f"{key} must not contain a query or fragment."
        )
    if "*" in parsed.netloc:
        raise SwarmReleaseProfileError(f"{key} must not contain a wildcard host.")
    try:
        parsed.port
    except ValueError as error:
        raise SwarmReleaseProfileError(f"{key} contains an invalid port.") from error
    if origin_only and parsed.path not in ("", "/"):
        raise SwarmReleaseProfileError(f"{key} must be an origin without a path.")

    hostname = parsed.hostname.casefold()
    if _is_non_public_host(hostname):
        raise SwarmReleaseProfileError(f"{key} must not use a local or private host.")
    if _is_placeholder_host(hostname) or _is_placeholder(value):
        raise SwarmReleaseProfileError(f"{key} must not use a placeholder host.")
    return parsed


def _validate_identity(values: Mapping[str, str]) -> None:
    """Validates app, API runtime, Keycloak, and stack scalar identities.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        None when exact candidate identities pass.

    Raises:
        SwarmReleaseProfileError: If schema, environment, provider, data, or
            candidate identity differs from the approved Felix contract.
    """

    expected_values = {
        "PROFILE_SCHEMA_VERSION": "1",
        "APP_ID": "felix",
        "APP_ENVIRONMENT": "production",
        "APP_PROFILE": "felix",
        "BACKEND_APP_ID": "felix",
        "BACKEND_DATA_PROFILE": "postgresql",
        "AUTH_PROVIDER": "keycloak",
        "KEYCLOAK_REALM": _CANDIDATE_REALM,
        "KEYCLOAK_FRONTEND_CLIENT_ID": _CANDIDATE_FRONTEND_CLIENT,
        "STACK_NAME": _CANDIDATE_STACK,
    }
    if (
        values["KEYCLOAK_REALM"] in _PROTECTED_REALMS
        or values["KEYCLOAK_FRONTEND_CLIENT_ID"] in _PROTECTED_CLIENTS
        or values["STACK_NAME"] in _PROTECTED_STACKS
    ):
        raise SwarmReleaseProfileError(
            "Candidate profile must not target a protected legacy identity."
        )
    for key, expected in expected_values.items():
        if values[key] != expected:
            raise SwarmReleaseProfileError(f"{key} must equal {expected!r}.")
    for key in ("KEYCLOAK_AUDIENCE", "KEYCLOAK_FRONTEND_CLIENT_ID", "STACK_NAME"):
        if not _IDENTIFIER_PATTERN.fullmatch(values[key]):
            raise SwarmReleaseProfileError(f"{key} contains an invalid identifier.")


def _validate_urls(values: Mapping[str, str]) -> None:
    """Validates API, CORS, and Keycloak URL relationships.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        None when public URLs are plausible and mutually consistent.

    Raises:
        SwarmReleaseProfileError: If URLs are unsafe, redundant, mismatched, or
            target the protected legacy PWA.
    """

    api = _parse_public_url("API_BASE_URL", values["API_BASE_URL"], origin_only=False)
    if api.path.rstrip("/") == "/api" or api.path.startswith("/api/"):
        raise SwarmReleaseProfileError(
            "API_BASE_URL must not contain a redundant /api service prefix."
        )
    if api.path not in ("", "/"):
        raise SwarmReleaseProfileError("API_BASE_URL must not contain a path.")
    if api.hostname != values["DOMAIN"].casefold():
        raise SwarmReleaseProfileError("DOMAIN must match the API_BASE_URL hostname.")

    keycloak = _parse_public_url(
        "KEYCLOAK_BASE_URL",
        values["KEYCLOAK_BASE_URL"],
        origin_only=True,
    )
    _parse_public_url(
        "KEYCLOAK_ISSUER_URL",
        values["KEYCLOAK_ISSUER_URL"],
        origin_only=False,
    )
    base = values["KEYCLOAK_BASE_URL"].rstrip("/")
    expected_issuer = f"{base}/realms/{values['KEYCLOAK_REALM']}"
    if values["KEYCLOAK_ISSUER_URL"] != expected_issuer:
        raise SwarmReleaseProfileError(
            "KEYCLOAK_ISSUER_URL must be the declared realm below the base URL."
        )
    if keycloak.hostname is None:
        raise SwarmReleaseProfileError("KEYCLOAK_BASE_URL must contain a hostname.")

    origins = values["CORS_ORIGINS"].split(",")
    if len(origins) != len(set(origins)):
        raise SwarmReleaseProfileError("CORS_ORIGINS must not contain duplicates.")
    for origin in origins:
        _parse_public_url("CORS_ORIGINS", origin, origin_only=True)
    if _PROTECTED_WEB_ORIGIN in origins:
        raise SwarmReleaseProfileError(
            "Candidate CORS_ORIGINS must not claim the protected legacy origin."
        )
    if origins != [_CANDIDATE_WEB_ORIGIN]:
        raise SwarmReleaseProfileError(
            f"CORS_ORIGINS must equal {_CANDIDATE_WEB_ORIGIN!r}."
        )


def _profile_fingerprint(values: Mapping[str, str]) -> str:
    """Computes a canonical SHA-256 public-profile fingerprint.

    Args:
        values: Validated mapping in schema order.

    Returns:
        Lowercase SHA-256 hexadecimal digest.
    """

    content = "".join(f"{key}={values[key]}\n" for key in _PROFILE_KEYS)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_release_profile(path: Path) -> SwarmReleaseProfile:
    """Parses and validates one root candidate-production profile.

    Args:
        path: Canonical root `prod.env`.

    Returns:
        Immutable validated profile with safe fingerprint.

    Raises:
        SwarmReleaseProfileError: If parsing or validation fails.
        OSError: If the profile cannot otherwise be read.
    """

    values = _parse_assignments(path)
    for key, value in values.items():
        if _is_placeholder(value):
            raise SwarmReleaseProfileError(f"{key} must not contain placeholder text.")
    _validate_identity(values)
    _validate_urls(values)
    return SwarmReleaseProfile(
        path=path.resolve(),
        values=values,
        fingerprint=_profile_fingerprint(values),
    )


def load_release_profile(
    root: Path,
    requested_path: Path | None = None,
) -> SwarmReleaseProfile:
    """Resolves and validates the Swarm production profile.

    Args:
        root: Swarm repository root.
        requested_path: Optional exact root `prod.env` path.

    Returns:
        Immutable validated public production profile.

    Raises:
        SwarmReleaseProfileError: If resolution or validation fails.
        OSError: If the profile cannot otherwise be read.
    """

    return parse_release_profile(resolve_profile_path(root, requested_path))


def render_compatibility_env(profile: SwarmReleaseProfile) -> str:
    """Renders the validated public profile as generated root `.env` data.

    Args:
        profile: Validated candidate-production profile.

    Returns:
        Deterministic commentable public-only compatibility content.
    """

    lines = [
        "# Generated public release-profile compatibility materialization.",
        "# Do not add credentials or edit by hand; regenerate from prod.env.",
        *(f"{key}={profile.values[key]}" for key in _PROFILE_KEYS),
        "",
    ]
    return "\n".join(lines)


def materialize_compatibility_env(
    profile: SwarmReleaseProfile,
    destination: Path,
    *,
    overwrite: bool = False,
) -> None:
    """Atomically writes validated public values to a compatibility `.env`.

    Args:
        profile: Validated source production profile.
        destination: Generated compatibility artifact path.
        overwrite: Whether an existing file may be replaced. Defaults to False.

    Returns:
        None.

    Raises:
        SwarmReleaseProfileError: If the destination exists without explicit
            overwrite approval.
        OSError: If the temporary or destination file cannot be written.
    """

    resolved_destination = destination.resolve()
    if resolved_destination.exists() and not overwrite:
        raise SwarmReleaseProfileError(
            f"Compatibility file exists: {resolved_destination}; pass --force to replace it."
        )
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=resolved_destination.parent,
        prefix=f".{resolved_destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(render_compatibility_env(profile))
        temporary_path.replace(resolved_destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def execute_with_validated_profile(
    root: Path,
    operation: ProfileOperation,
    *,
    requested_path: Path | None = None,
) -> int:
    """Runs caller-owned work only after the production profile passes.

    Args:
        root: Swarm repository root.
        operation: Callback receiving the validated public profile.
        requested_path: Optional exact root `prod.env` path.

    Returns:
        Integer result returned by the operation.

    Raises:
        SwarmReleaseProfileError: Before callback execution when validation
            fails.
        OSError: If the profile cannot otherwise be read.
    """

    profile = load_release_profile(root, requested_path)
    return operation(profile)


def build_argument_parser() -> argparse.ArgumentParser:
    """Builds the Swarm public-profile CLI parser.

    Returns:
        Configured validation/materialization parser.
    """

    parser = argparse.ArgumentParser(
        description="Validate the Swarm Felix candidate production profile."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Swarm repository root.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Optional exact root prod.env path; arbitrary paths are rejected.",
    )
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Write the validated public profile to generated root .env.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow materialization to replace an existing root .env.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validates a profile and optionally materializes generated public data.

    Args:
        argv: Optional CLI arguments excluding the executable name.

    Returns:
        Zero on success and two for invalid configuration.
    """

    arguments = build_argument_parser().parse_args(argv)
    root = arguments.root.resolve()
    try:
        profile = load_release_profile(root, arguments.profile)
        if arguments.materialize:
            materialize_compatibility_env(
                profile,
                root / ".env",
                overwrite=arguments.force,
            )
    except (OSError, SwarmReleaseProfileError) as error:
        print(f"swarm-release-profile: ERROR: {error}", file=sys.stderr)
        return 2

    print(json.dumps(profile.safe_summary(), indent=2, sort_keys=True))
    if arguments.materialize:
        print("swarm-release-profile: generated root .env from validated public data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
