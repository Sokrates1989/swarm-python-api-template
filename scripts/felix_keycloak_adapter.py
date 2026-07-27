#!/usr/bin/env python3
"""Pinned, secret-safe Swarm adapter for canonical Felix Keycloak tooling.

The adapter validates an exact clean canonical checkout and delegates one
explicit check, plan, apply, verify, secret-bridge, rotation, or legacy
read-only operation. It never performs source updates or reads credential
values itself.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIN_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "release_contracts"
    / "felix_keycloak_tool.v1.json"
)
EXPECTED_COMMIT = "5096ea7820874bbb66dbc6162043c4348c8c95e5"
EXPECTED_VERSION = "0.1.0"
EXPECTED_REALM = "felix-new"
EXPECTED_FRONTEND_CLIENT = "felix-new-frontend"
EXPECTED_BACKEND_CLIENT = "felix-new-backend"
EXPECTED_DOCKER_SECRET = "FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET"
PROXIED_COMMANDS = {
    "check",
    "plan",
    "diff",
    "apply",
    "verify",
    "bridge-secret",
    "verify-legacy",
}


class AdapterError(RuntimeError):
    """Report a safely handled adapter pin or invocation failure."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate keys.

    Args:
        pairs: Ordered JSON key/value pairs.

    Returns:
        Mapping containing every unique pair.

    Raises:
        AdapterError: If any key appears twice.
    """

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdapterError(f"Duplicate Keycloak tool pin key: {key}.")
        result[key] = value
    return result


def load_pin(path: Path) -> dict[str, Any]:
    """Load and validate the exact public canonical-tool pin.

    Args:
        path: Pin JSON path.

    Returns:
        Validated pin mapping.

    Raises:
        AdapterError: If the file, schema, identities, or commit differs.
    """

    try:
        pin = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError("Unable to load canonical Keycloak tool pin.") from exc
    expected = {
        "schemaVersion": 1,
        "appId": "felix",
        "toolVersion": EXPECTED_VERSION,
        "sourceCommit": EXPECTED_COMMIT,
        "candidateRealm": EXPECTED_REALM,
        "frontendClientId": EXPECTED_FRONTEND_CLIENT,
        "backendClientId": EXPECTED_BACKEND_CLIENT,
        "dockerSecretName": EXPECTED_DOCKER_SECRET,
        "entrypoint": "tools/felix_keycloak.py",
    }
    if not isinstance(pin, dict) or any(pin.get(key) != value for key, value in expected.items()):
        raise AdapterError("Canonical Keycloak tool pin is not exact.")
    return pin


def default_tool_directory() -> Path:
    """Resolve the local multi-repository canonical checkout convention.

    Returns:
        ``keycloak`` repository beside the parent ``swarm`` directory.
    """

    return REPOSITORY_ROOT.parent.parent / "keycloak"


def _git_output(tool_directory: Path, *arguments: str) -> str:
    """Run one captured read-only Git command in the canonical checkout.

    Args:
        tool_directory: Candidate canonical repository root.
        *arguments: Git arguments following ``git -C <root>``.

    Returns:
        Stripped stdout.

    Raises:
        AdapterError: If Git rejects the query.
    """

    result = subprocess.run(
        ["git", "-C", str(tool_directory), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AdapterError("Unable to inspect canonical Keycloak checkout.")
    return result.stdout.strip()


def validate_tool_checkout(
    tool_directory: Path,
    pin: dict[str, Any],
) -> Path:
    """Validate repository identity, exact commit, cleanliness, and version.

    Args:
        tool_directory: Canonical Keycloak checkout root.
        pin: Validated public tool pin.

    Returns:
        Absolute canonical CLI entrypoint.

    Raises:
        AdapterError: If the checkout is absent, dirty, unpinned, or reports a
            different CLI version.
    """

    resolved = tool_directory.resolve()
    entrypoint = (resolved / str(pin["entrypoint"])).resolve()
    try:
        entrypoint.relative_to(resolved)
    except ValueError as exc:
        raise AdapterError("Canonical Keycloak entrypoint escapes its checkout.") from exc
    if not entrypoint.is_file():
        raise AdapterError("Canonical Keycloak entrypoint is missing.")
    if _git_output(resolved, "rev-parse", "HEAD") != pin["sourceCommit"]:
        raise AdapterError("Canonical Keycloak checkout is not at the pinned commit.")
    if _git_output(resolved, "status", "--porcelain"):
        raise AdapterError("Canonical Keycloak checkout must be clean.")
    version = subprocess.run(
        [sys.executable, str(entrypoint), "--version"],
        check=False,
        capture_output=True,
        text=True,
        cwd=resolved,
    )
    if version.returncode != 0 or version.stdout.strip() != pin["toolVersion"]:
        raise AdapterError("Canonical Keycloak CLI version does not match its pin.")
    return entrypoint


def build_delegate_command(
    entrypoint: Path,
    command: str,
    admin_user: str,
    admin_password_file: Path,
    *,
    rotation_secret_name: str | None = None,
    rotation_confirmation: str | None = None,
) -> list[str]:
    """Build one shell-free canonical CLI invocation.

    Args:
        entrypoint: Validated canonical CLI entrypoint.
        command: Explicit supported canonical subcommand.
        admin_user: Keycloak administrator username.
        admin_password_file: Protected administrator password file.
        rotation_secret_name: New versioned Docker secret for explicit rotation.
        rotation_confirmation: Exact backend client ID confirmation.

    Returns:
        Argument vector containing no credential value.

    Raises:
        AdapterError: If the command or rotation arguments are invalid.
    """

    if command not in PROXIED_COMMANDS | {"rotate-secret"}:
        raise AdapterError(f"Unsupported canonical Keycloak command: {command}.")
    arguments = [
        sys.executable,
        str(entrypoint),
        "--admin-user",
        admin_user,
        "--admin-password-file",
        str(admin_password_file),
        command,
    ]
    if command == "rotate-secret":
        if not rotation_secret_name or rotation_confirmation != EXPECTED_BACKEND_CLIENT:
            raise AdapterError("Rotation requires a new name and exact client confirmation.")
        arguments.extend(
            [
                "--docker-secret-name",
                rotation_secret_name,
                "--confirm-client-id",
                rotation_confirmation,
            ]
        )
    return arguments


def delegate(arguments: argparse.Namespace) -> int:
    """Validate the pin and run one explicit canonical operation.

    Args:
        arguments: Parsed adapter command-line namespace.

    Returns:
        Canonical CLI exit code.

    Side Effects:
        The canonical ``apply``, ``bridge-secret``, or ``rotate-secret``
        command may mutate only its documented candidate resources.
    """

    pin = load_pin(arguments.pin)
    entrypoint = validate_tool_checkout(arguments.tool_directory, pin)
    command = build_delegate_command(
        entrypoint,
        arguments.command,
        arguments.admin_user,
        arguments.admin_password_file,
        rotation_secret_name=arguments.docker_secret_name,
        rotation_confirmation=arguments.confirm_client_id,
    )
    result = subprocess.run(
        command,
        check=False,
        cwd=entrypoint.parents[2],
    )
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    """Build the pinned Swarm Keycloak adapter parser.

    Returns:
        Configured parser for checkout validation and explicit delegation.
    """

    parser = argparse.ArgumentParser(
        description="Pinned Swarm adapter for canonical Felix Keycloak operations.",
    )
    parser.add_argument("--pin", type=Path, default=DEFAULT_PIN_PATH)
    parser.add_argument(
        "--tool-directory",
        type=Path,
        default=Path(
            os.environ.get(
                "FELIX_KEYCLOAK_TOOL_DIRECTORY",
                default_tool_directory(),
            )
        ),
    )
    parser.add_argument("--admin-user", required=True)
    parser.add_argument("--admin-password-file", type=Path, required=True)
    parser.add_argument(
        "command",
        choices=sorted(PROXIED_COMMANDS | {"rotate-secret"}),
    )
    parser.add_argument("--docker-secret-name")
    parser.add_argument("--confirm-client-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pinned secret-safe Swarm adapter.

    Args:
        argv: Optional argument vector excluding executable name.

    Returns:
        Delegated exit code, or one for a safely reported adapter failure.
    """

    try:
        return delegate(build_parser().parse_args(argv))
    except AdapterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
