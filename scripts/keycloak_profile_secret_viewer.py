"""
Module: keycloak_profile_secret_viewer.py

Description:
    Preserves the Keycloak bootstrap import surface while delegating recovery
    views to the repository-wide temporary secret viewer.

Dependencies:
    - Python standard library.
    - scripts/temporary_secret_viewer.py.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from temporary_secret_viewer import (
    SecretViewPresentation,
    TemporarySecretViewerError,
    offer_temporary_secret_view as _shared_offer_temporary_secret_view,
    view_secret_temporarily as _shared_view_secret_temporarily,
)


KeycloakSecretViewerError = TemporarySecretViewerError

_KEYCLOAK_PRESENTATION = SecretViewPresentation(
    heading="Client-secret recovery copy",
    notices=(
        "Docker Swarm cannot reveal this secret again after this run.",
        "If selected, copy the value to your clipboard and save it yourself "
        "in an encrypted recovery store.",
        "The private read-only file is deleted immediately when the editor "
        "closes.",
    ),
    prompt="View the newly stored Keycloak secret now? [y/N]: ",
    skipped="Secret view skipped; the value remains only in Keycloak and Docker.",
    file_name="temp_keycloak_secret.txt",
    copy_instruction=(
        "Copy the value to your clipboard or recovery store, then close the editor."
    ),
    deleted_message="[OK] Deleted the temporary Keycloak secret file.",
)


def view_secret_temporarily(
    secret: str,
    editor: str,
    *,
    runtime_root: Path | None = None,
    launcher: Callable[[Sequence[str], Mapping[str, str]], int] | None = None,
    output: Callable[[str], None] = print,
) -> None:
    """Open one Keycloak value through the repository-wide viewer."""

    if launcher is None:
        _shared_view_secret_temporarily(
            secret,
            editor,
            presentation=_KEYCLOAK_PRESENTATION,
            runtime_root=runtime_root,
            output=output,
        )
        return
    _shared_view_secret_temporarily(
        secret,
        editor,
        presentation=_KEYCLOAK_PRESENTATION,
        runtime_root=runtime_root,
        launcher=launcher,
        output=output,
    )


def offer_temporary_secret_view(
    secret: str,
    *,
    input_reader: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    locator: Callable[[str], str | None] = shutil.which,
    runtime_root: Path | None = None,
    launcher: Callable[[Sequence[str], Mapping[str, str]], int] | None = None,
) -> None:
    """Offer the shared one-run viewer for a new Keycloak client secret."""

    if launcher is None:
        _shared_offer_temporary_secret_view(
            secret,
            presentation=_KEYCLOAK_PRESENTATION,
            input_reader=input_reader,
            output=output,
            locator=locator,
            runtime_root=runtime_root,
        )
        return
    _shared_offer_temporary_secret_view(
        secret,
        presentation=_KEYCLOAK_PRESENTATION,
        input_reader=input_reader,
        output=output,
        locator=locator,
        runtime_root=runtime_root,
        launcher=launcher,
    )


__all__ = [
    "KeycloakSecretViewerError",
    "offer_temporary_secret_view",
    "view_secret_temporarily",
]
