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
source "${_MENU_IMAGE_ACTIONS_DIR}/menu-image-test-channel.sh"

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
# _select_image_update_channel
# ------------------------------------------------------------------------------
# Require an explicit stable/test choice before service scope or registry tag
# selection. This prevents a production checkout from following test aliases by
# accident while allowing a separate test checkout to opt in deliberately.
#
# Returns:
#   0 after setting IMAGE_UPDATE_CHANNEL; otherwise 1 on Back.
# ------------------------------------------------------------------------------
_select_image_update_channel() {
    local selection=""

    prompt_deployment_choice \
        selection \
        'Application image channel' \
        'stable' \
        'stable|Stable release images (unsuffixed MAJOR.MINOR.PATCH tags)' \
        'test|Newest test images (exact MAJOR.MINOR.PATCH-test tags)' \
        'cancel|Back without changes'
    case "$selection" in
        stable|test) IMAGE_UPDATE_CHANNEL="$selection" ;;
        *) return 1 ;;
    esac
}

# ------------------------------------------------------------------------------
# _select_release_image_scope
# ------------------------------------------------------------------------------
# Asks which profile-managed image to update, including an all-services option
# when more than one application image exists.
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
        choices+=("all|All listed application services")
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
# _load_published_stable_tags
# ------------------------------------------------------------------------------
# Loads real stable registry tags into a caller-owned array.
#
# Arguments:
#   $1 - Docker repository without tag.
#   $2 - Target array variable name.
#
# Returns:
#   0 when at least one tag is available; otherwise 1.
# ------------------------------------------------------------------------------
_load_published_stable_tags() {
    local repository="$1"
    local target_name="$2"
    local output=""
    local -n target="$target_name"

    output="$(registry_stable_tags "$repository")" || {
        echo "[ERROR] Could not enumerate published tags for ${repository}." >&2
        echo "        Exact-tag verification may still work with Docker credentials." >&2
        return 1
    }
    target=()
    if [ -n "$output" ]; then
        mapfile -t target <<< "$output"
    fi
    if [ "${#target[@]}" -eq 0 ]; then
        echo "[ERROR] ${repository} has no published stable MAJOR.MINOR.PATCH tags." >&2
        return 1
    fi
}

# ------------------------------------------------------------------------------
# _release_tag_is_not_older
# ------------------------------------------------------------------------------
# Prevents the update helper from acting as an implicit rollback mechanism.
#
# Arguments:
#   $1 - Candidate stable version.
#   $2 - Current version.
#
# Returns:
#   0 when candidate is equal/newer or current is non-SemVer; otherwise 1.
# ------------------------------------------------------------------------------
_release_tag_is_not_older() {
    local candidate="$1"
    local current="$2"
    local comparison=""

    if ! semantic_version_is_valid "$candidate"; then
        return 1
    fi
    if ! semantic_version_is_valid "$current"; then
        return 0
    fi
    comparison="$(compare_semantic_versions "$candidate" "$current")" ||
        return 1
    [ "$comparison" != '-1' ]
}

# ------------------------------------------------------------------------------
# _verify_release_tag
# ------------------------------------------------------------------------------
# Verifies existence, immutable digest, and linux/amd64 support for one chosen
# application image before any configuration mutation.
#
# Arguments:
#   $1 - Operator-facing label.
#   $2 - Repository.
#   $3 - Exact tag.
#
# Returns:
#   0 with evidence appended to IMAGE_UPDATE_VERIFICATION_EVIDENCE; otherwise 1.
# ------------------------------------------------------------------------------
_verify_release_tag() {
    local label="$1"
    local repository="$2"
    local tag="$3"
    local evidence=""

    evidence="$(registry_verify_tag "$repository" "$tag")" || {
        echo "[ERROR] ${label} image is not deployable as selected:"
        echo "        ${repository}:${tag}"
        echo "        The tag must exist and declare linux/amd64 support."
        return 1
    }
    IMAGE_UPDATE_VERIFICATION_EVIDENCE+=("${label}|${evidence}")
    echo "[OK] Verified ${label}: ${repository}:${tag}"
}

# ------------------------------------------------------------------------------
# _select_one_published_tag
# ------------------------------------------------------------------------------
# Uses registry-returned versions plus an exact immediately verified fallback.
#
# Arguments:
#   $1 - Label.
#   $2 - Repository.
#   $3 - Current version.
#   $4 - Target variable name.
#
# Returns:
#   0 after selection; otherwise 1 on cancellation or unavailable evidence.
# ------------------------------------------------------------------------------
_select_one_published_tag() {
    local label="$1"
    local repository="$2"
    local current="$3"
    local target_name="$4"
    local tags=()
    local available=()
    local tag=""

    _load_published_stable_tags "$repository" tags || tags=()
    for tag in "${tags[@]}"; do
        _release_tag_is_not_older "$tag" "$current" || continue
        available+=("$tag")
        [ "${#available[@]}" -ge 20 ] && break
    done
    select_published_semver \
        "$target_name" "$label" "$repository" "$current" "${available[@]}"
}

