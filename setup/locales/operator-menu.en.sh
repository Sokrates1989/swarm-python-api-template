#!/usr/bin/env bash
# English messages for the deployment operator menu.

declare -gA OPERATOR_MENU_MESSAGES=(
    [semver.options_header]='%s published image version options:'
    [semver.release_channel]='Published stable releases or an exact verified custom tag'
    [semver.release_help]='Stable discovery lists clean SemVer releases; exact verified -test and custom tags remain available.'
    [semver.release_plan]='Channel: release/custom (stable list; exact tags registry-verified)'
    [semver.keep_current]='  1/k) Keep current (%s)'
    [semver.show_rollbacks]='  r/x) Show rollback options'
    [semver.exact]='  e) Enter an exact published image tag (SemVer, -test, or custom)'
    [semver.highest]='  h) Highest published stable version (%s)'
    [semver.cancel]='  0/q) Cancel'
    [semver.back]='  0/q) Back'
    [semver.show_more]='  m) Show more'
    [semver.choice_highest]='Your choice [h]: '
    [semver.choice_keep]='Your choice [1/k]: '
    [semver.choice]='Your choice: '
    [semver.exact_prompt]='Exact published image tag: '
    [semver.invalid_main]='[WARN] Choose a shown published version, r/x, e, h, or 0/q.'
    [semver.invalid_rollback]='[WARN] Choose a shown rollback option, m, or 0/q.'
    [semver.invalid_tag]='[WARN] Enter a Docker tag using letters, numbers, ., _, or -. The mutable latest aliases are not allowed.'
    [semver.comparison_unavailable]='[WARN] %s current tag %s has no SemVer comparison base. Highest and exact verified tag selection remain available.'
    [semver.not_published]='[WARN] %s is not a published linux/amd64 version for %s.'
    [semver.rollback_series_header]='%s rollback release series:'
    [semver.rollback_series]='  %s) Show %s.X versions'
    [semver.rollback_versions_header]='%s %s.X rollback versions:'
    [semver.rollback_version]='  %s) %s [rollback]'
)
