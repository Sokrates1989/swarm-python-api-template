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

create_single_secret() {
    local secret_name="$1"
    local editor="$2"
    
    echo ""
    echo "Creating: $secret_name"
    echo ""
    show_editor_instructions "$editor"
    
    # Create empty file
    > secret.txt
    
    # Run editor and capture exit code
    set +e  # Temporarily disable exit on error
    $editor secret.txt
    set -e  # Re-enable exit on error
    
    # Check if file has content
    if [ -f secret.txt ] && [ -s secret.txt ]; then
        # Check if secret already exists
        if docker secret inspect "$secret_name" &>/dev/null; then
            echo "⚠️  Secret '$secret_name' already exists"
            read -p "Delete and recreate? (y/N): " RECREATE
            if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
                docker secret rm "$secret_name" 2>/dev/null || true
                docker secret create "$secret_name" secret.txt 2>/dev/null
                if [ $? -eq 0 ]; then
                    echo "✅ Recreated $secret_name"
                else
                    echo "❌ Failed to create secret"
                fi
            else
                echo "⏭️  Keeping existing secret"
            fi
        else
            docker secret create "$secret_name" secret.txt 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "✅ Created $secret_name"
            else
                echo "❌ Failed to create secret"
            fi
        fi
        rm -f secret.txt
    else
        echo "⚠️  Secret file is empty or not saved, skipping"
        rm -f secret.txt
    fi
}

create_docker_secrets() {
    local db_password_secret="$1"
    local admin_api_key_secret="$2"
    local backup_restore_api_key_secret="$3"
    local backup_delete_api_key_secret="$4"
    
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
        echo "   - $backup_restore_api_key_secret"
        echo "   - $backup_delete_api_key_secret"
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
        echo "  echo 'your-restore-key' | docker secret create $backup_restore_api_key_secret -"
        echo "  echo 'your-delete-key' | docker secret create $backup_delete_api_key_secret -"
        return 1
    fi
    
    # Create all secrets using helper function
    create_single_secret "$db_password_secret" "$EDITOR"
    create_single_secret "$admin_api_key_secret" "$EDITOR"
    create_single_secret "$backup_restore_api_key_secret" "$EDITOR"
    create_single_secret "$backup_delete_api_key_secret" "$EDITOR"
    
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
    local backup_restore_api_key_secret="$3"
    local backup_delete_api_key_secret="$4"
    
    local db_exists=$(docker secret ls --filter "name=${db_password_secret}" --format "{{.Name}}" | grep -c "^${db_password_secret}$")
    local api_exists=$(docker secret ls --filter "name=${admin_api_key_secret}" --format "{{.Name}}" | grep -c "^${admin_api_key_secret}$")
    local restore_exists=$(docker secret ls --filter "name=${backup_restore_api_key_secret}" --format "{{.Name}}" | grep -c "^${backup_restore_api_key_secret}$")
    local delete_exists=$(docker secret ls --filter "name=${backup_delete_api_key_secret}" --format "{{.Name}}" | grep -c "^${backup_delete_api_key_secret}$")
    
    if [ "$db_exists" -eq 0 ] || [ "$api_exists" -eq 0 ] || [ "$restore_exists" -eq 0 ] || [ "$delete_exists" -eq 0 ]; then
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
        if [ "$restore_exists" -eq 0 ]; then
            echo "   - $backup_restore_api_key_secret (missing)"
        else
            echo "   - $backup_restore_api_key_secret (exists)"
        fi
        if [ "$delete_exists" -eq 0 ]; then
            echo "   - $backup_delete_api_key_secret (missing)"
        else
            echo "   - $backup_delete_api_key_secret (exists)"
        fi
        echo ""
        return 1
    fi
    
    echo "✅ All required secrets exist"
    echo ""
    return 0
}
