"""
Module: keycloak_profile_secret_viewer.py

Description:
    Offers an explicit, one-run recovery view for a newly created or rotated
    Keycloak client secret. The value is written to a private temporary file,
    opened read-only in an operator-selected terminal editor, and deleted as
    soon as the editor closes or the viewing process is interrupted.

Dependencies:
    - Python standard library.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


class KeycloakSecretViewerError(RuntimeError):
    """Raised when a requested temporary secret view cannot remain safe."""


def _runtime_root(explicit_root: Path | None = None) -> tuple[Path, bool]:
    """Resolve the safest available parent for one private temporary folder.

    Args:
        explicit_root: Optional test/operator override that must already exist.

    Returns:
        Parent directory and whether it is expected to be memory-backed.

    Raises:
        KeycloakSecretViewerError: If an explicit root is unusable or no
            writable temporary directory is available.
    """

    if explicit_root is not None:
        root = explicit_root.resolve()
        if not root.is_dir() or not os.access(root, os.W_OK):
            raise KeycloakSecretViewerError(
                f"Temporary secret directory is not writable: {root}"
            )
        return root, False
    candidates = []
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
    raise KeycloakSecretViewerError(
        "No writable temporary directory is available for secret viewing."
    )


def _editor_command(editor: str, secret_path: Path) -> tuple[str, ...]:
    """Build a read-only, backup-resistant editor argument vector.

    Args:
        editor: Resolved nano, vim, or vi executable.
        secret_path: Private temporary secret file.

    Returns:
        Editor command that does not place the secret value in arguments.
    """

    name = Path(editor).name.lower()
    if name.startswith("nano"):
        return (editor, "--ignorercfiles", "--view", str(secret_path))
    if name.startswith("vim"):
        return (
            editor,
            "-Nu",
            "NONE",
            "-n",
            "-R",
            "-i",
            "NONE",
            str(secret_path),
        )
    return (editor, "-R", str(secret_path))


def _launch_editor(
    command: Sequence[str],
    environment: Mapping[str, str],
) -> int:
    """Run the selected editor and terminate it when the parent is interrupted.

    Args:
        command: Read-only editor argument vector.
        environment: Child environment with backup-resistant vi defaults.

    Returns:
        Editor process exit status.

    Side Effects:
        Starts and waits for one interactive terminal editor process.
    """

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
    """Delete every file in one freshly created private viewer directory.

    Args:
        directory: Exact directory created by this viewer invocation.

    Raises:
        KeycloakSecretViewerError: If an unexpected nested directory or a
            cleanup failure prevents complete deletion.

    Side Effects:
        Unlinks editor sidecars, the secret file, and the private directory.
    """

    try:
        if directory.exists():
            for child in directory.iterdir():
                if child.is_dir() and not child.is_symlink():
                    raise KeycloakSecretViewerError(
                        f"Unexpected nested directory blocks cleanup: {child}"
                    )
                if not child.is_symlink():
                    child.chmod(0o600)
                child.unlink(missing_ok=True)
            directory.rmdir()
    except OSError as error:
        raise KeycloakSecretViewerError(
            f"Unable to delete temporary Keycloak secret view: {directory}"
        ) from error


def _temporary_signal_handlers() -> dict[int, object]:
    """Install handlers that convert termination into cleanup-capable errors.

    Returns:
        Previous handlers keyed by supported signal number.

    Side Effects:
        Temporarily replaces SIGHUP and SIGTERM handlers in the main thread.
    """

    previous: dict[int, object] = {}

    def interrupt_view(signum: int, frame: object) -> None:
        """Raise an interrupt so the viewer's ``finally`` cleanup executes.

        Args:
            signum: Received process signal number.
            frame: Interpreter frame supplied by the signal runtime.

        Raises:
            KeyboardInterrupt: Always, so the enclosing cleanup runs.
        """

        del signum, frame
        raise KeyboardInterrupt

    for signal_name in ("SIGHUP", "SIGTERM"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is not None:
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, interrupt_view)
    return previous


def _restore_signal_handlers(previous: Mapping[int, object]) -> None:
    """Restore handlers replaced for one temporary viewing session.

    Args:
        previous: Original handlers keyed by signal number.

    Side Effects:
        Restores process signal handling.
    """

    for signal_number, handler in previous.items():
        signal.signal(signal_number, handler)


def view_secret_temporarily(
    secret: str,
    editor: str,
    *,
    runtime_root: Path | None = None,
    launcher: Callable[[Sequence[str], Mapping[str, str]], int] = _launch_editor,
    output: Callable[[str], None] = print,
) -> None:
    """Open a new client secret read-only and delete its temporary storage.

    Args:
        secret: Exact newly proven Keycloak client secret held in memory.
        editor: Resolved nano, vim, or vi executable.
        runtime_root: Optional temporary-parent override, primarily for tests.
        launcher: Injectable interactive editor boundary.
        output: Operator-facing message callback.

    Raises:
        KeycloakSecretViewerError: If secure creation or cleanup fails.
        KeyboardInterrupt: If the operator interrupts the editor session after
            cleanup has completed.

    Side Effects:
        Creates a mode-0400 file in a mode-0700 directory, starts the editor,
        and deletes all files in that directory immediately afterward.
    """

    if not secret:
        raise KeycloakSecretViewerError("Keycloak returned an empty client secret.")
    parent, memory_backed = _runtime_root(runtime_root)
    directory = Path(tempfile.mkdtemp(prefix="keycloak-secret-view-", dir=parent))
    secret_path = directory / "temp_keycloak_secret.txt"
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
        output("Copy the value to your recovery store, then close the editor.")
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
        output("[OK] Deleted the temporary Keycloak secret file.")


def _available_editors(
    locator: Callable[[str], str | None],
) -> tuple[tuple[str, str], ...]:
    """Return installed supported editors in preferred default order.

    Args:
        locator: Executable lookup callback compatible with ``shutil.which``.

    Returns:
        Label/path pairs for nano, vim, and vi when installed.
    """

    available = []
    seen_paths: set[str] = set()
    for name in ("nano", "vim", "vi"):
        resolved = locator(name)
        if resolved and resolved not in seen_paths:
            available.append((name, resolved))
            seen_paths.add(resolved)
    return tuple(available)


def _select_editor(
    editors: tuple[tuple[str, str], ...],
    input_reader: Callable[[str], str],
    output: Callable[[str], None],
) -> str:
    """Prompt for one installed editor with Enter selecting the first.

    Args:
        editors: Available label/path pairs.
        input_reader: Operator input callback.
        output: Operator-facing message callback.

    Returns:
        Resolved selected editor path.
    """

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
    input_reader: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    locator: Callable[[str], str | None] = shutil.which,
    runtime_root: Path | None = None,
    launcher: Callable[[Sequence[str], Mapping[str, str]], int] = _launch_editor,
) -> None:
    """Offer an opt-in editor view for a newly bound client secret.

    Args:
        secret: Exact Keycloak value just proven and stored in Docker Swarm.
        input_reader: Operator input callback.
        output: Operator-facing message callback.
        locator: Supported-editor lookup callback.
        runtime_root: Optional temporary-parent override, primarily for tests.
        launcher: Injectable interactive editor boundary.

    Side Effects:
        May prompt, create a private temporary file, start an editor, and
        delete the temporary file immediately after the editor closes.
    """

    output("")
    output("Client-secret recovery copy")
    output("---------------------------")
    output("Docker Swarm cannot reveal this secret again after this run.")
    output("If selected, a private read-only file is opened only for copying")
    output("and is deleted immediately when the editor closes.")
    answer = input_reader("View the newly stored Keycloak secret now? [y/N]: ").strip()
    if answer.lower() not in {"y", "yes"}:
        output("Secret view skipped; the value remains only in Keycloak and Docker.")
        return
    editors = _available_editors(locator)
    if not editors:
        output("[WARN] No supported terminal editor (nano, vim, or vi) is installed.")
        return
    editor = _select_editor(editors, input_reader, output)
    view_secret_temporarily(
        secret,
        editor,
        runtime_root=runtime_root,
        launcher=launcher,
        output=output,
    )


__all__ = [
    "KeycloakSecretViewerError",
    "offer_temporary_secret_view",
    "view_secret_temporarily",
]
