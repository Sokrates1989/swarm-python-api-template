#!/bin/bash

# Shared helpers for configuring AWS Cognito environment variables.
# This module can be sourced by other bash scripts (setup-wizard.sh, quick-start.sh)
# to provide a consistent interactive configuration flow.

set -e

COGNITO_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COGNITO_PROJECT_ROOT="$(cd "${COGNITO_SETUP_DIR}/../.." && pwd)"

# Source secret-manager module for file-based secret creation
source "${COGNITO_SETUP_DIR}/secret-manager.sh"

_env_file="${COGNITO_PROJECT_ROOT}/.env"

_cognito_setup_is_macos() {
  case "$(uname)" in
    Darwin*) return 0 ;;
    *) return 1 ;;
  esac
}

_cognito_setup_ensure_env_file() {
  if [ -f "${_env_file}" ]; then
    return 0
  fi

  echo "❌ .env file does not exist. Cannot configure Cognito." >&2
  echo "Please run the setup wizard first to create the .env file." >&2
  return 1
}

_cognito_setup_get_env() {
  local key="$1"
  if [ ! -f "${_env_file}" ]; then
    echo ""
    return
  fi
  grep -E "^${key}=" "${_env_file}" | head -n1 | cut -d'=' -f2-
}

_cognito_setup_update_env() {
  local key="$1"
  local value="$2"

  if declare -F update_env_values >/dev/null 2>&1; then
    update_env_values "${_env_file}" "${key}" "${value}"
    return 0
  fi

  if grep -qE "^${key}=" "${_env_file}" 2>/dev/null; then
    if _cognito_setup_is_macos; then
      sed -i '' "s|^${key}=.*|${key}=${value}|" "${_env_file}"
    else
      sed -i "s|^${key}=.*|${key}=${value}|" "${_env_file}"
    fi
  else
    echo "${key}=${value}" >> "${_env_file}"
  fi
}


