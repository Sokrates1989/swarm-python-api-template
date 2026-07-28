"""
Module: site_profile.py

Description:
    Command-line adapter for shared executable site-profile configuration,
    validation, summary, and deterministic Docker Swarm stack rendering.

Dependencies:
    - scripts/executable_profile.py.
    - scripts/executable_stack_renderer.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from executable_profile import (
    ExecutableProfileError,
    load_executable_profile,
)
from executable_profile_environment import (
    load_config_defaults,
    write_deployment_env,
)
from executable_stack_renderer import (
    compose_check,
    render_stack,
    validate_rendered_stack,
    write_stack,
)


def _parse_assignments(assignments: list[str]) -> dict[str, str]:
    """Parse repeatable ``KEY=VALUE`` setup overrides.

    Args:
        assignments: Raw CLI assignments.

    Returns:
        Unique key/value mapping.

    Raises:
        ExecutableProfileError: If syntax is invalid or a key is repeated.
    """

    values: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ExecutableProfileError(
                f"Deployment override must use KEY=VALUE: {assignment!r}"
            )
        key, value = assignment.split("=", 1)
        if not key or key in values:
            raise ExecutableProfileError(
                f"Deployment override key is empty or duplicated: {key!r}"
            )
        values[key] = value
    return values


def _configure(args: argparse.Namespace) -> int:
    """Write the selected executable profile's public root environment.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process status.
    """

    destination = write_deployment_env(
        args.root,
        args.profile,
        _parse_assignments(args.set),
        force=args.force,
    )
    print(f"Generated public deployment environment: {destination}")
    return 0


def _defaults(args: argparse.Namespace) -> int:
    """Print deterministic setup defaults as JSON.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process status.
    """

    _, values = load_config_defaults(args.root, args.profile)
    print(json.dumps(values, indent=2, sort_keys=True))
    return 0


def _render(args: argparse.Namespace) -> int:
    """Validate the active profile and atomically render its stack.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process status.
    """

    profile = load_executable_profile(args.root)
    stack = render_stack(profile)
    destination = args.root.resolve() / "swarm-stack.yml"
    write_stack(destination, stack)
    if args.compose_check:
        compose_check(destination)
    print(f"Rendered executable profile stack: {destination}")
    print(json.dumps(profile.safe_summary(), indent=2, sort_keys=True))
    return 0


def _validate(args: argparse.Namespace) -> int:
    """Validate root environment and an existing rendered stack.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process status.
    """

    profile = load_executable_profile(args.root)
    stack_path = args.root.resolve() / "swarm-stack.yml"
    if not stack_path.is_file():
        raise ExecutableProfileError(f"Rendered stack is missing: {stack_path}")
    stack = stack_path.read_text(encoding="utf-8")
    validate_rendered_stack(stack, profile)
    if stack != render_stack(profile):
        raise ExecutableProfileError(
            "Rendered stack differs from the selected site-config and root .env."
        )
    if args.compose_check:
        compose_check(stack_path)
    print(json.dumps(profile.safe_summary(), indent=2, sort_keys=True))
    return 0


def _summary(args: argparse.Namespace) -> int:
    """Print the active profile's sanitized normalized summary.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process status.
    """

    print(
        json.dumps(
            load_executable_profile(args.root).safe_summary(),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the site-profile CLI parser.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description="Configure and render a site-config-driven Swarm profile."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Swarm deployment repository root.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    defaults = subparsers.add_parser("defaults", help="Print setup defaults.")
    defaults.add_argument("--profile", required=True)
    defaults.set_defaults(handler=_defaults)

    configure = subparsers.add_parser("configure", help="Write root .env.")
    configure.add_argument("--profile", required=True)
    configure.add_argument("--set", action="append", default=[])
    configure.add_argument("--force", action="store_true")
    configure.set_defaults(handler=_configure)

    render = subparsers.add_parser("render", help="Render swarm-stack.yml.")
    render.add_argument("--compose-check", action="store_true")
    render.set_defaults(handler=_render)

    validate = subparsers.add_parser(
        "validate-stack",
        help="Validate root .env and rendered stack.",
    )
    validate.add_argument("--compose-check", action="store_true")
    validate.set_defaults(handler=_validate)

    summary = subparsers.add_parser("summary", help="Print sanitized summary.")
    summary.set_defaults(handler=_summary)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the site-profile CLI.

    Args:
        argv: Optional arguments excluding executable name.

    Returns:
        Process status.
    """

    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ExecutableProfileError, FileExistsError, OSError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
