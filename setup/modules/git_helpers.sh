#!/bin/bash
#
# git_helpers.sh
#
# Git repository update check and pull helpers for the
# Python API Template swarm deployment main menu.
#
# Provides:
#   check_git_updates    - fetches origin and sets status variables
#   show_git_status_line - one-line status for the deployment overview
#   handle_git_pull      - performs git pull and auto-restarts quick-start.sh

# Load semantic status colors when this helper is sourced independently.
GIT_HELPERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! declare -F _menu_colorize >/dev/null 2>&1 &&
    [ -f "${GIT_HELPERS_DIR}/menu_formatting.sh" ]; then
    # shellcheck source=/dev/null
    source "${GIT_HELPERS_DIR}/menu_formatting.sh"
fi

# _GIT_UPDATE_STATUS: cached result of the git update check.
# Values: "" (not checked), "up-to-date", "behind", "ahead", "diverged", "error"
_GIT_UPDATE_STATUS=""
_GIT_UPDATE_BEHIND_COUNT=""

# check_git_updates
# Fetches from origin and compares local vs remote HEAD.
# Sets _GIT_UPDATE_STATUS and _GIT_UPDATE_BEHIND_COUNT.
check_git_updates() {
    _GIT_UPDATE_STATUS="error"
    _GIT_UPDATE_BEHIND_COUNT=""

    if ! command -v git &>/dev/null; then
        return 0
    fi

    if ! git rev-parse --is-inside-work-tree &>/dev/null 2>&1; then
        return 0
    fi

    git fetch origin --quiet 2>/dev/null || return 0

    local local_head remote_head merge_base branch
    branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")
    if [ -z "$branch" ]; then return 0; fi

    local_head=$(git rev-parse HEAD 2>/dev/null)
    remote_head=$(git rev-parse "origin/${branch}" 2>/dev/null || echo "")
    if [ -z "$remote_head" ]; then return 0; fi

    if [ "$local_head" = "$remote_head" ]; then
        _GIT_UPDATE_STATUS="up-to-date"
        return 0
    fi

    merge_base=$(git merge-base "$local_head" "$remote_head" 2>/dev/null || echo "")
    if [ "$merge_base" = "$local_head" ]; then
        local behind_count
        behind_count=$(git rev-list --count "${local_head}..${remote_head}" 2>/dev/null || echo "?")
        _GIT_UPDATE_STATUS="behind"
        _GIT_UPDATE_BEHIND_COUNT="$behind_count"
    elif [ "$merge_base" = "$remote_head" ]; then
        _GIT_UPDATE_STATUS="ahead"
    else
        _GIT_UPDATE_STATUS="diverged"
    fi
}

# show_git_status_line
# Prints a single-line repo status for the deployment overview.
show_git_status_line() {
    case "$_GIT_UPDATE_STATUS" in
        up-to-date)
            echo "Repo     : $(_menu_colorize ok '[OK] up to date')"
            ;;
        behind)
            echo "Repo     : $(_menu_colorize warning "[WARN] ${_GIT_UPDATE_BEHIND_COUNT} update(s) available")"
            ;;
        ahead)
            echo "Repo     : $(_menu_colorize warning '[WARN] local commits ahead of remote')"
            ;;
        diverged)
            echo "Repo     : $(_menu_colorize error '[ERROR] diverged from remote')"
            ;;
        error)
            echo "Repo     : $(_menu_colorize warning '[WARN] unable to check remote state')"
            ;;
    esac
}

# handle_git_pull
# Performs a git pull and restarts quick-start.sh so updated scripts take effect.
handle_git_pull() {
    echo ""
    echo "🔄 Updating deployment scripts..."
    echo "=================================="
    echo ""

    if git pull; then
        local module_dir repo_root restart_script
        module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        repo_root="$(cd "$module_dir/../.." && pwd)"
        restart_script="${repo_root}/quick-start.sh"

        echo ""
        echo "✅ Repository updated successfully"
        echo ""
        echo "🔁 Restarting quick-start.sh to apply updates..."
        echo ""

        if [ -x "$restart_script" ]; then
            exec "$restart_script"
        elif [ -f "$restart_script" ]; then
            exec bash "$restart_script"
        else
            echo "⚠️  quick-start.sh not found at: $restart_script"
            echo "   Please restart manually."
            return 1
        fi
    else
        echo ""
        echo "❌ Git pull failed. Resolve conflicts manually."
    fi
}
