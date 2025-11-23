# Stack conflict check module

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
