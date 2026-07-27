"""
Module: release_profile.py

Description:
    Parses, validates, and atomically writes the guided Swarm deployment
    instance's public root `.env` without evaluating shell syntax. The adapter
    enforces Felix API, WebApp, database, proxy/TLS, image, Keycloak, stack,
    and legacy-isolation identities.

Dependencies:
    - Python 3.10 or newer standard library.

Usage:
    python scripts/release_profile.py
    python scripts/release_profile.py --set KEY=value [...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from release_profile_deployment import validate_deployment
from release_profile_errors import SwarmReleaseProfileError
from release_profile_urls import validate_urls


_PROFILE_KEYS = (
    "PROFILE_SCHEMA_VERSION",
    "DEPLOYMENT_PROFILE_ID",
    "APP_ID",
    "APP_ENVIRONMENT",
    "APP_PROFILE",
    "BACKEND_APP_ID",
    "BACKEND_DATA_PROFILE",
    "AUTH_PROVIDER",
    "API_BASE_URL",
    "DOMAIN",
    "WEB_BASE_URL",
    "WEB_DOMAIN",
    "CORS_ORIGINS",
    "KEYCLOAK_BASE_URL",
    "KEYCLOAK_ISSUER_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_AUDIENCE",
    "KEYCLOAK_FRONTEND_CLIENT_ID",
    "STACK_NAME",
    "STACK_FAMILY",
    "STACK_ROLE",
    "PRIMARY_SERVICE",
    "DB_TYPE",
    "DB_MODE",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "PROXY_TYPE",
    "SSL_MODE",
    "TRAEFIK_NETWORK",
    "API_PUBLISHED_PORT",
    "IMAGE_NAME",
    "IMAGE_VERSION",
    "API_REPLICAS",
    "MEMORY_LIMIT",
    "DATA_ROOT",
    "PGADMIN_ENABLED",
    "PGADMIN_DOMAIN",
    "PGADMIN_EMAIL",
    "PGADMIN_REPLICAS",
    "WEB_ENABLED",
    "WEB_IMAGE_NAME",
    "WEB_IMAGE_VERSION",
    "WEB_REPLICAS",
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
_CANDIDATE_REALM = "felix-new"
_CANDIDATE_FRONTEND_CLIENT = "felix-new-frontend"
_CANDIDATE_STACK = "felix-new"
_PROTECTED_REALMS = frozenset(("felix", "felixappnew"))
_PROTECTED_CLIENTS = frozenset(("felix-frontend", "felixappnew-frontend"))
_PROTECTED_STACKS = frozenset(("felix", "felixappnew"))
ProfileOperation = Callable[["SwarmReleaseProfile"], int]


@dataclass(frozen=True)
class SwarmReleaseProfile:
    """Contains one validated public Swarm production profile.

    Attributes:
        path: Canonical wizard-generated root `.env` path.
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
    """Resolves the exact deployment-instance `.env` input path.

    Args:
        root: Swarm repository root.
        requested_path: Optional override accepted only when it resolves to the
            canonical root `.env`.

    Returns:
        Canonical root `.env` path.

    Raises:
        SwarmReleaseProfileError: If an override tries to bypass the standard
            production profile boundary.
    """

    resolved_root = root.resolve()
    expected = (resolved_root / ".env").resolve()
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
            f"Deployment configuration is missing: {path}. Run the setup wizard."
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
        "DEPLOYMENT_PROFILE_ID": "felix",
        "APP_ID": "felix",
        "APP_ENVIRONMENT": "production",
        "APP_PROFILE": "felix",
        "BACKEND_APP_ID": "felix",
        "BACKEND_DATA_PROFILE": "postgresql",
        "AUTH_PROVIDER": "keycloak",
        "KEYCLOAK_REALM": _CANDIDATE_REALM,
        "KEYCLOAK_FRONTEND_CLIENT_ID": _CANDIDATE_FRONTEND_CLIENT,
        "STACK_NAME": _CANDIDATE_STACK,
        "STACK_FAMILY": "api",
        "STACK_ROLE": "full-stack",
        "PRIMARY_SERVICE": "api",
        "DB_TYPE": "postgresql",
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
        path: Canonical wizard-generated root `.env`.

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
    validate_urls(values)
    validate_deployment(values)
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
        requested_path: Optional exact root `.env` path.

    Returns:
        Immutable validated public production profile.

    Raises:
        SwarmReleaseProfileError: If resolution or validation fails.
        OSError: If the profile cannot otherwise be read.
    """

    return parse_release_profile(resolve_profile_path(root, requested_path))


def render_release_env(values: Mapping[str, str]) -> str:
    """Render deterministic public-only root `.env` content.

    Args:
        values: Complete guided deployment values in any mapping order.

    Returns:
        Commented canonical assignments ending in one newline.

    Raises:
        SwarmReleaseProfileError: If required/unknown keys differ from the
            strict guided schema.
    """

    actual = set(values)
    expected = set(_PROFILE_KEYS)
    if actual != expected:
        missing = ", ".join(sorted(expected - actual))
        unknown = ", ".join(sorted(actual - expected))
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise SwarmReleaseProfileError(
            "Guided deployment values are incomplete: " + "; ".join(details)
        )
    lines = [
        "# Generated by the Felix deployment setup wizard.",
        "# Public values only. Store passwords and client secrets in Docker secrets.",
        *(f"{key}={values[key]}" for key in _PROFILE_KEYS),
        "",
    ]
    return "\n".join(lines)


def write_release_env(
    root: Path,
    values: Mapping[str, str],
    *,
    overwrite: bool = False,
) -> SwarmReleaseProfile:
    """Validate and atomically write the deployment instance's root `.env`.

    Args:
        root: Swarm repository root.
        values: Complete public guided-deployment mapping.
        overwrite: Whether a differing existing `.env` may be replaced.
            Defaults to False.

    Returns:
        Validated profile whose path is the final root `.env`.

    Raises:
        SwarmReleaseProfileError: If values are invalid or replacement is not
            explicitly allowed.
        OSError: If temporary or destination file operations fail.

    Side Effects:
        Creates or replaces only the repository-owned root `.env`.
    """

    resolved_root = root.resolve()
    destination = resolve_profile_path(resolved_root)
    rendered = render_release_env(values)
    if destination.exists() and not overwrite:
        if destination.read_text(encoding="utf-8") == rendered:
            return load_release_profile(resolved_root)
        raise SwarmReleaseProfileError(
            f"Deployment configuration exists: {destination}; pass --force to replace it."
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=resolved_root,
        prefix=".felix-env.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(rendered)
        temporary_profile = parse_release_profile(temporary_path)
        temporary_path.replace(destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return SwarmReleaseProfile(
        path=destination,
        values=temporary_profile.values,
        fingerprint=temporary_profile.fingerprint,
    )


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
        requested_path: Optional exact root `.env` path.

    Returns:
        Integer result returned by the operation.

    Raises:
        SwarmReleaseProfileError: Before callback execution when validation
            fails.
        OSError: If the profile cannot otherwise be read.
    """

    profile = load_release_profile(root, requested_path)
    return operation(profile)


