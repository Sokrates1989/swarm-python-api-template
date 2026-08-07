#!/bin/bash
# ==============================================================================
# menu-shortcuts.sh - Stable cross-repository operator shortcuts
# ==============================================================================
#
# Defines the letter contract shared by Swarm quick-start menus. Repositories
# may expose additional local shortcuts, but a letter declared here must keep
# the same meaning everywhere. Numeric menu choices remain compatibility
# aliases and are intentionally outside this stable contract.
# ==============================================================================

# Guard against multiple sourcing.
if [ -n "${_MENU_SHORTCUTS_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_MENU_SHORTCUTS_LOADED=1

# operator_menu_shortcut_key
# Returns the canonical key for one shared operator action.
#
# Arguments:
#   $1 - Stable action identifier.
#
# Output:
#   One lowercase shortcut, or no output for an unknown action.
#
# Returns:
#   0 for a known action; otherwise 1.
operator_menu_shortcut_key() {
    case "$1" in
        audit-images) echo "a" ;;
        bootstrap) echo "b" ;;
        deploy) echo "d" ;;
        logging) echo "g" ;;
        health) echo "h" ;;
        images) echo "i" ;;
        logs) echo "l" ;;
        database-admin) echo "p" ;;
        refresh) echo "r" ;;
        secrets) echo "s" ;;
        update) echo "u" ;;
        exit) echo "q" ;;
        *) return 1 ;;
    esac
}

# resolve_operator_menu_shortcut
# Resolves a case-insensitive shared shortcut to its stable action identifier.
#
# Arguments:
#   $1 - Raw operator input.
#
# Output:
#   Stable action identifier, or no output when the input is not shared.
#
# Returns:
#   0 for a shared shortcut; otherwise 1.
resolve_operator_menu_shortcut() {
    local normalized=""

    normalized="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "$normalized" in
        a) echo "audit-images" ;;
        b) echo "bootstrap" ;;
        d) echo "deploy" ;;
        g) echo "logging" ;;
        h) echo "health" ;;
        i) echo "images" ;;
        l) echo "logs" ;;
        p) echo "database-admin" ;;
        r) echo "refresh" ;;
        s) echo "secrets" ;;
        u) echo "update" ;;
        q) echo "exit" ;;
        *) return 1 ;;
    esac
}
