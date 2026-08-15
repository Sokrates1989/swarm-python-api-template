#!/usr/bin/env bash
# Deutsche Texte für das Betreiber-Menü der Bereitstellung.

declare -gA OPERATOR_MENU_MESSAGES=(
    [semver.options_header]='Veröffentlichte Image-Versionen für %s:'
    [semver.release_channel]='Veröffentlichte stabile Versionen oder exakter geprüfter benutzerdefinierter Tag'
    [semver.release_help]='Die stabile Suche listet reine SemVer-Versionen; exakte geprüfte -test- und benutzerdefinierte Tags bleiben verfügbar.'
    [semver.release_plan]='Kanal: Release/benutzerdefiniert (stabile Liste; exakte Tags durch Registry geprüft)'
    [semver.keep_current]='  1/k) Aktuelle Version beibehalten (%s)'
    [semver.show_rollbacks]='  r/x) Rollback-Optionen anzeigen'
    [semver.exact]='  e) Exakten veröffentlichten Image-Tag eingeben (SemVer, -test oder benutzerdefiniert)'
    [semver.highest]='  h) Höchste veröffentlichte stabile Version (%s)'
    [semver.cancel]='  0/q) Abbrechen'
    [semver.back]='  0/q) Zurück'
    [semver.show_more]='  m) Mehr anzeigen'
    [semver.choice_highest]='Auswahl [h]: '
    [semver.choice_keep]='Auswahl [1/k]: '
    [semver.choice]='Auswahl: '
    [semver.exact_prompt]='Exakter veröffentlichter Image-Tag: '
    [semver.invalid_main]='[WARN] Eine angezeigte Version, r/x, e, h oder 0/q wählen.'
    [semver.invalid_rollback]='[WARN] Eine angezeigte Rollback-Option, m oder 0/q wählen.'
    [semver.invalid_tag]='[WARN] Docker-Tag aus Buchstaben, Zahlen, ., _ oder - eingeben. Die veränderlichen latest-Aliase sind nicht erlaubt.'
    [semver.comparison_unavailable]='[WARN] Für %s hat der aktuelle Tag %s keine SemVer-Vergleichsbasis. Die höchste und eine exakte geprüfte Version bleiben auswählbar.'
    [semver.not_published]='[WARN] %s ist für %s keine veröffentlichte linux/amd64-Version.'
    [semver.rollback_series_header]='Rollback-Versionsreihen für %s:'
    [semver.rollback_series]='  %s) %s.X-Versionen anzeigen'
    [semver.rollback_versions_header]='%s: Rollback-Versionen der Reihe %s.X:'
    [semver.rollback_version]='  %s) %s [Rollback]'
)
