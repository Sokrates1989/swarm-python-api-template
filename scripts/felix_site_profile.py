"""
Module: felix_site_profile.py

Description:
    Command-line adapter for validating and rendering the fixed Felix candidate
    Swarm site profile without creating secrets or deploying services.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from release_profile import SwarmReleaseProfileError
from felix_site_contract import (
    FelixSiteProfileError,
    load_felix_site_profile,
)
from felix_stack_renderer import (
    _compose_check,
    _resolve_root_artifact,
    _write_stack,
    render_stack,
    validate_rendered_stack,
)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the strict Felix site-profile CLI parser.

    Returns:
        Configured parser with validate, render, and validate-stack commands.
    """

    parser = argparse.ArgumentParser(
        description="Validate and render the Felix candidate Swarm site profile."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Swarm repository root.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Validate prod.env and felix.json.")
    render = commands.add_parser("render", help="Render root swarm-stack.yml.")
    render.add_argument("--output", type=Path, help="Exact root stack path.")
    render.add_argument(
        "--compose-check",
        action="store_true",
        help="Run docker compose config after rendering.",
    )
    validate_stack = commands.add_parser(
        "validate-stack",
        help="Validate the existing root swarm-stack.yml.",
    )
    validate_stack.add_argument("--stack", type=Path, help="Exact root stack path.")
    validate_stack.add_argument(
        "--compose-check",
        action="store_true",
        help="Run docker compose config after strict validation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate inputs and execute one non-deploying Felix profile operation.

    Args:
        argv: Optional CLI arguments excluding the executable name.

    Returns:
        Zero on success and two for invalid input, output, or Compose config.
    """

    arguments = build_argument_parser().parse_args(argv)
    root = arguments.root.resolve()
    try:
        profile = load_felix_site_profile(root)
        stack_path = _resolve_root_artifact(
            root,
            getattr(arguments, "output", None) or getattr(arguments, "stack", None),
            "swarm-stack.yml",
        )
        if arguments.command == "render":
            _write_stack(stack_path, render_stack(profile))
        elif arguments.command == "validate-stack":
            existing = stack_path.read_text(encoding="utf-8")
            expected = render_stack(profile)
            if existing != expected:
                raise FelixSiteProfileError(
                    "Existing swarm-stack.yml does not match the strict Felix render."
                )
            validate_rendered_stack(existing, profile)
        if getattr(arguments, "compose_check", False):
            _compose_check(stack_path)
    except (OSError, SwarmReleaseProfileError, FelixSiteProfileError) as error:
        print(f"felix-site-profile: ERROR: {error}", file=sys.stderr)
        return 2

    print(json.dumps(profile.safe_summary(), indent=2, sort_keys=True))
    if arguments.command == "render":
        print(f"felix-site-profile: rendered {stack_path}")
    elif arguments.command == "validate-stack":
        print(f"felix-site-profile: validated {stack_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