_run_cognito_prompts() {
  local current_region
  current_region="$( _cognito_setup_get_env "AWS_REGION" )"

  local configured="false"
  if [[ -n "${current_region}" ]]; then
    configured="true"
  fi

  if [[ "${configured}" == "true" ]]; then
    echo "⚠️  Existing AWS Region configuration detected:"
    echo "    AWS_REGION=${current_region}"
    echo ""
    read -p "Do you want to overwrite this configuration? (y/N): " overwrite_choice
    if [[ ! "${overwrite_choice}" =~ ^[Yy]$ ]]; then
      echo "ℹ️  Keeping existing configuration."
      return 0
    fi
  fi

  echo "🔧 AWS Cognito Configuration"
  echo "---------------------------"
  echo ""
  echo "You'll need a few values from your AWS Cognito User Pool."
  echo "Tips:"
  echo "  • AWS Console → Cognito → User pools → select your pool."
  echo "  • Flutter config → lib/utils/authentication/config/amplifyconfiguration.dart."

  local region_prompt="${current_region}"

  local input_region input_pool input_client input_key input_secret

  echo ""
  echo "🌍 AWS Region"
  echo "    • Example: eu-central-1"
  echo "    • AWS Console: shown near the top-right or under Pool details."
  echo "    • Flutter config: look for \"Region\" inside amplifyconfiguration.dart."
  while true; do
    read -p "Enter AWS Region${region_prompt:+ [${region_prompt}]}: " input_region
    input_region="${input_region:-${region_prompt}}"
    if [[ -n "${input_region}" ]]; then
      break
    fi
    echo "❌ AWS Region cannot be empty."
  done

  # Write only AWS_REGION to .env (secrets will be stored as Docker secrets only)
  _cognito_setup_update_env "AWS_REGION" "${input_region}"

  echo ""
  echo "✅ AWS Region saved to ${_env_file}"
  echo "    AWS_REGION=${input_region}"

  # Create Docker secrets for Cognito configuration
  echo ""
  echo "🔑 Creating Docker Secrets for AWS Cognito"
  echo "=========================================="
  echo ""
  echo "Cognito secrets must be stored as Docker secrets (not in .env)."
  echo "You'll enter each secret value in an editor."
  echo ""
  
  # Get stack name from .env
  local stack_name
  stack_name="$( _cognito_setup_get_env "STACK_NAME" )"
  if [ -z "${stack_name}" ]; then
    stack_name="api_production"
  fi
  
  # Generate secret names
  local stack_name_upper
  stack_name_upper=$(echo "$stack_name" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')
  local pool_id_secret="${stack_name_upper}_COGNITO_USER_POOL_ID"
  local client_id_secret="${stack_name_upper}_COGNITO_APP_CLIENT_ID"
  local access_key_secret="${stack_name_upper}_AWS_ACCESS_KEY_ID"
  local secret_key_secret="${stack_name_upper}_AWS_SECRET_ACCESS_KEY"
  
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
      echo "  echo 'your-pool-id' | docker secret create ${pool_id_secret} -"
      return 1
  fi
  
  echo "🔑 Creating Docker Secrets for AWS Cognito"
  echo "=========================================="
  echo ""
  echo "Cognito secrets must be stored as Docker secrets (not in .env)."
  echo "You'll enter each secret value in an editor."
  echo ""
  echo "💡 Tips:"
  echo "  • Required: User Pool ID (find in AWS Console → Cognito → User pools)"
  echo "  • Optional: Leave editor empty (save without typing) to skip a secret"
  echo "  • IAM keys only needed if using Cognito Admin API features"
  echo ""
  read -p "Continue? (Y/n): " continue_choice
  if [[ "${continue_choice}" =~ ^[Nn]$ ]]; then
    echo "ℹ️  Skipping secret creation."
    return 1
  fi
  
  # Track which secrets were created
  export COGNITO_CREATED_SECRETS=""
  
  # Create User Pool ID (required)
  echo ""
  echo "📋 Secret 1/4: Cognito User Pool ID (REQUIRED)"
  echo "    • AWS Console: Cognito → User pools → select pool → copy 'User pool ID'"
  echo "    • Flutter: amplifyconfiguration.dart → PoolId"
  echo "    • Example: eu-central-1_AbCdEfGhI"
  if create_single_secret "${pool_id_secret}" "${EDITOR}"; then
    COGNITO_CREATED_SECRETS="${COGNITO_CREATED_SECRETS} ${pool_id_secret}"
  fi
  
  # Create App Client ID (optional)
  echo ""
  echo "📱 Secret 2/4: App Client ID (OPTIONAL)"
  echo "    • AWS Console: Cognito → User pools → select pool → App integration → App clients"
  echo "    • Flutter: amplifyconfiguration.dart → AppClientId"
  echo "    • Leave empty to skip (not required for basic JWT verification)"
  if create_single_secret "${client_id_secret}" "${EDITOR}"; then
    COGNITO_CREATED_SECRETS="${COGNITO_CREATED_SECRETS} ${client_id_secret}"
  fi
  
  # Create AWS Access Key ID (optional)
  echo ""
  echo "🔐 Secret 3/4: AWS Access Key ID (OPTIONAL)"
  echo "    • Only needed for Cognito Admin API (e.g., user management from backend)"
  echo "    • AWS Console: IAM → Users → Security credentials → Access keys"
  echo "    • Leave empty to skip (not needed for JWT verification)"
  if create_single_secret "${access_key_secret}" "${EDITOR}"; then
    COGNITO_CREATED_SECRETS="${COGNITO_CREATED_SECRETS} ${access_key_secret}"
  fi
  
  # Create AWS Secret Access Key (optional)
  echo ""
  echo "🔐 Secret 4/4: AWS Secret Access Key (OPTIONAL)"
  echo "    • Only needed if you created Access Key ID above"
  echo "    • AWS Console: IAM → Users → Security credentials → Access keys"
  echo "    • Leave empty to skip"
  if create_single_secret "${secret_key_secret}" "${EDITOR}"; then
    COGNITO_CREATED_SECRETS="${COGNITO_CREATED_SECRETS} ${secret_key_secret}"
  fi
  
  echo ""
  if [ -n "${COGNITO_CREATED_SECRETS}" ]; then
    echo "✅ Cognito secrets created"
  else
    echo "⚠️  No secrets were created"
    return 1
  fi

  # Export list of created secrets for use by stack updater
  export COGNITO_CREATED_SECRETS
  return 0
}

run_cognito_setup() {
  if ! _cognito_setup_ensure_env_file; then
    return 1
  fi

  echo ""
  read -p "Would you like to configure AWS Cognito settings now? (y/N): " configure_choice
  if [[ ! "${configure_choice}" =~ ^[Yy]$ ]]; then
    echo "ℹ️  Skipping AWS Cognito configuration."
    return 0
  fi

  if ! _run_cognito_prompts; then
    return 1
  fi

  return 0
}