def _parse_cli_values(assignments: Sequence[str]) -> dict[str, str]:
    """Parse repeated public `KEY=value` CLI arguments without evaluation.

    Args:
        assignments: Raw repeated `--set` values supplied by the setup wizard.

    Returns:
        Duplicate-free public assignment mapping.

    Raises:
        SwarmReleaseProfileError: If syntax, keys, duplicates, newlines, or
            secret-looking names violate the public schema.
    """

    values: dict[str, str] = {}
    for assignment in assignments:
        if "\n" in assignment or "\r" in assignment:
            raise SwarmReleaseProfileError("CLI deployment values must be one line.")
        match = _ASSIGNMENT_PATTERN.fullmatch(assignment)
        if match is None:
            raise SwarmReleaseProfileError(
                f"Invalid --set value: {assignment!r}; expected KEY=value."
            )
        key, value = match.groups()
        if key not in _PROFILE_KEY_SET:
            raise SwarmReleaseProfileError(f"Unknown guided deployment key: {key}")
        if any(marker in key for marker in _SECRET_KEY_MARKERS):
            raise SwarmReleaseProfileError(
                f"Secret-looking guided deployment key is forbidden: {key}"
            )
        if key in values:
            raise SwarmReleaseProfileError(f"Duplicate guided deployment key: {key}")
        if not value or value != value.strip():
            raise SwarmReleaseProfileError(
                f"{key} must be non-empty without edge whitespace."
            )
        values[key] = value
    return values


def build_argument_parser() -> argparse.ArgumentParser:
    """Builds the Swarm public-profile CLI parser.

    Returns:
        Configured validation/guided-write parser.
    """

    parser = argparse.ArgumentParser(
        description="Validate or write the guided Felix deployment .env."
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
        help="Optional exact root .env path; arbitrary paths are rejected.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=value",
        help="Public guided value; repeat for the complete schema to write .env.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow guided writing to replace a differing root .env.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate an existing `.env` or atomically write guided public values.

    Args:
        argv: Optional CLI arguments excluding the executable name.

    Returns:
        Zero on success and two for invalid configuration.
    """

    arguments = build_argument_parser().parse_args(argv)
    root = arguments.root.resolve()
    try:
        if arguments.set:
            if arguments.profile is not None:
                raise SwarmReleaseProfileError(
                    "--profile cannot be combined with guided --set values."
                )
            profile = write_release_env(
                root,
                _parse_cli_values(arguments.set),
                overwrite=arguments.force,
            )
        else:
            profile = load_release_profile(root, arguments.profile)
    except (OSError, SwarmReleaseProfileError) as error:
        print(f"swarm-release-profile: ERROR: {error}", file=sys.stderr)
        return 2

    print(json.dumps(profile.safe_summary(), indent=2, sort_keys=True))
    if arguments.set:
        print("swarm-release-profile: wrote validated root .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
