#!/bin/bash
# ==============================================================================
# data-dirs.sh - Data directory creation module
# ==============================================================================
#
# This module creates the data directories required by the active deployment
# profile. It also enforces the shared API-image UID/GID contract on writable
# bind mounts so host directories do not hide writable image-owned paths behind
# root-owned replacements. Nginx-only profiles only need the data root.
#
# Functions:
#   create_data_directories - Create all required data directories
#
# Directory structure created for API profiles:
#   $DATA_ROOT/
#     postgres_data/  (if local PostgreSQL)
#     pgadmin/         (if pgAdmin is enabled)
#     mongodb_data/    (if local MongoDB)
#     mongodb_config/  (if local MongoDB)
#     neo4j_data/      (if local Neo4j)
#     neo4j_logs/      (if local Neo4j)
#     backups/
#     logs/api/
#     redis_data/     (unless APP_REQUIRES_REDIS=false)
#
# Directory structure created for database-free API profiles:
#   $DATA_ROOT/
#     logs/api/
#     backups/
#
# Directory structure created for nginx profiles:
#   $DATA_ROOT/
#
# ==============================================================================

# Shared Python API images run as this non-root identity. Operators may override
# the values in the process environment when adopting a compatible custom image.
API_RUNTIME_UID="${API_RUNTIME_UID:-10001}"
API_RUNTIME_GID="${API_RUNTIME_GID:-10001}"

# ------------------------------------------------------------------------------
# _create_data_dir
# ------------------------------------------------------------------------------
# Ensures one directory exists and prints a consistent status line.
#
# Arguments:
#   $1 - path: directory path to create.
#   $2 - label: human-readable directory label for output.
#
# Returns:
#   0 on success, 1 when mkdir fails.
# ------------------------------------------------------------------------------
_create_data_dir() {
    local path="$1"
    local label="$2"

    if [ -d "$path" ]; then
        echo "[OK] ${label} already exists: $path"
        return 0
    fi

    echo "Creating ${label}: $path"
    if mkdir -p "$path"; then
        echo "[OK] Created: $path"
        return 0
    fi

    echo "[ERROR] Failed to create: $path"
    return 1
}

# ------------------------------------------------------------------------------
# _set_pgadmin_directory_owner
# ------------------------------------------------------------------------------
# Assigns the persistent pgAdmin directory to the container's documented
# runtime UID/GID so its configuration database remains writable.
#
# Arguments:
#   $1 - path: existing pgAdmin data directory.
#
# Returns:
#   0 after ownership is correct; 1 when chown is unavailable or fails.
#
# Side effects:
#   Changes only the selected pgAdmin directory ownership to 5050:5050.
# ------------------------------------------------------------------------------
_set_pgadmin_directory_owner() {
    local path="$1"

    if ! command -v chown >/dev/null 2>&1; then
        echo "[ERROR] chown is required for the pgAdmin data directory."
        return 1
    fi
    if chown 5050:5050 "$path"; then
        echo "[OK] pgAdmin ownership ready: ${path} (5050:5050)"
        return 0
    fi
    echo "[ERROR] Could not assign pgAdmin ownership: $path"
    return 1
}

# ------------------------------------------------------------------------------
# _set_api_writable_directory_owner
# ------------------------------------------------------------------------------
# Recursively assigns an API bind mount to the non-root runtime identity and
# guarantees owner read/write access without widening group or public access.
#
# Arguments:
#   $1 - path: existing API-owned writable directory.
#
# Returns:
#   0 after ownership and owner permissions are correct; otherwise 1.
#
# Side effects:
#   Changes ownership and owner permissions below the selected directory.
# ------------------------------------------------------------------------------
_set_api_writable_directory_owner() {
    local path="$1"

    if [ -z "$path" ] || [ "$path" = "/" ] || [ ! -d "$path" ]; then
        echo "[ERROR] Refusing unsafe or missing API data directory: ${path:-<empty>}"
        return 1
    fi
    case "$API_RUNTIME_UID" in
        ''|*[!0-9]*)
            echo "[ERROR] API_RUNTIME_UID must be a numeric UID."
            return 1
            ;;
    esac
    case "$API_RUNTIME_GID" in
        ''|*[!0-9]*)
            echo "[ERROR] API_RUNTIME_GID must be a numeric GID."
            return 1
            ;;
    esac
    if ! command -v chown >/dev/null 2>&1 || ! command -v chmod >/dev/null 2>&1; then
        echo "[ERROR] chown and chmod are required for API writable directories."
        return 1
    fi
    if ! chown -R -- "${API_RUNTIME_UID}:${API_RUNTIME_GID}" "$path"; then
        echo "[ERROR] Could not assign API runtime ownership: $path"
        echo "        Run quick-start with permission to chown deployment data."
        return 1
    fi
    if ! chmod -R u+rwX -- "$path"; then
        echo "[ERROR] Could not grant API owner access: $path"
        return 1
    fi
    echo "[OK] API runtime ownership ready: ${path} (${API_RUNTIME_UID}:${API_RUNTIME_GID})"
}

