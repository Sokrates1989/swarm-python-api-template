#!/usr/bin/env bash
# Loads the English or German deployment operator-menu message catalog.

if [ -n "${_OPERATOR_MENU_LOCALIZATION_LOADED:-}" ]; then
    return 0 2>/dev/null || true
fi
_OPERATOR_MENU_LOCALIZATION_LOADED=1

_OPERATOR_MENU_LOCALIZATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_operator_menu_locale="${OPERATOR_MENU_LOCALE:-en}"
case "${_operator_menu_locale,,}" in
    de|de-*) _operator_menu_locale='de' ;;
    *) _operator_menu_locale='en' ;;
esac
source "${_OPERATOR_MENU_LOCALIZATION_DIR}/../locales/operator-menu.${_operator_menu_locale}.sh"

# Formats one localized operator-menu message without appending a newline.
operator_menu_message() {
    local key="$1"
    shift
    [ -n "${OPERATOR_MENU_MESSAGES[$key]+configured}" ] || return 1
    # shellcheck disable=SC2059 -- trusted catalogs intentionally own formats.
    printf "${OPERATOR_MENU_MESSAGES[$key]}" "$@"
}
