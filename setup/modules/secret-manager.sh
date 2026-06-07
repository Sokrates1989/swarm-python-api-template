#!/bin/bash
# ==============================================================================
# secret-manager.sh - Docker secrets management module
# ==============================================================================
#
# This module provides functions for creating, listing, and verifying Docker
# secrets used by the Swarm Python API Template stack. It supports interactive
# secret creation via nano/vim/vi editors and handles secret lifecycle
# (create, recreate, skip).
#
# Functions:
#   show_editor_instructions  - Display editor-specific usage tips
#   create_single_secret      - Create one Docker secret interactively
#   create_docker_secrets     - Create all required secrets for the stack
#   list_docker_secrets       - List all Docker secrets in Swarm
#   verify_secrets_exist      - Check that all required secrets exist
#
# Dependencies:
#   - Docker Swarm initialized (docker secret commands)
#   - nano, vim, or vi available for interactive editing
#
# ==============================================================================

# ------------------------------------------------------------------------------
# show_editor_instructions
# ------------------------------------------------------------------------------
# Displays usage tips for the selected text editor so users know how to save
# and exit when entering their secret value.
#
# Arguments:
#   $1 - editor name ("nano", "vim", or "vi")
# ------------------------------------------------------------------------------
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

create_secrets_from_file() {
    local db_password_secret="$1"
    local admin_api_key_secret="$2"
    local backup_restore_api_key_secret="$3"
    local backup_delete_api_key_secret="$4"
    local secrets_file="${5:-secrets.env}"
    local template_path="$6"

    echo ""
    echo "🔐 Create Docker Secrets from File"
    echo "==================================="
    echo ""

    if [ ! -f "$secrets_file" ]; then
        echo "⚠️  $secrets_file not found"
        echo ""

        if [ -n "$template_path" ] && [ -f "$template_path" ]; then
            echo "Creating $secrets_file from template..."
            cp "$template_path" "$secrets_file"
            echo "✅ Created $secrets_file"
            echo ""
            echo "📝 Please edit $secrets_file with your secret values, then run this option again."
            echo ""
            return 1
        fi

        echo "❌ No template found. Please create $secrets_file manually."
        return 1
    fi

    local db_password=""
    local admin_api_key=""
    local backup_restore_api_key=""
    local backup_delete_api_key=""

    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|\#*) continue ;;
        esac
        local key="${line%%=*}"
        local value="${line#*=}"
        case "$key" in
            DB_PASSWORD) db_password="$value" ;;
            ADMIN_API_KEY) admin_api_key="$value" ;;
            BACKUP_RESTORE_API_KEY) backup_restore_api_key="$value" ;;
            BACKUP_DELETE_API_KEY) backup_delete_api_key="$value" ;;
        esac
    done < "$secrets_file"

    local had_errors=false

    _create_secret_from_value() {
        local secret_name="$1"
        local secret_value="$2"
        local description="$3"

        secret_value="$(echo "$secret_value" | xargs)"

        if docker secret inspect "$secret_name" >/dev/null 2>&1; then
            read -p "Secret '$secret_name' exists. Delete and recreate? (y/N): " RECREATE
            if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
                docker secret rm "$secret_name" >/dev/null 2>&1 || return 1
            else
                return 0
            fi
        fi

        if [ -z "$secret_value" ]; then
            return 1
        fi

        printf '%s' "$secret_value" | docker secret create "$secret_name" - >/dev/null 2>&1
    }

    _create_secret_from_value "$db_password_secret" "$db_password" "DB password" || had_errors=true
    _create_secret_from_value "$admin_api_key_secret" "$admin_api_key" "Admin API key" || had_errors=true
    _create_secret_from_value "$backup_restore_api_key_secret" "$backup_restore_api_key" "Backup restore API key" || had_errors=true
    _create_secret_from_value "$backup_delete_api_key_secret" "$backup_delete_api_key" "Backup delete API key" || had_errors=true

    if [ "$had_errors" = true ]; then
        return 1
    fi

    return 0
}

