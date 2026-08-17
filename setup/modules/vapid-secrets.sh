#!/bin/bash
# ==============================================================================
# vapid-secrets.sh - Profile-driven Web Push VAPID Docker-secret setup
# ==============================================================================
#
# A VAPID public key and private key are one cryptographic pair. This module
# discovers their exact Docker-secret names from enabled profile secret mounts,
# generates one P-256 pair locally, creates both secrets without printing either
# value, and offers an explicit self-deleting recovery view for manual backup.
# ==============================================================================

_VAPID_SECRETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_VAPID_SECRETS_DIR}/operator-menu-localization.sh"
source "${_VAPID_SECRETS_DIR}/vapid-recovery.sh"

# _profile_vapid_secret_name_for_env_key
# Resolves one VAPID Docker-secret name from the active profile.
#
# Arguments:
#   $1 - Secret-mount environment key.
#
# Outputs:
#   The unique matching exact Docker-secret name, or no text when unsupported.
#
# Returns:
#   jq status.
_profile_vapid_secret_name_for_env_key() {
    local env_key="$1"
    local profile_file=""

    profile_file="$(_active_profile_json)" || return 1
    jq -r --arg env_key "$env_key" '
      [
        .secretMounts[]?,
        (.capabilities // {} | to_entries[] |
          select(.value.enabled == true) |
          .value.secretMounts[]?)
      ]
      | map(select(
          .envKey == $env_key and
          (.name | type == "string") and
          (.name | length > 0)
        ))
      | map(.name)
      | unique
      | if length == 1 then .[0] else empty end
    ' "$profile_file"
}

# profile_supports_vapid_secret_setup
# Checks whether the active exact-name profile declares one complete VAPID pair.
#
# Arguments:
#   None.
#
# Returns:
#   0 when public and private VAPID secret mounts are uniquely declared;
#   otherwise 1.
profile_supports_vapid_secret_setup() {
    local public_name=""
    local private_name=""

    command -v jq >/dev/null 2>&1 || return 1
    _profile_secrets_use_exact_names || return 1
    public_name="$(_profile_vapid_secret_name_for_env_key \
        WEB_PUSH_VAPID_PUBLIC_KEY_FILE)" || return 1
    private_name="$(_profile_vapid_secret_name_for_env_key \
        WEB_PUSH_VAPID_PRIVATE_KEY_FILE)" || return 1

    [ -n "$public_name" ] &&
        [ -n "$private_name" ] &&
        [ "$public_name" != "$private_name" ]
}

# _profile_secret_is_vapid
# Checks whether one profile secret is either half of the managed VAPID pair.
#
# Arguments:
#   $1 - Exact Docker-secret name.
#
# Returns:
#   0 for either VAPID secret; otherwise 1.
_profile_secret_is_vapid() {
    local secret_name="$1"
    local public_name=""
    local private_name=""

    profile_supports_vapid_secret_setup || return 1
    public_name="$(_profile_vapid_secret_name_for_env_key \
        WEB_PUSH_VAPID_PUBLIC_KEY_FILE)" || return 1
    private_name="$(_profile_vapid_secret_name_for_env_key \
        WEB_PUSH_VAPID_PRIVATE_KEY_FILE)" || return 1

    [ "$secret_name" = "$public_name" ] ||
        [ "$secret_name" = "$private_name" ]
}

# _generate_vapid_key_pair
# Creates a standard base64url P-256 VAPID key pair without npm dependencies.
#
# Arguments:
#   None.
#
# Outputs:
#   PUBLIC_KEY=... and PRIVATE_KEY=... lines for internal caller capture.
#
# Returns:
#   0 after successful generation; otherwise 1.
_generate_vapid_key_pair() (
    local tmp_dir=""
    local private_pem=""
    local key_text=""
    local pair_output=""
    local status=0

    # The subshell confines this cleanup trap to one generation attempt.
    _cleanup_vapid_generation_workspace() {
        if [ -n "$private_pem" ]; then
            rm -f -- "$private_pem" "$key_text"
        fi
        if [ -n "$tmp_dir" ]; then
            rmdir -- "$tmp_dir" 2>/dev/null || true
        fi
    }
    trap _cleanup_vapid_generation_workspace EXIT

    if ! command -v openssl >/dev/null 2>&1; then
        echo "[ERROR] openssl is required to generate VAPID keys." >&2
        return 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "[ERROR] python3 is required to encode VAPID keys." >&2
        return 1
    fi

    umask 077
    tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t vapid-secrets)" || {
        echo "[ERROR] Could not create protected VAPID workspace." >&2
        return 1
    }
    private_pem="${tmp_dir}/private.pem"
    key_text="${tmp_dir}/key.txt"

    if ! openssl ecparam -name prime256v1 -genkey -noout \
        -out "$private_pem" >/dev/null 2>&1; then
        echo "[ERROR] Could not generate the VAPID P-256 key." >&2
        return 1
    fi
    if ! openssl ec -in "$private_pem" -noout -text \
        > "$key_text" 2>/dev/null; then
        echo "[ERROR] Could not inspect generated VAPID key material." >&2
        return 1
    fi

    pair_output="$(python3 - "$key_text" <<'PY'
