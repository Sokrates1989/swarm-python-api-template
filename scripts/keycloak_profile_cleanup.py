"""
Module: keycloak_profile_cleanup.py

Description:
    Persists an operator-facing cleanup reminder for temporary Keycloak users
    that this bootstrap actually created. The state is public metadata in the
    ignored root ``.env``; it never inspects, authenticates as, or deletes a
    live Keycloak account. Existing accounts with bootstrap-reserved names are
    therefore outside this module's ownership boundary.

Dependencies:
    - Python standard library.
    - Executable profile model and deployment validation modules.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from executable_profile import ExecutableProfile, load_executable_profile
from executable_profile_deployment_validation import validate_deployment
from executable_profile_support import ExecutableProfileError, NAME_PATTERN


CLEANUP_PENDING_KEY = "KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING"
CLEANUP_NAMES_KEY = "KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES"
_CLEANUP_KEYS = (CLEANUP_PENDING_KEY, CLEANUP_NAMES_KEY)
_INSERT_AFTER_KEY = "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED"


@dataclass(frozen=True)
class BootstrapUserCleanupState:
    """Represent public operator-tracked temporary-user cleanup state.

    Attributes:
        pending: Whether manual Keycloak cleanup still needs acknowledgement.
        usernames: Exact bootstrap-created usernames awaiting confirmation.
    """

    pending: bool
    usernames: tuple[str, ...]


def _normalized_usernames(usernames: object) -> tuple[str, ...]:
    """Normalize and validate bootstrap-created cleanup usernames.

    Args:
        usernames: Iterable of candidate username values.

    Returns:
        Sorted unique safe usernames.

    Raises:
        ExecutableProfileError: If the value is not iterable or contains an
            unsafe username.
    """

    if isinstance(usernames, (str, bytes)):
        candidates = str(usernames).split(",")
    else:
        try:
            candidates = list(usernames)  # type: ignore[arg-type]
        except TypeError as error:
            raise ExecutableProfileError(
                "Bootstrap-user cleanup names must be iterable."
            ) from error
    normalized = tuple(
        sorted({str(candidate).strip() for candidate in candidates if str(candidate).strip()})
    )
    unsafe = [name for name in normalized if not NAME_PATTERN.fullmatch(name)]
    if unsafe:
        raise ExecutableProfileError(
            "Bootstrap-user cleanup contains unsafe usernames: "
            + ", ".join(unsafe)
        )
    return normalized


def read_bootstrap_user_cleanup_state(
    profile: ExecutableProfile,
) -> BootstrapUserCleanupState:
    """Read validated cleanup reminder state from one active deployment.

    Args:
        profile: Loaded executable deployment profile.

    Returns:
        Current cleanup state. Pre-upgrade environments default to no pending
        reminder through the executable-profile compatibility defaults.
    """

    usernames = _normalized_usernames(
        profile.deployment.get(CLEANUP_NAMES_KEY, "")
    )
    pending = profile.deployment.get(CLEANUP_PENDING_KEY, "") == "true"
    return BootstrapUserCleanupState(pending=pending, usernames=usernames)


def created_bootstrap_usernames(
    plan: Mapping[str, object],
) -> tuple[str, ...]:
    """Extract only users whose authenticated plan classified as creation.

    Args:
        plan: Sanitized reconciliation plan shown before mutation.

    Returns:
        Sorted usernames with an exact ``create`` action.

    Raises:
        ExecutableProfileError: If the plan action map is malformed.
    """

    raw_actions = plan.get("bootstrapTestUserActions", {})
    if not isinstance(raw_actions, Mapping):
        raise ExecutableProfileError(
            "Keycloak bootstrap-user action plan is malformed."
        )
    return _normalized_usernames(
        name for name, action in raw_actions.items() if action == "create"
    )


def _render_cleanup_state(
    source: str,
    state: BootstrapUserCleanupState,
) -> str:
    """Replace or add cleanup assignments without discarding human comments.

    Args:
        source: Existing validated root environment content.
        state: New cleanup state.

    Returns:
        Updated dotenv content preserving all unrelated lines and sections.
    """

    assignments = {
        CLEANUP_PENDING_KEY: str(state.pending).lower(),
        CLEANUP_NAMES_KEY: ",".join(state.usernames),
    }
    lines = source.splitlines()
    present = {
        line.split("=", 1)[0]
        for line in lines
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = [key for key in _CLEANUP_KEYS if key not in present]
    rendered: list[str] = []
    inserted = False
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        rendered.append(
            f"{key}={assignments[key]}" if key in assignments else line
        )
        if key == _INSERT_AFTER_KEY and missing:
            rendered.extend(f"{name}={assignments[name]}" for name in missing)
            inserted = True
    if missing and not inserted:
        rendered.extend(
            (
                "",
                "# Keycloak temporary bootstrap-user cleanup reminder.",
                *(f"{name}={assignments[name]}" for name in missing),
            )
        )
    return "\n".join(rendered) + "\n"


def _write_bootstrap_user_cleanup_state(
    profile: ExecutableProfile,
    state: BootstrapUserCleanupState,
) -> None:
    """Validate and atomically persist cleanup state without stack changes.

    Args:
        profile: Active executable deployment profile.
        state: New public cleanup reminder state.

    Returns:
        Nothing after a mode-0600 atomic replacement.

    Raises:
        ExecutableProfileError: If the resulting deployment environment is
            incoherent.
        OSError: If the environment cannot be read, staged, or replaced.
    """

    updates = {
        CLEANUP_PENDING_KEY: str(state.pending).lower(),
        CLEANUP_NAMES_KEY: ",".join(state.usernames),
    }
    merged = {**profile.deployment, **updates}
    validate_deployment(profile.data, profile.config_id, merged)
    destination = profile.root / ".env"
    content = _render_cleanup_state(
        destination.read_text(encoding="utf-8"),
        state,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=profile.root,
        prefix=".keycloak-cleanup-state.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as output:
            output.write(content)
        temporary.chmod(0o600)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def record_created_bootstrap_users(
    profile: ExecutableProfile,
    plan: Mapping[str, object],
) -> BootstrapUserCleanupState:
    """Record successfully created users while retaining earlier reminders.

    Args:
        profile: Active executable deployment profile.
        plan: Authenticated plan that was applied and fully verified.

    Returns:
        Resulting cleanup state. Existing or merely updated users never enter
        this state because their origin is not proven to be this bootstrap.
    """

    current = read_bootstrap_user_cleanup_state(profile)
    created = created_bootstrap_usernames(plan)
    if not created:
        return current
    resulting = BootstrapUserCleanupState(
        pending=True,
        usernames=_normalized_usernames((*current.usernames, *created)),
    )
    _write_bootstrap_user_cleanup_state(profile, resulting)
    return resulting


def acknowledge_bootstrap_user_cleanup(
    profile: ExecutableProfile,
) -> BootstrapUserCleanupState:
    """Clear only the reminder after an operator manually deletes its users.

    Args:
        profile: Active executable deployment profile.

    Returns:
        Prior pending state for operator-facing confirmation output.

    Note:
        This function deliberately performs no Keycloak request and never
        deletes or verifies a user. The acknowledgement is an operator claim.
    """

    prior = read_bootstrap_user_cleanup_state(profile)
    if prior.pending or prior.usernames:
        _write_bootstrap_user_cleanup_state(
            profile,
            BootstrapUserCleanupState(pending=False, usernames=()),
        )
    return prior


def build_parser() -> argparse.ArgumentParser:
    """Build the cleanup acknowledgement command parser.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Acknowledge manual deletion of bootstrap-created Keycloak users."
        )
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("action", choices=("acknowledge",))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the non-destructive cleanup acknowledgement command.

    Args:
        argv: Optional arguments excluding executable name.

    Returns:
        Process status.
    """

    args = build_parser().parse_args(argv)
    try:
        profile = load_executable_profile(args.root)
        prior = acknowledge_bootstrap_user_cleanup(profile)
        if not prior.pending:
            print("[INFO] No bootstrap-created user cleanup was pending.")
            return 0
        print(
            "[OK] Recorded manual cleanup acknowledgement for: "
            + ", ".join(prior.usernames)
        )
        print("[INFO] No Keycloak account was queried, changed, or deleted.")
        return 0
    except (ExecutableProfileError, OSError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BootstrapUserCleanupState",
    "acknowledge_bootstrap_user_cleanup",
    "created_bootstrap_usernames",
    "read_bootstrap_user_cleanup_state",
    "record_created_bootstrap_users",
]
