#!/bin/bash
# ==============================================================================
# stack-conflict-check.sh - Docker Swarm stack conflict detection
# ==============================================================================
#
# This module checks whether a stack with the given name is already deployed
# in Docker Swarm. If so, it offers to remove it before continuing, since
# secrets cannot be updated while in use.
#
# Functions:
#   check_stack_conflict - Detect and optionally remove an existing stack
#
# Dependencies:
#   - Docker Swarm initialized
#
# ==============================================================================

# ------------------------------------------------------------------------------
# check_stack_conflict
# ------------------------------------------------------------------------------
# Checks if a stack with the given name exists. If it does, prompts the user
# to remove it (useful before secret updates or fresh deployments).
#
# Arguments:
#   $1 - stack_name: the Docker stack name to check
#
# Returns:
#   0 always (continues regardless of user choice)
# ------------------------------------------------------------------------------
check_stack_conflict() {
    local stack_name="$1"
    
    echo ""
    echo "🔍 Checking for existing stack..."
    
    if docker stack ls --format "{{.Name}}" | grep -q "^${stack_name}$"; then
        echo "⚠️  WARNING: Stack '$stack_name' is already running!"
        echo ""
        echo "This may interfere with deployment or secret updates."
        echo "Secrets cannot be updated while they are in use by a running stack."
        echo ""
        read -p "Remove existing stack before continuing? (y/N): " REMOVE_STACK
        
        if [[ "$REMOVE_STACK" =~ ^[Yy]$ ]]; then
            echo ""
            echo "Removing stack: $stack_name"
            docker stack rm "$stack_name"
            
            echo "Waiting for stack to be fully removed..."
            # Wait for services to be removed
            sleep 2
            while docker stack ls --format "{{.Name}}" | grep -q "^${stack_name}$"; do
                echo -n "."
                sleep 2
            done
            echo ""
            echo "✅ Stack removed successfully"
            echo ""
            return 0
        else
            echo ""
            echo "⚠️  Continuing with existing stack running."
            echo "Note: You may encounter errors when creating/updating secrets."
            echo ""
            return 0
        fi
    else
        echo "✅ No conflicting stack found"
        echo ""
        return 0
    fi
}
