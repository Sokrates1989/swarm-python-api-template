#!/bin/bash
# ==============================================================================
# menu-image-actions.sh - Profile-driven service image updates
# ==============================================================================
#
# Implements the operations-menu image workflow without reopening the first-run
# setup wizard. The active root environment selects the site profile; profile
# capabilities expose the primary and optional WebApp release images. One
# confirmed action atomically updates public image fields, rerenders the stack,
# deploys it, runs shared health acceptance, and reports the verified result.
#
# Dependencies:
#   - site_helpers.sh and deployment-profile-prompts.sh.
#   - semantic-version.sh and deployment-environment-format.sh.
#   - deployment-setup-actions.sh at execution time.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_IMAGE_ACTIONS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_IMAGE_ACTIONS_LOADED=1

_MENU_IMAGE_ACTIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_MENU_IMAGE_ACTIONS_DIR}/semantic-version.sh"
source "${_MENU_IMAGE_ACTIONS_DIR}/deployment-environment-format.sh"
source "${_MENU_IMAGE_ACTIONS_DIR}/menu-image-transaction.sh"

# ------------------------------------------------------------------------------
# _primary_release_image_label
# ------------------------------------------------------------------------------
# Derives a capability-oriented label for the profile's primary image.
#
# Output:
#   Backend API, Nginx, or Primary service.
# ------------------------------------------------------------------------------
_primary_release_image_label() {
    if [ "${APP_STACK_FAMILY:-${STACK_FAMILY:-api}}" = "nginx" ]; then
        printf '%s' 'Nginx'
    elif [ "${APP_PRIMARY_SERVICE:-${PRIMARY_SERVICE:-api}}" = "api" ]; then
        printf '%s' 'Backend API'
    else
        printf '%s' 'Primary service'
    fi
}

# ------------------------------------------------------------------------------
# _managed_release_image_records
# ------------------------------------------------------------------------------
# Lists every operator-versioned application image supported by the loaded
# profile schema. Infrastructure images remain digest-pinned in site config and
# are displayed in the overview but are not silently rewritten here.
#
# Output:
#   id|label|service|repository-key|version-key|repository|version records.
# ------------------------------------------------------------------------------
_managed_release_image_records() {
    local primary_service="${APP_PRIMARY_SERVICE:-${PRIMARY_SERVICE:-api}}"
    local primary_label=""

    primary_label="$(_primary_release_image_label)"
    if [ -n "${IMAGE_NAME:-}" ]; then
        printf '%s|%s|%s|%s|%s|%s|%s\n' \
            'primary' \
            "$primary_label" \
            "$primary_service" \
            'IMAGE_NAME' \
            'IMAGE_VERSION' \
            "$IMAGE_NAME" \
            "${IMAGE_VERSION:-latest}"
    fi
    if [ "${APP_REQUIRES_WEB:-${WEB_ENABLED:-false}}" = "true" ] &&
        [ "${WEB_ENABLED:-true}" = "true" ] &&
        [ -n "${WEB_IMAGE_NAME:-}" ]; then
        printf '%s|%s|%s|%s|%s|%s|%s\n' \
            'web' \
            'WebApp' \
            'web' \
            'WEB_IMAGE_NAME' \
            'WEB_IMAGE_VERSION' \
            "$WEB_IMAGE_NAME" \
            "${WEB_IMAGE_VERSION:-latest}"
    fi
}

# ------------------------------------------------------------------------------
# _managed_release_version_floor
# ------------------------------------------------------------------------------
# Resolves the greatest current release-image version and any optional
# profile-declared coordinated floor. Unchanged lower-version components may
# remain deployed, but their next selected version starts from this maximum.
#
# Arguments:
#   All arguments are managed image records.
#
# Output:
#   Greatest valid stable semantic version.
#
# Returns:
#   0 when a semantic baseline exists; otherwise 1.
# ------------------------------------------------------------------------------
_managed_release_version_floor() {
    local records=("$@")
    local versions=()
    local record=""
    local version=""

    if [ -n "${APP_RELEASE_VERSION_FLOOR:-}" ]; then
        versions+=("$APP_RELEASE_VERSION_FLOOR")
    fi
    for record in "${records[@]}"; do
        version="${record##*|}"
        versions+=("$version")
    done
    highest_semantic_version "${versions[@]}"
}