# ------------------------------------------------------------------------------
# create_single_secret
# ------------------------------------------------------------------------------
# Prompts the user to enter a secret value in a text editor, then creates (or
# recreates) the corresponding Docker secret. Handles edge cases:
#   - Secret already exists: offer to delete and recreate.
#   - File empty/not saved: skip creation.
#
# Arguments:
#   $1 - secret_name: the Docker secret name to create
#   $2 - editor: which text editor to use (nano/vim/vi)
#
# Returns:
#   0 on success (secret created or kept existing)
#   1 on failure (secret not created)
# ------------------------------------------------------------------------------
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
            if [[ -r /dev/tty ]]; then
                read -r -p "Delete and recreate? (y/N): " RECREATE < /dev/tty
            else
                read -r -p "Delete and recreate? (y/N): " RECREATE
            fi
            if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
                local stack_name="${STACK_NAME:-}"
                if [ -z "$stack_name" ] && [ -f .env ]; then
                    stack_name=$(grep '^STACK_NAME=' .env 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r')
                fi
                if [ -n "$stack_name" ] && declare -F check_stack_conflict >/dev/null 2>&1; then
                    check_stack_conflict "$stack_name"
                    if docker stack ls --format "{{.Name}}" | grep -q "^${stack_name}$"; then
                        echo "❌ Cannot recreate secret while stack '$stack_name' is still running"
                        rm -f secret.txt
                        return 1
                    fi
                fi
                echo "Removing old secret..."
                if docker secret rm "$secret_name" >/dev/null 2>&1; then
                    echo "Creating new secret..."
                    if docker secret create "$secret_name" secret.txt >/dev/null 2>&1; then
                        echo "✅ Recreated $secret_name"
                        rm -f secret.txt
                        return 0
                    else
                        echo "❌ Failed to create secret"
                        echo "Error: Docker secret creation failed. Check if Docker Swarm is initialized."
                        rm -f secret.txt
                        return 1
                    fi
                else
                    echo "❌ Failed to remove old secret (may be in use)"
                    rm -f secret.txt
                    return 1
                fi
            else
                echo "⏭️  Keeping existing secret"
                rm -f secret.txt
                return 0  # Secret exists, so return success
            fi
        else
            echo "Creating secret..."
            if docker secret create "$secret_name" secret.txt >/dev/null 2>&1; then
                echo "✅ Created $secret_name"
                rm -f secret.txt
                return 0
            else
                echo "❌ Failed to create secret"
                echo "Error: Docker secret creation failed. Check if Docker Swarm is initialized."
                rm -f secret.txt
                return 1
            fi
        fi
    else
        echo "⚠️  Secret file is empty or not saved, skipping"
        rm -f secret.txt
        return 1  # No secret created
    fi
}

# ------------------------------------------------------------------------------
# create_docker_secrets
# ------------------------------------------------------------------------------
# Entry point for creating all stack secrets interactively. Detects available
# editors, then iterates through the four required secrets, calling
# create_single_secret for each.
#
# Arguments:
#   $1 - db_password_secret: name of the database password secret
#   $2 - admin_api_key_secret: name of the admin API key secret
#   $3 - backup_restore_api_key_secret: name of the backup restore key secret
#   $4 - backup_delete_api_key_secret: name of the backup delete key secret
#
# Returns:
#   0 on success (all secrets handled), 1 if no editor found
# ------------------------------------------------------------------------------
create_docker_secrets() {
    local db_password_secret="$1"
    local admin_api_key_secret="$2"
    local backup_restore_api_key_secret="$3"
    local backup_delete_api_key_secret="$4"
    local db_ui_admin_password_secret="${5:-}"
    
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
        if [ -n "$db_ui_admin_password_secret" ]; then
            echo "   - $db_ui_admin_password_secret"
        fi
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
        if [ -n "$db_ui_admin_password_secret" ]; then
            echo "  echo 'your-admin-ui-password' | docker secret create $db_ui_admin_password_secret -"
        fi
        return 1
    fi
    
    # Create all secrets using helper function
    create_single_secret "$db_password_secret" "$EDITOR"
    create_single_secret "$admin_api_key_secret" "$EDITOR"
    create_single_secret "$backup_restore_api_key_secret" "$EDITOR"
    create_single_secret "$backup_delete_api_key_secret" "$EDITOR"
    if [ -n "$db_ui_admin_password_secret" ]; then
        create_single_secret "$db_ui_admin_password_secret" "$EDITOR"
    fi
    
    echo ""
    echo "✅ Secret creation complete"
    echo ""
    
    return 0
}

# ------------------------------------------------------------------------------
# list_docker_secrets
# ------------------------------------------------------------------------------
# Lists all Docker secrets currently registered in the Swarm cluster.
# ------------------------------------------------------------------------------
list_docker_secrets() {
    echo "📋 Existing Docker Secrets"
    echo "========================="
    echo ""
    docker secret ls
    echo ""
}

