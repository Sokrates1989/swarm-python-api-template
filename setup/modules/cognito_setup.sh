#!/bin/bash

# Shared helpers for configuring AWS Cognito environment variables.
# This module can be sourced by other bash scripts (setup-wizard.sh, quick-start.sh)
# to provide a consistent interactive configuration flow.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source secret-manager module for file-based secret creation
source "${SCRIPT_DIR}/secret-manager.sh"

_env_file="${PROJECT_ROOT}/.env"

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
  
  # Ask which optional secrets to create
  echo "Which secrets do you want to create?"
  echo ""
  echo "Required:"
  echo "  - ${pool_id_secret} (Cognito User Pool ID)"
  echo ""
  read -p "Create App Client ID secret? (y/N): " create_client
  read -p "Create IAM Access Key secrets? (y/N): " create_iam
  echo ""
  
  read -p "Create Docker secrets for Cognito configuration? (Y/n): " create_secrets
  if [[ ! "${create_secrets}" =~ ^[Nn]$ ]]; then
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
        if [[ "${create_client}" =~ ^[Yy]$ ]]; then
          echo "  echo 'your-client-id' | docker secret create ${client_id_secret} -"
        fi
        if [[ "${create_iam}" =~ ^[Yy]$ ]]; then
          echo "  echo 'your-access-key' | docker secret create ${access_key_secret} -"
          echo "  echo 'your-secret-key' | docker secret create ${secret_key_secret} -"
        fi
        return 1
    fi
    
    echo ""
    echo "You'll be prompted to enter each secret value in an editor."
    echo "The secrets will be securely stored in Docker and the temporary files will be deleted."
    echo ""
    
    # Create required secrets
    create_single_secret "${pool_id_secret}" "${EDITOR}"
    
    # Create optional secrets
    if [[ "${create_client}" =~ ^[Yy]$ ]]; then
      create_single_secret "${client_id_secret}" "${EDITOR}"
    fi
    
    if [[ "${create_iam}" =~ ^[Yy]$ ]]; then
      create_single_secret "${access_key_secret}" "${EDITOR}"
      create_single_secret "${secret_key_secret}" "${EDITOR}"
    fi
    
    echo ""
    echo "✅ Cognito secrets created"
  else
    echo "ℹ️  Skipping secret creation. You can create them manually later."
  fi

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
