"""
Module: temporary_secret_viewer.py

Description:
    Provides the repository-wide, one-run viewing contract for newly generated
    secret material. Values are opened in a private read-only temporary file
    and are deleted as soon as the selected terminal editor closes or the
    viewing process is interrupted. The command-line adapter consumes and
    deletes a protected handoff file before presenting the opt-in prompt.

Dependencies:
    - Python standard library.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


MAX_SECRET_BYTES = 1024 * 1024


class TemporarySecretViewerError(RuntimeError):
    """Raised when a temporary secret view cannot remain private or ephemeral."""


@dataclass(frozen=True)
class SecretViewPresentation:
    """User-facing text and file naming for one secret-view use case."""

    heading: str
    notices: tuple[str, ...]
    prompt: str
    skipped: str
    file_name: str = "temporary-secret.txt"
    copy_instruction: str = (
        "Copy the values to your clipboard or encrypted recovery store, "
        "then close the editor."
    )
    deleted_message: str = "[OK] Deleted the temporary secret file."


DEFAULT_PRESENTATION = SecretViewPresentation(
    heading="Secret recovery copy",
    notices=(
        "The generated secret values are available only during this run.",
        "If you choose to view them, copy the values to your clipboard and "
        "save them yourself in an encrypted recovery store.",
        "The read-only temporary file is deleted immediately after the "
        "editor closes.",
    ),
    prompt="View the generated secret values now? [y/N]: ",
    skipped="Secret view skipped; no recovery file was retained.",
)


def _runtime_root(explicit_root: Path | None = None) -> tuple[Path, bool]:
    """Resolve the safest writable parent for one private temporary folder."""

    if explicit_root is not None:
        root = explicit_root.resolve()
        if not root.is_dir() or not os.access(root, os.W_OK):
            raise TemporarySecretViewerError(
                f"Temporary secret directory is not writable: {root}"
            )
        return root, False

    candidates: list[tuple[Path, bool]] = []
    runtime_environment = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_environment:
        candidates.append((Path(runtime_environment), True))
    if hasattr(os, "getuid"):
        candidates.append((Path("/run/user") / str(os.getuid()), True))
    candidates.append((Path("/dev/shm"), True))
    candidates.append((Path(tempfile.gettempdir()), False))
    for root, memory_backed in candidates:
        if root.is_dir() and os.access(root, os.W_OK):
            return root.resolve(), memory_backed
    raise TemporarySecretViewerError(
        "No writable temporary directory is available for secret viewing."
    )


def _safe_file_name(file_name: str) -> str:
    """Validate a display file name without allowing path traversal."""

    candidate = file_name.strip()
    if (
        not candidate
        or candidate in {".", ".."}
        or Path(candidate).name != candidate
        or "/" in candidate
        or "\\" in candidate
    ):
        raise TemporarySecretViewerError(
            "Temporary secret file name must be one plain file name."
        )
    return candidate


def _editor_command(
    editor: str | Sequence[str],
    secret_path: Path,
) -> tuple[str, ...]:
    """Build a read-only, backup-resistant terminal editor command."""

    editor_parts = (editor,) if isinstance(editor, str) else tuple(editor)
    if not editor_parts:
        raise TemporarySecretViewerError("Selected editor command is empty.")
    executable, *configured_arguments = editor_parts
    name = Path(executable).name.lower()
    if name.startswith("nano"):
        return (
            executable,
            *configured_arguments,
            "--ignorercfiles",
            "--view",
            str(secret_path),
        )
    if name.startswith("vim"):
        return (
            executable,
            *configured_arguments,
            "-Nu",
            "NONE",
            "-n",
            "-R",
            "-i",
            "NONE",
            str(secret_path),
        )
    if name == "vi" or name.startswith("vi."):
        return (executable, *configured_arguments, "-R", str(secret_path))
    return (executable, *configured_arguments, str(secret_path))


def _launch_editor(
    command: Sequence[str],
    environment: Mapping[str, str],
) -> int:
    """Run the selected editor and terminate it when the parent is interrupted."""

    process = subprocess.Popen(list(command), env=dict(environment))
    try:
        return process.wait()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise


def _remove_private_view(directory: Path) -> None:
    """Delete the secret and editor sidecars from one owned private directory."""

    try:
        if directory.exists():
            for child in directory.iterdir():
                if child.is_dir() and not child.is_symlink():
                    raise TemporarySecretViewerError(
                        f"Unexpected nested directory blocks cleanup: {child}"
                    )
                if not child.is_symlink():
                    child.chmod(0o600)
                child.unlink(missing_ok=True)
            directory.rmdir()
    except OSError as error:
        raise TemporarySecretViewerError(
            f"Unable to delete temporary secret view: {directory}"
        ) from error


def _temporary_signal_handlers() -> dict[int, object]:
    """Convert termination signals into cleanup-capable interruptions."""

    previous: dict[int, object] = {}

    def interrupt_view(signum: int, frame: object) -> None:
        del signum, frame
        raise KeyboardInterrupt

    for signal_name in ("SIGHUP", "SIGTERM"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is not None:
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, interrupt_view)
    return previous


def _restore_signal_handlers(previous: Mapping[int, object]) -> None:
    """Restore handlers replaced for one temporary viewing session."""

    for signal_number, handler in previous.items():
        signal.signal(signal_number, handler)


def view_secret_temporarily(
    secret: str,
    editor: str | Sequence[str],
    *,
    presentation: SecretViewPresentation = DEFAULT_PRESENTATION,
    runtime_root: Path | None = None,
    launcher: Callable[[Sequence[str], Mapping[str, str]], int] = _launch_editor,
    output: Callable[[str], None] = print,
) -> None:
    """Open secret material read-only and delete it after the editor closes."""

    if not secret:
        raise TemporarySecretViewerError("Secret recovery content is empty.")
    if len(secret.encode("utf-8")) > MAX_SECRET_BYTES:
        raise TemporarySecretViewerError("Secret recovery content is too large.")

    safe_file_name = _safe_file_name(presentation.file_name)
    parent, memory_backed = _runtime_root(runtime_root)
    directory = Path(tempfile.mkdtemp(prefix="secret-view-", dir=parent))
    secret_path = directory / safe_file_name
    previous_handlers: dict[int, object] = {}
    try:
        os.chmod(directory, 0o700)
        descriptor = os.open(
            secret_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(secret_path, 0o400)
        storage = (
            "memory-backed runtime storage"
            if memory_backed
            else "temporary storage"
        )
        output(f"Opening {secret_path} from {storage} in read-only mode.")
        output(presentation.copy_instruction)
        environment = dict(os.environ)
        environment["EXINIT"] = "set noswapfile nobackup nowritebackup"
        previous_handlers = _temporary_signal_handlers()
        editor_status = launcher(_editor_command(editor, secret_path), environment)
        if editor_status != 0:
            output(
                f"[WARN] Editor exited with status {editor_status}; "
                "the temporary copy will still be deleted."
            )
    finally:
        if previous_handlers:
            _restore_signal_handlers(previous_handlers)
        _remove_private_view(directory)
        output(presentation.deleted_message)


def _available_editors(
    locator: Callable[[str], str | None],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return installed supported editors in preferred default order."""

    available: list[tuple[str, tuple[str, ...]]] = []
    seen_paths: set[str] = set()
    for name in ("nano", "vim", "vi"):
        resolved = locator(name)
        if resolved and resolved not in seen_paths:
            available.append((name, (resolved,)))
            seen_paths.add(resolved)
    for variable_name in ("VISUAL", "EDITOR"):
        configured = os.environ.get(variable_name, "").strip()
        if not configured:
            continue
        try:
            command = shlex.split(configured)
        except ValueError:
            continue
        if not command:
            continue
        resolved = locator(command[0])
        if not resolved:
            continue
        if resolved in seen_paths:
            continue
        available.append(
            (
                f"${variable_name}: {configured}",
                (resolved, *command[1:]),
            )
        )
        seen_paths.add(resolved)
    return tuple(available)


