#!/bin/bash
# ==============================================================================
# data-dirs.sh - Data directory creation module
# ==============================================================================
#
# This module creates the required data directories for the stack based on
# the selected database type. It checks for existing directories and only
# creates those that are missing.
#
# Functions:
#   create_data_directories - Create all required data directories
#
# Directory structure created:
#   $DATA_ROOT/
#     postgres_data/  (if PostgreSQL)
#     neo4j_data/     (if Neo4j)
#     neo4j_logs/     (if Neo4j)
#     backups/
#     redis_data/
#
# ==============================================================================

# ------------------------------------------------------------------------------
# create_data_directories
# ------------------------------------------------------------------------------
# Creates the data root and all service-specific subdirectories. Skips
# directories that already exist.
#
# Arguments:
#   $1 - data_root: absolute path to the data root directory
#   $2 - db_type: "postgresql" or "neo4j"
#
# Returns:
#   0 on success, 1 if any directory creation fails
# ------------------------------------------------------------------------------
create_data_directories() {
    local data_root="$1"
    local db_type="$2"
    
    echo "📁 Creating Data Directories"
    echo "============================"
    echo ""
    
    # Create main data root
    if [ -d "$data_root" ]; then
        echo "✅ Data root already exists: $data_root"
    else
        echo "Creating data root: $data_root"
        mkdir -p "$data_root"
        if [ $? -eq 0 ]; then
            echo "✅ Created: $data_root"
        else
            echo "❌ Failed to create: $data_root"
            return 1
        fi
    fi
    
    # Create database-specific directories
    if [ "$db_type" = "postgresql" ]; then
        if [ -d "$data_root/postgres_data" ]; then
            echo "✅ PostgreSQL data directory already exists"
        else
            echo "Creating PostgreSQL data directory..."
            mkdir -p "$data_root/postgres_data"
            if [ $? -eq 0 ]; then
                echo "✅ Created: $data_root/postgres_data"
            else
                echo "❌ Failed to create: $data_root/postgres_data"
                return 1
            fi
        fi
    elif [ "$db_type" = "neo4j" ]; then
        if [ -d "$data_root/neo4j_data" ]; then
            echo "✅ Neo4j data directory already exists"
        else
            echo "Creating Neo4j data directory..."
            mkdir -p "$data_root/neo4j_data"
            if [ $? -eq 0 ]; then
                echo "✅ Created: $data_root/neo4j_data"
            else
                echo "❌ Failed to create: $data_root/neo4j_data"
                return 1
            fi
        fi
        
        if [ -d "$data_root/neo4j_logs" ]; then
            echo "✅ Neo4j logs directory already exists"
        else
            echo "Creating Neo4j logs directory..."
            mkdir -p "$data_root/neo4j_logs"
            if [ $? -eq 0 ]; then
                echo "✅ Created: $data_root/neo4j_logs"
            else
                echo "❌ Failed to create: $data_root/neo4j_logs"
                return 1
            fi
        fi
    fi

    
    # Create Backup directory
    if [ -d "$data_root/backups" ]; then
        echo "✅ Backup data directory already exists"
    else
        echo "Creating Backup data directory..."
        mkdir -p "$data_root/backups"
        if [ $? -eq 0 ]; then
            echo "✅ Created: $data_root/backups"
        else
            echo "❌ Failed to create: $data_root/backups"
            return 1
        fi
    fi

    
    # Create Redis directory
    if [ -d "$data_root/redis_data" ]; then
        echo "✅ Redis data directory already exists"
    else
        echo "Creating Redis data directory..."
        mkdir -p "$data_root/redis_data"
        if [ $? -eq 0 ]; then
            echo "✅ Created: $data_root/redis_data"
        else
            echo "❌ Failed to create: $data_root/redis_data"
            return 1
        fi
    fi
    
    echo ""
    echo "✅ All data directories ready"
    echo ""
    
    return 0
}