# ------------------------------------------------------------------------------
# _highest_common_published_tag
# ------------------------------------------------------------------------------
# Finds the greatest stable tag present in every selected repository without
# downgrading any selected service.
#
# Output:
#   Highest common tag, or no output when none is safe.
# ------------------------------------------------------------------------------
_highest_common_published_tag() {
    local repository=""
    local current=""
    local tags=()
    local common_tags=()
    local tag=""
    local index=0
    local repository_count="${#IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"
    declare -A occurrences=()

    for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
        repository="${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}"
        current="${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}"
        _load_published_stable_tags "$repository" tags || return 1
        for tag in "${tags[@]}"; do
            _release_tag_is_not_older "$tag" "$current" || continue
            occurrences[$tag]=$(( ${occurrences[$tag]:-0} + 1 ))
        done
    done
    for tag in "${!occurrences[@]}"; do
        [ "${occurrences[$tag]}" -eq "$repository_count" ] || continue
        common_tags+=("$tag")
    done
    highest_semantic_version "${common_tags[@]}"
}

# ------------------------------------------------------------------------------
# _select_release_image_versions
# ------------------------------------------------------------------------------
# Chooses registry-proven versions for one or multiple selected services.
# Multiple-service mode can independently use each repository's highest tag or
# use their highest common tag; neither path invents a future version.
#
# Returns:
#   0 after populating IMAGE_UPDATE_SELECTED_VERSIONS; otherwise 1.
# ------------------------------------------------------------------------------
_select_release_image_versions() {
    local count="${#IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"
    local choices=()
    local selection=""
    local tags=()
    local highest=""
    local common=""
    local exact=""
    local index=0
    local label=""
    local all_enumerated=true
    local default_strategy='k'

    IMAGE_UPDATE_SELECTED_VERSIONS=()
    if [ "$count" -eq 1 ]; then
        _select_one_published_tag \
            "${IMAGE_UPDATE_SELECTED_LABELS[0]}" \
            "${IMAGE_UPDATE_SELECTED_REPOSITORIES[0]}" \
            "${IMAGE_UPDATE_SELECTED_CURRENTS[0]}" \
            highest || return 1
        IMAGE_UPDATE_SELECTED_VERSIONS+=("$highest")
        return 0
    fi
    for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
        if ! _load_published_stable_tags \
            "${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}" tags; then
            all_enumerated=false
        fi
    done
    if [ "$all_enumerated" = true ]; then
        common="$(_highest_common_published_tag)" || common=""
        choices+=("h|Update each service to its own highest published stable version")
        if [ -n "$common" ]; then
            choices+=("c|Use highest common published stable version (${common})")
        fi
    fi
    choices=("k|Keep every service at its current version" "${choices[@]}")
    choices+=("i|Select a published version for each service")
    choices+=("e|Enter one exact version and verify it in every repository")
    choices+=("q|Cancel")
    prompt_deployment_choice \
        selection \
        'Registry-backed version strategy' \
        "$default_strategy" \
        "${choices[@]}"
    case "$selection" in
        k)
            for index in "${!IMAGE_UPDATE_SELECTED_CURRENTS[@]}"; do
                IMAGE_UPDATE_SELECTED_VERSIONS+=(
                    "${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}"
                )
            done
            ;;
        h)
            for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
                _load_published_stable_tags \
                    "${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}" tags || return 1
                highest="${tags[0]}"
                if _release_tag_is_not_older \
                    "$highest" "${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}"; then
                    IMAGE_UPDATE_SELECTED_VERSIONS+=("$highest")
                else
                    IMAGE_UPDATE_SELECTED_VERSIONS+=(
                        "${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}"
                    )
                fi
            done
            ;;
        c)
            for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
                IMAGE_UPDATE_SELECTED_VERSIONS+=("$common")
            done
            ;;
        i)
            for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
                label="${IMAGE_UPDATE_SELECTED_LABELS[$index]}"
                _select_one_published_tag \
                    "$label" \
                    "${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}" \
                    "${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}" \
                    highest || return 1
                IMAGE_UPDATE_SELECTED_VERSIONS+=("$highest")
            done
            ;;
        e)
            prompt_deployment_value exact 'Exact shared published version' '' semver
            for index in "${!IMAGE_UPDATE_SELECTED_REPOSITORIES[@]}"; do
                if ! _release_tag_is_not_older \
                    "$exact" "${IMAGE_UPDATE_SELECTED_CURRENTS[$index]}"; then
                    echo "[ERROR] ${exact} would downgrade ${IMAGE_UPDATE_SELECTED_LABELS[$index]}."
                    return 1
                fi
                IMAGE_UPDATE_SELECTED_VERSIONS+=("$exact")
            done
            ;;
        *) return 1 ;;
    esac
}