import base64
import re
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
section = None
private_hex_parts = []
public_hex_parts = []

for line in lines:
    value = line.strip()
    if value.startswith("priv:"):
        section = "private"
        value = value[5:]
    elif value.startswith("pub:"):
        section = "public"
        value = value[4:]
    elif value.startswith("ASN1 OID") or value.startswith("NIST CURVE"):
        section = None
        value = ""

    hex_value = re.sub(r"[^0-9a-fA-F]", "", value)
    if not hex_value:
        continue
    if section == "private":
        private_hex_parts.append(hex_value)
    elif section == "public":
        public_hex_parts.append(hex_value)

private_key = bytes.fromhex("".join(private_hex_parts))
public_key = bytes.fromhex("".join(public_hex_parts))
if len(private_key) > 32:
    private_key = private_key[-32:]
private_key = private_key.rjust(32, b"\0")
if len(public_key) != 65 or public_key[0] != 4:
    raise SystemExit("Generated public key is not an uncompressed P-256 point")


def b64url(raw: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


print(f"PUBLIC_KEY={b64url(public_key)}")
print(f"PRIVATE_KEY={b64url(private_key)}")
PY
)" || status=$?

    if [ "$status" -ne 0 ]; then
        echo "[ERROR] Could not encode the generated VAPID key pair." >&2
        return "$status"
    fi
    printf '%s\n' "$pair_output"
)

# _create_vapid_docker_secret_pair
# Replaces the declared pair from protected temporary files.
#
# Arguments:
#   $1 - Public Docker-secret name.
#   $2 - Private Docker-secret name.
#   $3 - Public VAPID value.
#   $4 - Private VAPID value.
#
# Returns:
#   0 when both secrets exist; otherwise 1.
#
# Side effects:
#   Removes existing pair members and creates two Docker secrets.
_create_vapid_docker_secret_pair() (
    local public_name="$1"
    local private_name="$2"
    local public_key="$3"
    local private_key="$4"
    local tmp_dir=""
    local public_file=""
    local private_file=""
    local secret_name=""

    # The subshell keeps cleanup and key-bearing locals scoped to this write.
    _cleanup_vapid_secret_workspace() {
        if [ -n "$public_file" ]; then
            rm -f -- "$public_file" "$private_file"
        fi
        if [ -n "$tmp_dir" ]; then
            rmdir -- "$tmp_dir" 2>/dev/null || true
        fi
    }
    trap _cleanup_vapid_secret_workspace EXIT

    umask 077
    tmp_dir="$(mktemp -d 2>/dev/null || mktemp -d -t vapid-secrets)" || {
        echo "[ERROR] Could not create protected VAPID workspace."
        return 1
    }
    public_file="${tmp_dir}/public"
    private_file="${tmp_dir}/private"
    printf '%s' "$public_key" > "$public_file"
    printf '%s' "$private_key" > "$private_file"

    for secret_name in "$public_name" "$private_name"; do
        if docker secret inspect "$secret_name" >/dev/null 2>&1 &&
            ! docker secret rm "$secret_name" >/dev/null; then
            echo "[ERROR] Existing Docker secret could not be removed: ${secret_name}"
            return 1
        fi
    done

    if ! docker secret create "$public_name" "$public_file" >/dev/null; then
        echo "[ERROR] VAPID public-key Docker secret creation failed."
        return 1
    fi
    if ! docker secret create "$private_name" "$private_file" >/dev/null; then
        docker secret rm "$public_name" >/dev/null 2>&1 || true
        echo "[ERROR] VAPID private-key Docker secret creation failed."
        echo "        The incomplete replacement was removed; rerun VAPID setup."
        return 1
    fi

    return 0
)