def _select_editor(
    editors: tuple[tuple[str, tuple[str, ...]], ...],
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> tuple[str, ...]:
    """Prompt for one installed editor with Enter selecting the first."""

    output("Select the terminal editor for this one-time secret view:")
    for index, (label, _) in enumerate(editors, start=1):
        suffix = " (default)" if index == 1 else ""
        output(f"  {index}) {label}{suffix}")
    while True:
        answer = input_reader(f"Editor [1-{len(editors)}] [1]: ").strip()
        if not answer:
            return editors[0][1]
        if answer.isdigit() and 1 <= int(answer) <= len(editors):
            return editors[int(answer) - 1][1]
        output("Choose one displayed editor number or press Enter for default.")


def offer_temporary_secret_view(
    secret: str,
    *,
    presentation: SecretViewPresentation = DEFAULT_PRESENTATION,
    input_reader: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    locator: Callable[[str], str | None] = shutil.which,
    runtime_root: Path | None = None,
    launcher: Callable[[Sequence[str], Mapping[str, str]], int] = _launch_editor,
) -> None:
    """Offer one opt-in editor view and otherwise retain no recovery file."""

    output("")
    output(presentation.heading)
    output("-" * len(presentation.heading))
    for notice in presentation.notices:
        output(notice)
    answer = input_reader(presentation.prompt).strip()
    if answer.lower() not in {"y", "yes", "j", "ja"}:
        output(presentation.skipped)
        return
    editors = _available_editors(locator)
    if not editors:
        output("[WARN] No supported terminal editor (nano, vim, or vi) is installed.")
        return
    editor = _select_editor(editors, input_reader, output)
    view_secret_temporarily(
        secret,
        editor,
        presentation=presentation,
        runtime_root=runtime_root,
        launcher=launcher,
        output=output,
    )


def consume_private_source_file(source_file: Path) -> str:
    """Read and delete one mode-0600 handoff without exposing its contents."""

    source = source_file.absolute()
    try:
        metadata = source.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise TemporarySecretViewerError(
                "Secret-view handoff must be a regular file, not a link."
            )
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise TemporarySecretViewerError(
                "Secret-view handoff must not be accessible by group or others."
            )
        open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, open_flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            secret = handle.read(MAX_SECRET_BYTES + 1)
    except OSError as error:
        raise TemporarySecretViewerError(
            "Unable to consume the protected secret-view handoff."
        ) from error
    finally:
        try:
            source.unlink(missing_ok=True)
        except OSError as error:
            raise TemporarySecretViewerError(
                "Unable to delete the protected secret-view handoff."
            ) from error

    if not secret:
        raise TemporarySecretViewerError("Secret-view handoff is empty.")
    if len(secret.encode("utf-8")) > MAX_SECRET_BYTES:
        raise TemporarySecretViewerError("Secret-view handoff is too large.")
    return secret


def _build_parser() -> argparse.ArgumentParser:
    """Build the shell-callable temporary secret viewer parser."""

    parser = argparse.ArgumentParser(
        description="Offer a private, read-only, self-deleting secret view."
    )
    parser.add_argument("--source-file", required=True, type=Path)
    parser.add_argument("--file-name", default=DEFAULT_PRESENTATION.file_name)
    parser.add_argument("--heading", default=DEFAULT_PRESENTATION.heading)
    parser.add_argument("--notice", action="append", dest="notices")
    parser.add_argument("--prompt", default=DEFAULT_PRESENTATION.prompt)
    parser.add_argument("--skipped", default=DEFAULT_PRESENTATION.skipped)
    parser.add_argument(
        "--copy-instruction",
        default=DEFAULT_PRESENTATION.copy_instruction,
    )
    parser.add_argument(
        "--deleted-message",
        default=DEFAULT_PRESENTATION.deleted_message,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Consume a protected handoff and run the shared optional viewer flow."""

    args = _build_parser().parse_args(argv)
    presentation = SecretViewPresentation(
        heading=args.heading,
        notices=tuple(args.notices or DEFAULT_PRESENTATION.notices),
        prompt=args.prompt,
        skipped=args.skipped,
        file_name=args.file_name,
        copy_instruction=args.copy_instruction,
        deleted_message=args.deleted_message,
    )
    try:
        secret = consume_private_source_file(args.source_file)
        offer_temporary_secret_view(secret, presentation=presentation)
        secret = ""
        return 0
    except KeyboardInterrupt:
        print("\n[WARN] Secret view interrupted; temporary files were deleted.")
        return 130
    except TemporarySecretViewerError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PRESENTATION",
    "SecretViewPresentation",
    "TemporarySecretViewerError",
    "consume_private_source_file",
    "offer_temporary_secret_view",
    "view_secret_temporarily",
]
