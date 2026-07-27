"""Shell-free subprocess execution for strict Felix release operations.

All external commands receive explicit argument vectors. Checked failures omit
captured output from exceptions, while database dumps stream directly into a
protected file instead of passing through terminal or in-memory text.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .errors import FelixReleaseError


@dataclass(frozen=True)
class CommandResult:
    """Contain one captured command result.

    Attributes:
        arguments: Exact non-shell argument vector.
        return_code: Process exit status.
        stdout: Captured standard output.
        stderr: Captured standard error.
    """

    arguments: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str


class CommandRunner:
    """Execute explicit argument vectors without shell interpolation."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run one text command with captured output.

        Args:
            arguments: Non-empty executable/argument vector.
            cwd: Optional working directory.
            input_text: Optional protected stdin data.
            check: Raise on nonzero status when true.

        Returns:
            Captured command result.

        Raises:
            FelixReleaseError: If execution fails or a checked command is
                nonzero. Captured output is intentionally not copied into the
                error to avoid secret leakage.
        """

        if not arguments:
            raise FelixReleaseError("Release command argument vector is empty.")
        try:
            process = subprocess.run(
                list(arguments),
                cwd=cwd,
                input=input_text,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise FelixReleaseError(
                f"Required release executable is unavailable: {arguments[0]}."
            ) from exc
        result = CommandResult(
            tuple(arguments),
            process.returncode,
            process.stdout,
            process.stderr,
        )
        if check and result.return_code != 0:
            raise FelixReleaseError(
                f"Release command failed safely: {arguments[0]} "
                f"(exit {result.return_code})."
            )
        return result

    def run_to_file(
        self,
        arguments: Sequence[str],
        output_path: Path,
        *,
        cwd: Path | None = None,
    ) -> None:
        """Stream binary stdout directly into a protected file.

        Args:
            arguments: Non-empty executable/argument vector.
            output_path: Prevalidated backup output path.
            cwd: Optional working directory.

        Returns:
            None.

        Raises:
            FelixReleaseError: If execution or the command fails.

        Side Effects:
            Creates/truncates the exact output file without buffering database
            content into terminal output.
        """

        if not arguments:
            raise FelixReleaseError("Backup command argument vector is empty.")
        try:
            with output_path.open("wb") as output:
                process = subprocess.run(
                    list(arguments),
                    cwd=cwd,
                    check=False,
                    stdout=output,
                    stderr=subprocess.PIPE,
                )
        except OSError as exc:
            raise FelixReleaseError("Database backup command could not run.") from exc
        if process.returncode != 0:
            raise FelixReleaseError("Database backup command failed safely.")