# run_profile_vapid_secret_setup
# Generates and stores the active profile's complete Web Push VAPID key pair.
#
# Arguments:
#   None.
#
# Returns:
#   0 after successful creation or an operator decision to keep an existing
#   pair; otherwise 1.
#
# Side effects:
#   May remove a confirmed running stack before replacing Docker secrets.
run_profile_vapid_secret_setup() {
    local public_name=""
    local private_name=""
    local public_exists="false"
    local private_exists="false"
    local replace=""
    local pair_output=""
    local pair_label=""
    local pair_value=""
    local public_key=""
    local private_key=""

    if ! profile_supports_vapid_secret_setup; then
        echo "[INFO] Web Push VAPID setup is not declared by this profile."
        return 1
    fi
    public_name="$(_profile_vapid_secret_name_for_env_key \
        WEB_PUSH_VAPID_PUBLIC_KEY_FILE)" || return 1
    private_name="$(_profile_vapid_secret_name_for_env_key \
        WEB_PUSH_VAPID_PRIVATE_KEY_FILE)" || return 1

    docker secret inspect "$public_name" >/dev/null 2>&1 &&
        public_exists="true"
    docker secret inspect "$private_name" >/dev/null 2>&1 &&
        private_exists="true"

    echo ""
    echo "Web Push VAPID key-pair setup"
    echo "-----------------------------"
    echo "This creates one matching P-256 pair in these Docker secrets:"
    echo "  - ${public_name}"
    echo "  - ${private_name}"
    printf '%s\n' "$(operator_menu_message vapid.setup_storage_notice)"
    if [ "$public_exists" = "true" ] || [ "$private_exists" = "true" ]; then
        echo ""
        echo "[WARN] At least one VAPID pair member already exists."
        echo "       Replacing either key requires replacing both keys."
        if [ "$public_exists" = "true" ] && [ "$private_exists" = "true" ]; then
            echo "       Rotation may require browsers to subscribe again."
        fi
        read -r -p "Replace the complete VAPID pair? (y/N): " replace
        if [[ ! "$replace" =~ ^[Yy]$ ]]; then
            if [ "$public_exists" = "true" ] &&
                [ "$private_exists" = "true" ]; then
                echo "[INFO] Keeping the existing VAPID secret pair."
                return 0
            fi
            echo "[ERROR] The incomplete VAPID secret pair remains unresolved."
            return 1
        fi
    fi

    echo "[INFO] Generating a new VAPID key pair locally..."
    pair_output="$(_generate_vapid_key_pair)" || return 1
    while IFS='=' read -r pair_label pair_value; do
        case "$pair_label" in
            PUBLIC_KEY) public_key="$pair_value" ;;
            PRIVATE_KEY) private_key="$pair_value" ;;
        esac
    done <<< "$pair_output"
    pair_output=""
    pair_value=""
    if [[ ! "$public_key" =~ ^[A-Za-z0-9_-]{87}$ ]] ||
        [[ ! "$private_key" =~ ^[A-Za-z0-9_-]{43}$ ]]; then
        public_key=""
        private_key=""
        echo "[ERROR] Generated VAPID key lengths or encoding were invalid."
        return 1
    fi

    if [ "$public_exists" = "true" ] || [ "$private_exists" = "true" ]; then
        _require_stopped_stack_for_secret_change || {
            public_key=""
            private_key=""
            return 1
        }
    fi
    if ! _create_vapid_docker_secret_pair \
        "$public_name" "$private_name" "$public_key" "$private_key"; then
        public_key=""
        private_key=""
        return 1
    fi
    echo "[OK] Matching Web Push VAPID Docker secrets are ready."
    if ! _offer_vapid_recovery_view \
        "$public_name" \
        "$private_name" \
        "$public_key" \
        "$private_key"; then
        printf '%s\n' \
            "$(operator_menu_message vapid.recovery_not_viewed)" >&2
    fi
    public_key=""
    private_key=""

    echo "[INFO] Deploy the stack to apply the new pair. Existing browser"
    echo "       subscriptions may need to subscribe again after key rotation."
    return 0
}
