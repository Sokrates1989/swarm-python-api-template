#!/usr/bin/env bash
# Groups and incrementally reveals published semantic-version rollbacks.

if [ -n "${_SEMANTIC_VERSION_ROLLBACK_MENU_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_SEMANTIC_VERSION_ROLLBACK_MENU_LOADED=1

# Return unique stable versions in descending numeric order.
sort_semantic_versions_desc() {
    local ordered=()
    local candidate=""
    local index=0
    local inserted=false

    for candidate in "$@"; do
        semantic_version_is_valid "$candidate" || continue
        semantic_version_is_listed "$candidate" "${ordered[@]}" && continue
        inserted=false
        for index in "${!ordered[@]}"; do
            if [ "$(compare_semantic_versions "$candidate" "${ordered[$index]}")" = '1' ]; then
                ordered=(
                    "${ordered[@]:0:$index}"
                    "$candidate"
                    "${ordered[@]:$index}"
                )
                inserted=true
                break
            fi
        done
        [ "$inserted" = true ] || ordered+=("$candidate")
    done
    [ "${#ordered[@]}" -gt 0 ] && printf '%s\n' "${ordered[@]}"
}

# Return the MAJOR.MINOR release series for one stable version.
semantic_version_series() {
    local major=""
    local minor=""
    local patch=""

    semantic_version_is_valid "$1" || return 1
    IFS='.' read -r major minor patch <<< "$1"
    printf '%s.%s' "$major" "$minor"
}

# Select one rollback version from an expandable release-series list.
_select_rollback_version() {
    local target_name="$1"
    local label="$2"
    local series="$3"
    shift 3
    local versions=("$@")
    local visible=9
    local limit=0
    local choice=""
    local index=0

    while true; do
        limit="$visible"
        [ "$limit" -le "${#versions[@]}" ] || limit="${#versions[@]}"
        echo ""
        _semantic_version_say semver.rollback_versions_header "$label" "$series"
        for ((index=0; index < limit; index++)); do
            _semantic_version_say semver.rollback_version \
                "$((index + 1))" "${versions[$index]}"
        done
        [ "$limit" -ge "${#versions[@]}" ] ||
            _semantic_version_say semver.show_more
        _semantic_version_say semver.back
        _semantic_version_prompt semver.choice choice
        choice="${choice,,}"
        case "$choice" in
            m|more)
                if [ "$limit" -lt "${#versions[@]}" ]; then
                    visible=$((visible + 10))
                    continue
                fi
                ;;
            0|q|quit|back) return 1 ;;
            *)
                if [[ "$choice" =~ ^[0-9]+$ ]] &&
                    [ "$choice" -ge 1 ] && [ "$choice" -le "$limit" ]; then
                    printf -v "$target_name" '%s' "${versions[$((choice - 1))]}"
                    return 0
                fi
                ;;
        esac
        _semantic_version_say semver.invalid_rollback
    done
}

# Select a rollback series, then a published version within that series.
select_published_rollback_semver() {
    local target_name="$1"
    local label="$2"
    shift 2
    local versions=("$@")
    local series_list=()
    local series_versions=()
    local version=""
    local series=""
    local selected_series=""
    local choice=""
    local visible=9
    local limit=0
    local index=0

    for version in "${versions[@]}"; do
        series="$(semantic_version_series "$version")" || continue
        semantic_version_is_listed "$series" "${series_list[@]}" ||
            series_list+=("$series")
    done
    [ "${#series_list[@]}" -gt 0 ] || return 1
    while true; do
        limit="$visible"
        [ "$limit" -le "${#series_list[@]}" ] || limit="${#series_list[@]}"
        echo ""
        _semantic_version_say semver.rollback_series_header "$label"
        for ((index=0; index < limit; index++)); do
            _semantic_version_say semver.rollback_series \
                "$((index + 1))" "${series_list[$index]}"
        done
        [ "$limit" -ge "${#series_list[@]}" ] ||
            _semantic_version_say semver.show_more
        _semantic_version_say semver.back
        _semantic_version_prompt semver.choice choice
        choice="${choice,,}"
        case "$choice" in
            m|more)
                if [ "$limit" -lt "${#series_list[@]}" ]; then
                    visible=$((visible + 10))
                    continue
                fi
                ;;
            0|q|quit|back) return 1 ;;
            *)
                if [[ "$choice" =~ ^[0-9]+$ ]] &&
                    [ "$choice" -ge 1 ] && [ "$choice" -le "$limit" ]; then
                    selected_series="${series_list[$((choice - 1))]}"
                    series_versions=()
                    for version in "${versions[@]}"; do
                        [ "$(semantic_version_series "$version")" = "$selected_series" ] &&
                            series_versions+=("$version")
                    done
                    if _select_rollback_version \
                        "$target_name" "$label" "$selected_series" \
                        "${series_versions[@]}"; then
                        return 0
                    fi
                    continue
                fi
                ;;
        esac
        _semantic_version_say semver.invalid_rollback
    done
}