# ------------------------------------------------------------------------------
# _prepare_api_writable_directory
# ------------------------------------------------------------------------------
# Creates one API bind-mount directory and applies the runtime owner contract.
#
# Arguments:
#   $1 - path: directory path to create and prepare.
#   $2 - label: human-readable directory label for output.
#
# Returns:
#   0 when the directory is writable by the API runtime; otherwise 1.
# ------------------------------------------------------------------------------
_prepare_api_writable_directory() {
    local path="$1"
    local label="$2"

    _create_data_dir "$path" "$label" || return 1
    _set_api_writable_directory_owner "$path"
}

# ------------------------------------------------------------------------------
# create_data_directories
# ------------------------------------------------------------------------------
# Creates the data root and all profile-specific subdirectories. It skips service
# directories that are not used by the selected stack family.
#
# Arguments:
#   $1 - data_root: absolute path to the data root directory.
#   $2 - db_type: database type, or none.
#   $3 - db_mode: local, external, or none (defaults to active DB_MODE/local).
#
# Returns:
#   0 on success, 1 if any directory creation fails.
# ------------------------------------------------------------------------------
create_data_directories() {
    local data_root="$1"
    local db_type="$2"
    local db_mode="${3:-${DB_MODE:-local}}"
    local stack_family="${STACK_FAMILY:-api}"
    local requires_redis="${APP_REQUIRES_REDIS:-${REQUIRES_REDIS:-true}}"

    echo "[DATA] Creating Data Directories"
    echo "================================"
    echo ""

    _create_data_dir "$data_root" "Data root" || return 1

    if [ "$stack_family" = "api" ]; then
        _prepare_api_writable_directory \
            "$data_root/logs/api" \
            "API logs directory" || return 1
        _prepare_api_writable_directory \
            "$data_root/backups" \
            "Backup data directory" || return 1
    fi

    if [ "$stack_family" = "nginx" ] || [ "$db_type" = "none" ]; then
        echo "[INFO] Profile does not require database or Redis data directories."
        echo ""
        echo "[OK] All data directories ready"
        echo ""
        return 0
    fi

    if [ "$db_mode" = "local" ] && [ "$db_type" = "postgresql" ]; then
        _create_data_dir "$data_root/postgres_data" "PostgreSQL data directory" || return 1
        if [ "${PGADMIN_ENABLED:-false}" = "true" ]; then
            _create_data_dir "$data_root/pgadmin" "pgAdmin data directory" || return 1
            _set_pgadmin_directory_owner "$data_root/pgadmin" || return 1
        fi
    elif [ "$db_mode" = "local" ] && [ "$db_type" = "mongodb" ]; then
        _create_data_dir "$data_root/mongodb_data" "MongoDB data directory" || return 1
        _create_data_dir "$data_root/mongodb_config" "MongoDB config directory" || return 1
    elif [ "$db_mode" = "local" ] && [ "$db_type" = "neo4j" ]; then
        _create_data_dir "$data_root/neo4j_data" "Neo4j data directory" || return 1
        _create_data_dir "$data_root/neo4j_logs" "Neo4j logs directory" || return 1
    elif [ "$db_mode" = "external" ]; then
        echo "[INFO] External database selected; no local database directory is needed."
    fi

    if [ "$requires_redis" != "false" ]; then
        _create_data_dir "$data_root/redis_data" "Redis data directory" || return 1
    else
        echo "[INFO] Profile does not require Redis data directory."
    fi

    echo ""
    echo "[OK] All data directories ready"
    echo ""

    return 0
}