# ------------------------------------------------------------------------------
# _prepare_release_image_updates
# ------------------------------------------------------------------------------
# Collects repositories, selects only published versions, verifies every exact
# reference, and prepares the public environment transaction.
#
# Returns:
#   0 after populating IMAGE_UPDATE_ENV_ASSIGNMENTS; otherwise 1.
# ------------------------------------------------------------------------------
_prepare_release_image_updates() {
    local record=""
    local label=""
    local repository_key=""
    local version_key=""
    local repository=""
    local current_version=""
    local selected_repository=""
    local index=0

    IMAGE_UPDATE_SELECTED_REPOSITORIES=()
    IMAGE_UPDATE_SELECTED_CURRENTS=()
    IMAGE_UPDATE_SELECTED_LABELS=()
    for record in "${IMAGE_UPDATE_SELECTED_RECORDS[@]}"; do
        IFS='|' read -r _ label _ repository_key version_key repository current_version <<< "$record"
        prompt_deployment_value \
            selected_repository \
            "${label} image repository" \
            "$repository" \
            'image'
        IMAGE_UPDATE_SELECTED_REPOSITORIES+=("$selected_repository")
        IMAGE_UPDATE_SELECTED_CURRENTS+=("$current_version")
        IMAGE_UPDATE_SELECTED_LABELS+=("$label")
    done
    if [ "${IMAGE_UPDATE_CHANNEL:-stable}" = "test" ]; then
        _select_highest_test_image_versions || return 1
    else
        _select_release_image_versions || return 1
    fi
    IMAGE_UPDATE_ENV_ASSIGNMENTS=()
    IMAGE_UPDATE_VERIFICATION_EVIDENCE=()
    for index in "${!IMAGE_UPDATE_SELECTED_RECORDS[@]}"; do
        record="${IMAGE_UPDATE_SELECTED_RECORDS[$index]}"
        IFS='|' read -r _ label _ repository_key version_key _ _ <<< "$record"
        _verify_release_tag \
            "$label" \
            "${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}" \
            "${IMAGE_UPDATE_SELECTED_VERSIONS[$index]}" || return 1
        IMAGE_UPDATE_ENV_ASSIGNMENTS+=(
            "${repository_key}=${IMAGE_UPDATE_SELECTED_REPOSITORIES[$index]}"
            "${version_key}=${IMAGE_UPDATE_SELECTED_VERSIONS[$index]}"
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
    local selected_version=""

    echo ""
    echo "Service image update plan"
    echo "-------------------------"
    echo "Profile: ${DEPLOYMENT_PROFILE_ID:-${BACKEND_APP_ID:-unknown}}"
    echo "Stack:   ${STACK_NAME}"
    if [ "${IMAGE_UPDATE_CHANNEL:-stable}" = "test" ]; then
        echo "Channel: test (exact versioned tags; latest-test is never deployed)"
    else
        echo "Channel: stable (unsuffixed tags only)"
    fi
    for index in "${!IMAGE_UPDATE_SELECTED_RECORDS[@]}"; do
        record="${IMAGE_UPDATE_SELECTED_RECORDS[$index]}"
        IFS='|' read -r _ label _ _ _ repository version <<< "$record"
        selected_repository="${IMAGE_UPDATE_ENV_ASSIGNMENTS[$((index * 2))]#*=}"
        selected_version="${IMAGE_UPDATE_SELECTED_VERSIONS[$index]}"
        echo "  - ${label}: ${repository}:${version}"
        echo "               -> ${selected_repository}:${selected_version}"
    done
    echo ""
    echo "The shared renderer, Swarm deployment, and health acceptance run next."
}

# ------------------------------------------------------------------------------
# manage_service_images
# ------------------------------------------------------------------------------
# Runs the complete active-profile channel, image, confirmation, render,
# deployment, and health workflow used by the ``i`` shortcut.
#
# Returns:
#   0 after success or a no-op; 1 on cancellation or failure.
# ------------------------------------------------------------------------------
manage_service_images() {
    local records=()
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
    echo "Stable and test channels are separate. Test mode installs each selected"
    echo "service's newest exact MAJOR.MINOR.PATCH-test tag; latest-test is never"
    echo "deployment evidence. Every choice is verified for linux/amd64 before"
    echo "configuration changes. Infrastructure pins are"
    echo "reviewed separately through the image-audit menu (shortcut a)."
    _select_image_update_channel || return 1
    _select_release_image_scope "${records[@]}" || return 1
    if [ "${IMAGE_UPDATE_CHANNEL}" = "stable" ] &&
        [ -n "${APP_RELEASE_VERSION_FLOOR:-}" ]; then
        echo "Next new-artifact minimum: ${APP_RELEASE_VERSION_FLOOR}"
        echo "This build/publish policy is informational here; it is not deployment drift."
    fi
    _prepare_release_image_updates || return 1
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