# ------------------------------------------------------------------------------
# verify_secrets_exist
# ------------------------------------------------------------------------------
# Checks whether all four required secrets exist in Docker Swarm. Prints status
# for each secret and returns non-zero if any are missing.
#
# Arguments:
#   $1 - db_password_secret
#   $2 - admin_api_key_secret
#   $3 - backup_restore_api_key_secret
#   $4 - backup_delete_api_key_secret
#
# Returns:
#   0 if all secrets exist, 1 otherwise
# ------------------------------------------------------------------------------
verify_secrets_exist() {
    local db_password_secret="$1"
    local admin_api_key_secret="$2"
    local backup_restore_api_key_secret="$3"
    local backup_delete_api_key_secret="$4"
    
    local db_exists=0
    local api_exists=0
    local restore_exists=0
    local delete_exists=0

    docker secret inspect "$db_password_secret" >/dev/null 2>&1 && db_exists=1
    docker secret inspect "$admin_api_key_secret" >/dev/null 2>&1 && api_exists=1
    docker secret inspect "$backup_restore_api_key_secret" >/dev/null 2>&1 && restore_exists=1
    docker secret inspect "$backup_delete_api_key_secret" >/dev/null 2>&1 && delete_exists=1
    
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

# ------------------------------------------------------------------------------
# create_secret_from_value
# ------------------------------------------------------------------------------
# Creates a Docker secret from a provided value. Handles existing secrets
# by prompting for recreation if they already exist.
#
# Arguments:
#   $1 - secret_name: the full name of the Docker secret
#   $2 - secret_value: the value to store in the secret
#
# Returns:
#   0 on success, 1 on failure
#
# Outputs (stdout):
#   Status messages about secret creation
# ------------------------------------------------------------------------------
create_secret_from_value() {
    local secret_name="$1"
    local secret_value="$2"
    CREATE_SECRET_FROM_VALUE_ACTION="error"

    if docker secret inspect "$secret_name" >/dev/null 2>&1; then
        echo "⚠️  Secret '$secret_name' already exists."
        if [[ -r /dev/tty ]]; then
            read -r -p "   Delete and recreate? (y/N): " RECREATE < /dev/tty
        else
            read -r -p "   Delete and recreate? (y/N): " RECREATE
        fi
        if [[ "$RECREATE" =~ ^[Yy]$ ]]; then
            local stack_name="${STACK_NAME:-}"
            if [ -z "$stack_name" ] && [ -f .env ]; then
                stack_name=$(grep '^STACK_NAME=' .env 2>/dev/null | head -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r')
            fi
            if [ -n "$stack_name" ] && declare -F check_stack_conflict >/dev/null 2>&1; then
                check_stack_conflict "$stack_name"
                if docker stack ls --format "{{.Name}}" | grep -q "^${stack_name}$"; then
                    echo "❌ Cannot recreate secret while stack '$stack_name' is still running"
                    return 1
                fi
            fi
            docker secret rm "$secret_name" >/dev/null 2>&1 || {
                echo "❌ Failed to remove existing secret: $secret_name"
                return 1
            }
        else
            echo "   Skipping $secret_name (keeping existing)"
            CREATE_SECRET_FROM_VALUE_ACTION="kept"
            return 0
        fi
    fi

    if [ -z "$secret_value" ]; then
        echo "⚠️  Empty value for $secret_name, skipping"
        CREATE_SECRET_FROM_VALUE_ACTION="empty"
        return 0
    fi

    printf '%s' "$secret_value" | docker secret create "$secret_name" - >/dev/null 2>&1 && {
        CREATE_SECRET_FROM_VALUE_ACTION="created"
        return 0
    } || {
        echo "❌ Failed to create secret: $secret_name"
        return 1
    }
}

# ------------------------------------------------------------------------------
# create_secrets_from_env_file
# ------------------------------------------------------------------------------
# Creates Docker secrets from a secrets.env file. This is the main workflow
# function that orchestrates the entire secrets.env lifecycle:
# - Creates secrets.env from template if it doesn't exist
# - Syncs missing keys from template to existing secrets.env
# - Allows user to edit the file with their chosen editor
# - Creates Docker secrets from the file values
# - Optionally deletes the secrets.env file for security
#
# Arguments:
#   $1 - secrets_file: path to secrets.env (default: secrets.env)
#   $2 - template_file: path to template (default: setup/templates/secrets.env.template)
#   $3 - prefix: secret name prefix (required, e.g., myapp)
#
# Returns:
#   0 on success, 1 on failure
#
# Dependencies:
#   - choose_editor from user-prompts.sh
#   - sync_missing_secret_template_entries from secrets_template_sync.sh
# ------------------------------------------------------------------------------
create_secrets_from_env_file() {
    local secrets_file="${1:-secrets.env}"
    local template_file="${2:-setup/templates/secrets.env.template}"
    local prefix="${3:?Secret prefix is required}"

    echo ""
    echo "🔐 Create Docker Secrets from File"
    echo "==================================="
    echo ""

    # Create from template if it doesn't exist
    if [ ! -f "$secrets_file" ]; then
        if [ -f "$template_file" ]; then
            cp "$template_file" "$secrets_file"
            echo "✅ Created $secrets_file from template"
        else
            echo "❌ Template not found: $template_file"
            return 1
        fi
    fi

    # Sync missing keys from template
    if declare -F sync_missing_secret_template_entries >/dev/null 2>&1; then
        sync_missing_secret_template_entries "$secrets_file" "$template_file"
    fi

    echo ""
    echo "📝 Please edit $secrets_file and fill in your secret values."
    echo "   Secret names will be prefixed with: ${prefix}_"
    echo ""

    # Choose editor and open file
    if choose_editor; then
        read -p "Press Enter to open $secrets_file in $SELECTED_EDITOR..."
        echo ""
        "$SELECTED_EDITOR" "$secrets_file"
        echo ""
        echo "[OK] File saved: $secrets_file"
        echo ""
    else
        echo "⚠️  No editor found. Please edit $secrets_file manually, then continue."
        read -p "Press Enter when ready to create secrets..."
        echo ""
    fi

    # Parse and create secrets
    local key value created=0 skipped=0 kept=0
    while IFS='=' read -r key value || [ -n "$key" ]; do
        # Remove carriage returns (Windows line endings)
        key="${key%$'\r'}"
        value="${value%$'\r'}"

        # Trim whitespace around key and support optional export prefix
        key="${key#"${key%%[![:space:]]*}"}"
        key="${key%"${key##*[![:space:]]}"}"
        case "$key" in
            export\ *) key="${key#export }" ;;
        esac

        # Skip empty lines and comments
        [ -z "$key" ] && continue
        case "$key" in
            \#*) continue ;;
        esac

        # Normalize value: strip one outer quote pair if present
        value="${value#\"}"
        value="${value%\"}"
        value="${value#\'}"
        value="${value%\'}"

        if [ -n "$value" ]; then
            local full_name="${prefix}_${key}"
            if create_secret_from_value "$full_name" "$value"; then
                case "${CREATE_SECRET_FROM_VALUE_ACTION:-created}" in
                    created)
                        echo "✅ Secret created: $full_name"
                        created=$((created + 1))
                        ;;
                    kept)
                        kept=$((kept + 1))
                        ;;
                    empty)
                        skipped=$((skipped + 1))
                        ;;
                esac
            fi
        else
            skipped=$((skipped + 1))
        fi
    done < "$secrets_file"

    echo ""
    echo "✅ Created $created secret(s)"
    if [ $kept -gt 0 ]; then
        echo "   Kept $kept existing secret(s)"
    fi
    if [ $skipped -gt 0 ]; then
        echo "   Skipped $skipped empty value(s)"
    fi

    # Offer to delete the secrets file
    echo ""
    local delete_file=""
    read -p "Delete $secrets_file now? (recommended) (Y/n): " delete_file
    delete_file="${delete_file:-Y}"
    if [[ "$delete_file" =~ ^[Yy]$ ]]; then
        rm -f "$secrets_file" 2>/dev/null && echo "✅ Deleted $secrets_file"
    else
        echo "⚠️  $secrets_file still exists and may contain sensitive values."
        echo "   Please delete it soon: rm -f \"$secrets_file\""
    fi

    return 0
}

# ------------------------------------------------------------------------------
# check_required_secrets
# ------------------------------------------------------------------------------
# Checks if a list of required secrets exist in Docker Swarm. Prints status
# for each secret and returns non-zero if any are missing.
#
# Arguments:
#   $1 - prefix: secret name prefix
#   $@ - remaining args are secret base names to check
#
# Example:
#   check_required_secrets "myapp" "DB_PASSWORD" "ADMIN_API_KEY"
#
# Returns:
#   0 if all secrets exist, 1 otherwise
# ------------------------------------------------------------------------------
check_required_secrets() {
    local prefix="$1"
    shift
    local all_exist=true

    echo "📋 Checking required secrets with prefix: ${prefix}_"
    echo ""

    for base_name in "$@"; do
        local full_name="${prefix}_${base_name}"
        if docker secret inspect "$full_name" >/dev/null 2>&1; then
            echo "✅ ${full_name}"
        else
            echo "❌ ${full_name} (missing)"
            all_exist=false
        fi
    done

    echo ""
    if [ "$all_exist" = true ]; then
        echo "✅ All required secrets exist"
        return 0
    else
        echo "⚠️  Some required secrets are missing"
        return 1
    fi
}
