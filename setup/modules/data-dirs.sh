#!/bin/bash
# Data directory creation module
# Creates required data directories with existence checks

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
