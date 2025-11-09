#!/bin/bash
# Secret manager module
# Handles Docker secret creation

show_editor_instructions() {
    local editor="$1"
    
    if [ "$editor" = "nano" ]; then
        echo "Instructions for nano:"
        echo "  1. Type your secret"
        echo "  2. Press Ctrl+O to save"
        echo "  3. Press Enter to confirm filename"
        echo "  4. Press Ctrl+X to exit"
    elif [ "$editor" = "vim" ] || [ "$editor" = "vi" ]; then
        echo "Instructions for vim/vi:"
        echo "  1. Press 'i' to enter insert mode"
        echo "  2. Type your secret"
        echo "  3. Press Esc to exit insert mode"
        echo "  4. Type ':wq' and press Enter to save and quit"
    fi
    echo ""
    read -p "Press Enter to open editor..." -r
    echo ""
}

create_docker_secrets() {
    local db_password_secret="$1"
    local admin_api_key_secret="$2"
    
    echo "🔑 Create Docker Secrets"
    echo "======================="
    echo ""
    
    read -p "Create secrets now? (Y/n): " CREATE_SECRETS
    if [[ "$CREATE_SECRETS" =~ ^[Nn]$ ]]; then
        echo "Skipping secret creation."
        echo ""
        echo "⚠️  Remember to create these secrets before deploying:"
        echo "   - $db_password_secret"
        echo "   - $admin_api_key_secret"
        echo ""
        return 0
    fi
    
    # Detect editor
    local EDITOR=""
    if command -v nano &> /dev/null; then
        EDITOR="nano"
    elif command -v vim &> /dev/null; then
        EDITOR="vim"
    elif command -v vi &> /dev/null; then
        EDITOR="vi"
    else
        echo "❌ No text editor found (nano, vim, or vi required)"
        echo ""
        echo "Please create secrets manually:"
        echo "  echo 'your-password' | docker secret create $db_password_secret -"
        echo "  echo 'your-api-key' | docker secret create $admin_api_key_secret -"
        return 1
    fi
    
    echo ""
    echo "Creating: $db_password_secret"
    echo ""
    show_editor_instructions "$EDITOR"
    
    # Create empty file
    > secret.txt
    
    # Run editor and capture exit code
    set +e  # Temporarily disable exit on error
    $EDITOR secret.txt
    set -e  # Re-enable exit on error
    
    # Check if file has content
    if [ -f secret.txt ] && [ -s secret.txt ]; then
        # Check if secret already exists
        if docker secret inspect "$db_password_secret" &>/dev/null; then
            echo "⚠️  Secret '$db_password_secret' already exists"
            read -p "Delete and recreate? (y/N): " RECREATE
            if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
                docker secret rm "$db_password_secret" 2>/dev/null || true
                docker secret create "$db_password_secret" secret.txt 2>/dev/null
                if [ $? -eq 0 ]; then
                    echo "✅ Recreated $db_password_secret"
                else
                    echo "❌ Failed to create secret"
                fi
            else
                echo "⏭️  Keeping existing secret"
            fi
        else
            docker secret create "$db_password_secret" secret.txt 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "✅ Created $db_password_secret"
            else
                echo "❌ Failed to create secret"
            fi
        fi
        rm -f secret.txt
    else
        echo "⚠️  Secret file is empty or not saved, skipping"
        rm -f secret.txt
    fi
    
    echo ""
    echo "Creating: $admin_api_key_secret"
    echo ""
    show_editor_instructions "$EDITOR"
    
    # Create empty file
    > secret.txt
    
    # Run editor and capture exit code
    set +e  # Temporarily disable exit on error
    $EDITOR secret.txt
    set -e  # Re-enable exit on error
    
    # Check if file has content
    if [ -f secret.txt ] && [ -s secret.txt ]; then
        # Check if secret already exists
        if docker secret inspect "$admin_api_key_secret" &>/dev/null; then
            echo "⚠️  Secret '$admin_api_key_secret' already exists"
            read -p "Delete and recreate? (y/N): " RECREATE
            if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
                docker secret rm "$admin_api_key_secret" 2>/dev/null || true
                docker secret create "$admin_api_key_secret" secret.txt 2>/dev/null
                if [ $? -eq 0 ]; then
                    echo "✅ Recreated $admin_api_key_secret"
                else
                    echo "❌ Failed to create secret"
                fi
            else
                echo "⏭️  Keeping existing secret"
            fi
        else
            docker secret create "$admin_api_key_secret" secret.txt 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "✅ Created $admin_api_key_secret"
            else
                echo "❌ Failed to create secret"
            fi
        fi
        rm -f secret.txt
    else
        echo "⚠️  Secret file is empty or not saved, skipping"
        rm -f secret.txt
    fi
    
    echo ""
    echo "✅ Secret creation complete"
    echo ""
    
    return 0
}

list_docker_secrets() {
    echo "📋 Existing Docker Secrets"
    echo "========================="
    echo ""
    docker secret ls
    echo ""
}

verify_secrets_exist() {
    local db_password_secret="$1"
    local admin_api_key_secret="$2"
    
    local db_exists=$(docker secret ls --filter "name=${db_password_secret}" --format "{{.Name}}" | grep -c "^${db_password_secret}$")
    local api_exists=$(docker secret ls --filter "name=${admin_api_key_secret}" --format "{{.Name}}" | grep -c "^${admin_api_key_secret}$")
    
    if [ "$db_exists" -eq 0 ] || [ "$api_exists" -eq 0 ]; then
        echo "⚠️  Required secrets not found:"
        if [ "$db_exists" -eq 0 ]; then
            echo "   - $db_password_secret (missing)"
        else
            echo "   - $db_password_secret (exists)"
        fi
        if [ "$api_exists" -eq 0 ]; then
            echo "   - $admin_api_key_secret (missing)"
        else
            echo "   - $admin_api_key_secret (exists)"
        fi
        echo ""
        return 1
    fi
    
    echo "✅ All required secrets exist"
    echo ""
    return 0
}
