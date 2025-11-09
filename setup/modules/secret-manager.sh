#!/bin/bash
# Secret manager module
# Handles Docker secret creation

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
    echo "Press any key to open editor..."
    read -n 1 -r
    echo ""
    $EDITOR secret.txt
    
    if [ -f secret.txt ]; then
        docker secret create "$db_password_secret" secret.txt 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "✅ Created $db_password_secret"
        else
            echo "⚠️  Secret may already exist: $db_password_secret"
        fi
        rm -f secret.txt
    else
        echo "⚠️  Secret file not created, skipping"
    fi
    
    echo ""
    echo "Creating: $admin_api_key_secret"
    echo "Press any key to open editor..."
    read -n 1 -r
    echo ""
    $EDITOR secret.txt
    
    if [ -f secret.txt ]; then
        docker secret create "$admin_api_key_secret" secret.txt 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "✅ Created $admin_api_key_secret"
        else
            echo "⚠️  Secret may already exist: $admin_api_key_secret"
        fi
        rm -f secret.txt
    else
        echo "⚠️  Secret file not created, skipping"
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