# ------------------------------------------------------------------------------
# _select_release_image_scope
# ------------------------------------------------------------------------------
# Asks which profile-managed image to update, including a same-version all
# option when more than one application image exists.
#
# Arguments:
#   All arguments are managed image records.
#
# Returns:
#   0 after populating IMAGE_UPDATE_SELECTED_RECORDS; 1 on cancellation.
# ------------------------------------------------------------------------------
_select_release_image_scope() {
    local records=("$@")
    local choices=()
    local record=""
    local label=""
    local repository=""
    local version=""
    local selection=""
    local index=0

    for index in "${!records[@]}"; do
        record="${records[$index]}"
        IFS='|' read -r _ label _ _ _ repository version <<< "$record"
        choices+=("record-${index}|${label} only (${repository}:${version})")
    done
    if [ "${#records[@]}" -gt 1 ]; then
        choices+=("all|All listed application services (one shared version)")
    fi
    choices+=("cancel|Back without changes")
    prompt_deployment_choice \
        selection \
        'Which application service image should be updated?' \
        'record-0' \
        "${choices[@]}"
    IMAGE_UPDATE_SELECTED_RECORDS=()
    case "$selection" in
        cancel) return 1 ;;
        all) IMAGE_UPDATE_SELECTED_RECORDS=("${records[@]}") ;;
        record-*)
            index="${selection#record-}"
            IMAGE_UPDATE_SELECTED_RECORDS+=("${records[$index]}")
            ;;
        *) return 1 ;;
    esac
}

# ------------------------------------------------------------------------------
# _select_release_image_version
# ------------------------------------------------------------------------------
# Selects one version shared by the chosen services. Semantic profiles use the
# stack-wide floor helper; legacy non-SemVer tags retain an exact-tag prompt.
#
# Arguments:
#   $1 - Semantic stack floor or empty text.
#   $2 - Existing selected-service version fallback.
#
# Returns:
#   0 after setting IMAGE_UPDATE_SELECTED_VERSION; otherwise 1.
# ------------------------------------------------------------------------------
_select_release_image_version() {
    local floor="$1"
    local fallback="$2"
    local default_action='patch'
    local comparison=''

    if semantic_version_is_valid "$floor"; then
        if semantic_version_is_valid "$fallback"; then
            comparison="$(compare_semantic_versions "$fallback" "$floor")" ||
                return 1
            if [ "$comparison" = '-1' ]; then
                default_action='floor'
            fi
        fi
        select_semantic_version \
            "$floor" \
            'Application image version' \
            "$default_action" ||
            return 1
        IMAGE_UPDATE_SELECTED_VERSION="$SELECTED_SEMANTIC_VERSION"
        return 0
    fi
    echo ""
    echo "The current image tag has no stable semantic-version baseline."
    echo "Enter an exact tag; future MAJOR.MINOR.PATCH values enable bump choices."
    prompt_deployment_value \
        IMAGE_UPDATE_SELECTED_VERSION \
        'Application image version' \
        "$fallback" \
        'tag'
}

# ------------------------------------------------------------------------------
# _prepare_release_image_updates
# ------------------------------------------------------------------------------
# Collects repositories and one coordinated version for the selected records.
#
# Arguments:
#   $1 - Semantic stack floor or empty text.
#
# Returns:
#   0 after populating IMAGE_UPDATE_ENV_ASSIGNMENTS; otherwise 1.
# ------------------------------------------------------------------------------
_prepare_release_image_updates() {
    local floor="$1"
    local record=""
    local label=""
    local repository_key=""
    local version_key=""
    local repository=""
    local current_version=""
    local selected_repository=""
    local first_version=""
    local repositories=()
    local index=0

    for record in "${IMAGE_UPDATE_SELECTED_RECORDS[@]}"; do
        IFS='|' read -r _ label _ repository_key version_key repository current_version <<< "$record"
        [ -n "$first_version" ] || first_version="$current_version"
        prompt_deployment_value \
            selected_repository \
            "${label} image repository" \
            "$repository" \
            'image'
        repositories+=("$selected_repository")
    done
    _select_release_image_version "$floor" "$first_version" || return 1
    IMAGE_UPDATE_ENV_ASSIGNMENTS=()
    for index in "${!IMAGE_UPDATE_SELECTED_RECORDS[@]}"; do
        record="${IMAGE_UPDATE_SELECTED_RECORDS[$index]}"
        IFS='|' read -r _ _ _ repository_key version_key _ _ <<< "$record"
        IMAGE_UPDATE_ENV_ASSIGNMENTS+=(
            "${repository_key}=${repositories[$index]}"
            "${version_key}=${IMAGE_UPDATE_SELECTED_VERSION}"
        )
    done
}

