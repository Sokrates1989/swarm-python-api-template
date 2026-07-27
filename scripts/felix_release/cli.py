"""Command-line interface for strict Felix candidate release operations.

The adapter exposes explicit candidate preparation, preflight, deploy, health,
rollback, drill, status, and redacted-log commands to the quick-start menu.
It converts safely handled operational failures into stable exit codes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import FelixReleaseError
from .preflight import prepare_data_directories
from .state_machine import FelixReleaseStateMachine


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the candidate-only release command parser.

    Returns:
        Parser exposing preparation, deploy, health, rollback, drill, status,
        and sanitized-log operations.
    """

    parser = argparse.ArgumentParser(
        description="Operate the strict felix-new Swarm release state machine."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Swarm repository root. Defaults to the current tool checkout.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "prepare-data",
        help="Create only the fixed candidate data directories.",
    )
    commands.add_parser(
        "preflight",
        help="Verify profile, digest, Swarm, secrets, TLS, and legacy continuity.",
    )
    commands.add_parser(
        "deploy",
        help="Backup and deploy the candidate with strict health and rollback.",
    )
    commands.add_parser(
        "health",
        help="Run strict candidate health and legacy continuity checks.",
    )
    commands.add_parser(
        "rollback",
        help="Explicitly rollback only the candidate API service.",
    )
    commands.add_parser(
        "drill-rollback",
        help="Inject a bad candidate and verify rollback plus database continuity.",
    )
    commands.add_parser("status", help="Show sanitized candidate stack state.")
    commands.add_parser("logs", help="Show redacted recent candidate API logs.")
    return parser


def _print_json(payload: Any) -> None:
    """Write one deterministic public JSON result.

    Args:
        payload: JSON-serializable public result.

    Returns:
        None.

    Side Effects:
        Writes formatted JSON to standard output.
    """

    print(json.dumps(payload, indent=2, sort_keys=True))


def _run_command(
    state_machine: FelixReleaseStateMachine,
    command: str,
) -> None:
    """Execute one parsed candidate release command.

    Args:
        state_machine: Candidate-only state-machine instance.
        command: Valid parser command name.

    Returns:
        None.

    Raises:
        FelixReleaseError: If the requested operation fails safely.

    Side Effects:
        May create directories, pull images, write evidence/backups, deploy,
        inspect, log, inject a failure, or rollback the candidate stack.
    """

    if command == "preflight":
        evidence, receipt = state_machine.preflight()
        _print_json({"evidence": evidence.as_dict(), "receiptPath": str(receipt)})
    elif command == "deploy":
        _print_json({"receiptPath": str(state_machine.deploy())})
    elif command == "health":
        evidence, receipt = state_machine.health()
        _print_json({"evidence": evidence.as_dict(), "receiptPath": str(receipt)})
    elif command == "rollback":
        _print_json({"receiptPath": str(state_machine.rollback())})
    elif command == "drill-rollback":
        _print_json({"receiptPath": str(state_machine.failure_injection_drill())})
    elif command == "status":
        _print_json(state_machine.status())
    elif command == "logs":
        print(state_machine.sanitized_logs(), end="")
    else:
        raise FelixReleaseError(f"Unsupported Felix release command: {command}.")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse and run one strict Felix candidate release operation.

    Args:
        argv: Optional argument vector excluding the executable name.

    Returns:
        Zero on success, two for a safely handled operational error, or 130
        when interrupted by the operator.
    """

    arguments = build_argument_parser().parse_args(argv)
    root = arguments.root.resolve()
    try:
        if arguments.command == "prepare-data":
            _print_json(
                {
                    "candidateDataDirectories": list(
                        prepare_data_directories(root)
                    )
                }
            )
        else:
            _run_command(FelixReleaseStateMachine(root), arguments.command)
    except FelixReleaseError as exc:
        print(f"felix-release: ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("felix-release: interrupted", file=sys.stderr)
        return 130
    return 0
