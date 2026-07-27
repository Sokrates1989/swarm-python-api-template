"""Executable launcher for the strict Felix candidate release CLI.

Run this file directly on the Swarm manager or through ``quick-start.sh``.
The implementation lives in ``felix_release.cli`` so it remains unit-testable.
"""

from felix_release.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