# ------------------------------------------------------------------------------
# _show_release_image_update_plan
# ------------------------------------------------------------------------------
# Prints old and selected image references before the single external-effect
# confirmation.
# ------------------------------------------------------------------------------
_show_release_image_update_plan() {
    local record=""
    local label=""
    local repository=""
    local version=""
    local index=0
    local selected_repository=""

    echo ""
    echo "Service image update plan"
    echo "-------------------------"
    echo "Profile: ${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-unknown}}"
    echo "Stack:   ${STACK_NAME}"
    for index in "${!IMAGE_UPDATE_SELECTED_RECORDS[@]}"; do
        record="${IMAGE_UPDATE_SELECTED_RECORDS[$index]}"
        IFS='|' read -r _ label _ _ _ repository version <<< "$record"
        selected_repository="${IMAGE_UPDATE_ENV_ASSIGNMENTS[$((index * 2))]#*=}"
        echo "  - ${label}: ${repository}:${version}"
        echo "               -> ${selected_repository}:${IMAGE_UPDATE_SELECTED_VERSION}"
    done
    echo ""
    echo "The shared renderer, Swarm deployment, and health acceptance run next."
}

# ------------------------------------------------------------------------------
# manage_service_images
# ------------------------------------------------------------------------------
# Runs the complete active-profile image selection, version, confirmation,
# render, deployment, and health workflow used by operations-menu option 10.
#
# Returns:
#   0 after success or a no-op; 1 on cancellation or failure.
# ------------------------------------------------------------------------------
manage_service_images() {
    local records=()
    local version_floor=""
    local transaction_directory=""
    local apply_status=0

    load_root_env "${PROJECT_ROOT:-.}" || return 1
    mapfile -t records < <(_managed_release_image_records)
    if [ "${#records[@]}" -eq 0 ]; then
        echo "[ERROR] The selected profile exposes no operator-managed image."
        return 1
    fi
    echo ""
    echo "Change service image configuration"
    echo "=================================="
    echo "Active profile: ${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-unknown}}"
    echo "Infrastructure images remain profile-pinned; every application image"
    echo "listed below comes from the same shared site-config capability model."
    _select_release_image_scope "${records[@]}" || return 1
    if [ -n "${APP_RELEASE_VERSION_POLICY:-}" ] &&
        [ "$APP_RELEASE_VERSION_POLICY" != "monotonic-floor" ]; then
        echo "[ERROR] Unsupported profile release.versionPolicy:"
        echo "        ${APP_RELEASE_VERSION_POLICY}"
        return 1
    fi
    if [ -n "${APP_RELEASE_VERSION_FLOOR:-}" ] &&
        ! semantic_version_is_valid "$APP_RELEASE_VERSION_FLOOR"; then
        echo "[ERROR] Profile release.versionFloor is not stable SemVer:"
        echo "        ${APP_RELEASE_VERSION_FLOOR}"
        return 1
    fi
    version_floor="$(_managed_release_version_floor "${records[@]}")" ||
        version_floor=""
    _prepare_release_image_updates "$version_floor" || return 1
    _show_release_image_update_plan
    if ! prompt_yes_no \
        'Apply these image values, deploy, and run health checks?' \
        'Y'; then
        echo "Image update cancelled; no files or Swarm services were changed."
        return 1
    fi
    transaction_directory="$(mktemp -d \
        "${PROJECT_ROOT}/.image-update.XXXXXX")" || return 1
    _apply_release_image_update "$transaction_directory" || apply_status=$?
    _clean_release_image_transaction "$transaction_directory"
    if [ "$apply_status" -eq 2 ]; then
        return 0
    fi
    return "$apply_status"
}
