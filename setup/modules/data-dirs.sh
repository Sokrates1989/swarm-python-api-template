#!/bin/bash
# ==============================================================================
# data-dirs.sh - Data directory creation module
# ==============================================================================
#
# This module creates the data directories required by the active deployment
# profile. Nginx-only and database-free profiles only need the data root; API
# profiles keep the historical database, backup, and Redis directories.
#
# Functions:
#   create_data_directories - Create all required data directories
#
# Directory structure created for API profiles:
#   $DATA_ROOT/
#     postgres_data/  (if PostgreSQL)
#     neo4j_data/     (if Neo4j)
#     neo4j_logs/     (if Neo4j)
#     backups/
#     redis_data/     (unless APP_REQUIRES_REDIS=false)
#
# Directory structure created for nginx/no-database profiles:
#   $DATA_ROOT/
#
# ==============================================================================

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
# create_data_directories
# ------------------------------------------------------------------------------
# Creates the data root and all profile-specific subdirectories. It skips service
# directories that are not used by the selected stack family.
#
# Arguments:
#   $1 - data_root: absolute path to the data root directory.
#   $2 - db_type: database type, or none.
#
# Returns:
#   0 on success, 1 if any directory creation fails.
# ------------------------------------------------------------------------------
create_data_directories() {
    local data_root="$1"
    local db_type="$2"
    local stack_family="${STACK_FAMILY:-api}"
    local requires_redis="${APP_REQUIRES_REDIS:-${REQUIRES_REDIS:-true}}"

    echo "[DATA] Creating Data Directories"
    echo "================================"
    echo ""

    _create_data_dir "$data_root" "Data root" || return 1

    if [ "$stack_family" = "nginx" ] || [ "$db_type" = "none" ]; then
        echo "[INFO] Profile does not require database, backup, or Redis data directories."
        echo ""
        echo "[OK] All data directories ready"
        echo ""
        return 0
    fi

    if [ "$db_type" = "postgresql" ]; then
        _create_data_dir "$data_root/postgres_data" "PostgreSQL data directory" || return 1
    elif [ "$db_type" = "neo4j" ]; then
        _create_data_dir "$data_root/neo4j_data" "Neo4j data directory" || return 1
        _create_data_dir "$data_root/neo4j_logs" "Neo4j logs directory" || return 1
    fi

    _create_data_dir "$data_root/backups" "Backup data directory" || return 1

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
