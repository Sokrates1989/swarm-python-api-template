"""Verified PostgreSQL backup and rollback-continuity helpers.

The module writes candidate-only backup evidence without sending database
content through terminal output. It also owns the isolated marker used to
prove data continuity during the RLS-13 automatic-rollback drill.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from felix_site_contract import FelixSiteProfile

from .command import CommandRunner
from .errors import FelixReleaseError
from .models import BackupEvidence, PreviousDeployment


API_SERVICE = "felix-new_api"
POSTGRES_SERVICE = "felix-new_postgres"
DIGEST_SEARCH = re.compile(r"@(?P<digest>sha256:[0-9a-f]{64})$")


def capture_previous_deployment(runner: CommandRunner) -> PreviousDeployment:
    """Capture candidate-only prior stack/service/image identity.

    Args:
        runner: Shell-free command runner.

    Returns:
        Previous candidate deployment state.
    """

    stacks = runner.run(
        ["docker", "stack", "ls", "--format", "{{.Name}}"],
        check=False,
    )
    stack_exists = "felix-new" in stacks.stdout.splitlines()
    inspected = runner.run(
        [
            "docker",
            "service",
            "inspect",
            API_SERVICE,
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        ],
        check=False,
    )
    if inspected.return_code != 0:
        return PreviousDeployment(stack_exists, False, None, None)
    try:
        image_reference = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError("Prior API service image is invalid JSON.") from exc
    digest_match = DIGEST_SEARCH.search(str(image_reference))
    digest = digest_match.group("digest") if digest_match else None
    return PreviousDeployment(
        stack_exists,
        True,
        str(image_reference),
        digest,
    )


def _postgres_container(runner: CommandRunner) -> str:
    """Resolve exactly one running candidate PostgreSQL task container.

    Args:
        runner: Shell-free command runner.

    Returns:
        Running container ID.

    Raises:
        FelixReleaseError: If zero or multiple containers are running.
    """

    result = runner.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.swarm.service.name={POSTGRES_SERVICE}",
            "--format",
            "{{.ID}}",
        ]
    )
    containers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(containers) != 1:
        raise FelixReleaseError("Expected exactly one running candidate PostgreSQL task.")
    return containers[0]


def _profile_database(profile: FelixSiteProfile) -> tuple[str, str, Path]:
    """Resolve public database identity and backup root from the profile.

    Args:
        profile: Validated Felix candidate profile.

    Returns:
        Database user, database name, and backup root.

    Raises:
        FelixReleaseError: If storage is not a mapping.
    """

    storage = profile.data["storage"]
    if not isinstance(storage, dict):
        raise FelixReleaseError("Felix storage profile is not an object.")
    return (
        profile.environment["DB_USER"],
        profile.environment["DB_NAME"],
        Path(str(storage["dataRoot"])) / "backups" / "release",
    )


def _backup_path(backup_root: Path, operation_id: str, suffix: str) -> Path:
    """Build one exact protected backup artifact path.

    Args:
        backup_root: Validated candidate backup root.
        operation_id: Public release operation identifier.
        suffix: Fixed artifact suffix.

    Returns:
        Backup path below a UTC date directory.
    """

    date_directory = datetime.now(timezone.utc).strftime("%Y%m%d")
    return backup_root / date_directory / f"{operation_id}.{suffix}"


def _sha256(path: Path) -> str:
    """Hash one retained backup artifact.

    Args:
        path: Existing backup path.

    Returns:
        Lowercase SHA-256 digest.
    """

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_pg_dump(container: str, dump_path: Path) -> None:
    """Require ``pg_restore --list`` to accept a custom-format dump.

    Args:
        container: Running PostgreSQL container ID.
        dump_path: Protected custom-format dump.

    Returns:
        None.

    Raises:
        FelixReleaseError: If verification fails.
    """

    try:
        with dump_path.open("rb") as dump:
            result = subprocess.run(
                ["docker", "exec", "-i", container, "pg_restore", "--list"],
                stdin=dump,
                check=False,
                capture_output=True,
            )
    except OSError as exc:
        raise FelixReleaseError("PostgreSQL dump verification could not run.") from exc
    if result.returncode != 0 or not result.stdout:
        raise FelixReleaseError("PostgreSQL dump structural verification failed.")


def _empty_database_evidence(
    profile: FelixSiteProfile,
    operation_id: str,
) -> BackupEvidence:
    """Record a verified empty initial PostgreSQL data state.

    Args:
        profile: Validated Felix candidate profile.
        operation_id: Public release operation identifier.

    Returns:
        Verified initial-empty-database evidence.

    Raises:
        FelixReleaseError: If unmanaged files exist or evidence cannot be
            protected and written.
    """

    _, _, backup_root = _profile_database(profile)
    postgres_root = backup_root.parents[1] / "postgres"
    if any(postgres_root.iterdir()):
        raise FelixReleaseError(
            "Initial deploy found unmanaged PostgreSQL data without a running service."
        )
    path = _backup_path(backup_root, operation_id, "initial-empty.json")
    payload = {
        "schemaVersion": 1,
        "kind": "initial-empty-database",
        "operationId": operation_id,
        "postgresDataDirectoryEmpty": True,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        raise FelixReleaseError("Unable to retain initial database evidence.") from exc
    return BackupEvidence(
        "initial-empty-database",
        path,
        _sha256(path),
        path.stat().st_size,
        True,
    )


def create_verified_backup(
    runner: CommandRunner,
    profile: FelixSiteProfile,
    previous: PreviousDeployment,
    operation_id: str,
) -> BackupEvidence:
    """Create and structurally verify the pre-deployment database backup.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.
        previous: Captured prior candidate deployment.
        operation_id: Public release operation identifier.

    Returns:
        Verified backup evidence.

    Raises:
        FelixReleaseError: If an existing database cannot be dumped/verified.

    Side Effects:
        Writes a protected custom-format dump, or a protected empty-state
        declaration for the first deployment.
    """

    if not previous.service_exists:
        return _empty_database_evidence(profile, operation_id)
    database_user, database_name, backup_root = _profile_database(profile)
    container = _postgres_container(runner)
    dump_path = _backup_path(backup_root, operation_id, "pgdump")
    try:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FelixReleaseError("Unable to create candidate backup directory.") from exc
    runner.run_to_file(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "--username",
            database_user,
            "--dbname",
            database_name,
            "--format=custom",
        ],
        dump_path,
    )
    dump_path.chmod(0o600)
    if dump_path.stat().st_size < 128:
        raise FelixReleaseError("PostgreSQL backup is unexpectedly small.")
    _verify_pg_dump(container, dump_path)
    return BackupEvidence(
        "pg-dump",
        dump_path,
        _sha256(dump_path),
        dump_path.stat().st_size,
        True,
    )


def create_continuity_marker(
    runner: CommandRunner,
    profile: FelixSiteProfile,
    marker: str,
) -> None:
    """Create one isolated database marker for the rollback drill.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.
        marker: Public random operation marker containing only hex/hyphen.

    Returns:
        None.

    Raises:
        FelixReleaseError: If the marker is unsafe or SQL execution fails.

    Side Effects:
        Creates a dedicated release-orchestration schema/table and one marker.
    """

    if not re.fullmatch(r"[0-9a-f-]{16,64}", marker):
        raise FelixReleaseError("Rollback continuity marker is invalid.")
    database_user, database_name, _ = _profile_database(profile)
    container = _postgres_container(runner)
    sql = (
        "CREATE SCHEMA IF NOT EXISTS release_orchestration; "
        "CREATE TABLE IF NOT EXISTS release_orchestration.markers "
        "(marker text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now()); "
        f"INSERT INTO release_orchestration.markers(marker) VALUES ('{marker}') "
        "ON CONFLICT (marker) DO NOTHING;"
    )
    runner.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "--username",
            database_user,
            "--dbname",
            database_name,
            "--set",
            "ON_ERROR_STOP=1",
            "--command",
            sql,
        ]
    )


def verify_continuity_marker(
    runner: CommandRunner,
    profile: FelixSiteProfile,
    marker: str,
) -> None:
    """Verify the rollback drill preserved its isolated database marker.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.
        marker: Previously inserted public marker.

    Returns:
        None.

    Raises:
        FelixReleaseError: If the marker is absent after rollback.
    """

    database_user, database_name, _ = _profile_database(profile)
    container = _postgres_container(runner)
    query = (
        "SELECT count(*) FROM release_orchestration.markers "
        f"WHERE marker = '{marker}';"
    )
    result = runner.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "--username",
            database_user,
            "--dbname",
            database_name,
            "--tuples-only",
            "--no-align",
            "--command",
            query,
        ]
    )
    if result.stdout.strip() != "1":
        raise FelixReleaseError("Rollback continuity marker was not preserved.")
