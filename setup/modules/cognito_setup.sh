#!/bin/bash

# Shared helpers for configuring AWS Cognito environment variables.
# This module can be sourced by other bash scripts (setup-wizard.sh, quick-start.sh)
# to provide a consistent interactive configuration flow.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
  local current_region current_pool current_client current_key current_secret
  current_region="$( _cognito_setup_get_env "AWS_REGION" )"
  current_pool="$( _cognito_setup_get_env "COGNITO_USER_POOL_ID" )"
  current_client="$( _cognito_setup_get_env "COGNITO_APP_CLIENT_ID" )"
  current_key="$( _cognito_setup_get_env "AWS_ACCESS_KEY_ID" )"
  current_secret="$( _cognito_setup_get_env "AWS_SECRET_ACCESS_KEY" )"

  local configured="false"
  if [[ -n "${current_region}" && -n "${current_pool}" ]]; then
    configured="true"
  fi

  if [[ "${configured}" == "true" ]]; then
    echo "⚠️  Existing Cognito configuration detected:"
    echo "    AWS_REGION=${current_region}"
    echo "    COGNITO_USER_POOL_ID=${current_pool}"
    if [ -n "${current_client}" ]; then
      echo "    COGNITO_APP_CLIENT_ID=${current_client}"
    fi
    echo ""
    read -p "Do you want to overwrite this configuration? (y/N): " overwrite_choice
    if [[ ! "${overwrite_choice}" =~ ^[Yy]$ ]]; then
      echo "ℹ️  Keeping existing Cognito configuration."
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
  local pool_prompt="${current_pool}"
  local client_prompt="${current_client}"
  local key_prompt="${current_key}"
  local secret_display=""
  if [ -n "${current_secret}" ]; then
    secret_display="[stored]"
  fi

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

  echo ""
  echo "🆔 Cognito User Pool ID"
  echo "    • AWS Console: User pool → Pool details → User pool ID."
  echo "    • Flutter config: amplifyconfiguration.dart → CognitoUserPool.Default.PoolId."
  while true; do
    read -p "Enter Cognito User Pool ID${pool_prompt:+ [${pool_prompt}]}: " input_pool
    input_pool="${input_pool:-${pool_prompt}}"
    if [[ -n "${input_pool}" ]]; then
      break
    fi
    echo "❌ Cognito User Pool ID cannot be empty."
  done

  echo ""
  echo "💻 Cognito App Client ID (optional)"
  echo "    • AWS Console: User pool → App integration → App client list."
  echo "    • Flutter config: amplifyconfiguration.dart → \"AppClientId\"."
  read -p "Enter Cognito App Client ID${client_prompt:+ [${client_prompt}] (optional)}: " input_client
  input_client="${input_client:-${client_prompt}}"

  echo ""
  echo "Optional: Provide IAM credentials if the backend requires Cognito admin APIs."
  echo "    • AWS Console: IAM → Users → Security credentials tab."
  read -p "AWS Access Key ID${key_prompt:+ [${key_prompt}] (optional)}: " input_key
  input_key="${input_key:-${key_prompt}}"

  echo "    • The Secret Access Key is shown only when you create or rotate the key."
  read -p "AWS Secret Access Key${secret_display:+ ${secret_display}} (optional): " input_secret
  if [[ -z "${input_secret}" && -n "${current_secret}" ]]; then
    input_secret="${current_secret}"
  fi

  _cognito_setup_update_env "AWS_REGION" "${input_region}"
  _cognito_setup_update_env "COGNITO_USER_POOL_ID" "${input_pool}"
  _cognito_setup_update_env "COGNITO_APP_CLIENT_ID" "${input_client}"
  _cognito_setup_update_env "AWS_ACCESS_KEY_ID" "${input_key}"
  _cognito_setup_update_env "AWS_SECRET_ACCESS_KEY" "${input_secret}"

  echo ""
  echo "✅ AWS Cognito configuration saved to ${_env_file}."
  echo "    AWS_REGION=${input_region}"
  echo "    COGNITO_USER_POOL_ID=${input_pool}"
  if [ -n "${input_client}" ]; then
    echo "    COGNITO_APP_CLIENT_ID=${input_client}"
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
