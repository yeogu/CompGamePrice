#!/usr/bin/env bash
set -euo pipefail

project_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
label="com.compgameprice.steam-collection"
domain="gui/$(id -u)"
service="${domain}/${label}"
generated_plist="${project_directory}/snapshots/${label}.plist"
installed_plist="${HOME}/Library/LaunchAgents/${label}.plist"

show_status() {
    if launchctl print "${service}" >/dev/null 2>&1; then
        launchctl print "${service}"
    else
        echo "Steam collection schedule is not registered."
        return 1
    fi
}

case "${1:-}" in
    install)
        python3 "${project_directory}/tools/generate_macos_schedule.py" \
            --project-dir "${project_directory}" \
            --output "${generated_plist}"
        plutil -lint "${generated_plist}"
        mkdir -p "$(dirname "${installed_plist}")"
        install -m 0644 "${generated_plist}" "${installed_plist}"
        if launchctl print "${service}" >/dev/null 2>&1; then
            launchctl bootout "${service}"
        fi
        launchctl enable "${service}"
        launchctl bootstrap "${domain}" "${installed_plist}"
        echo "Registered ${label}; it will run every day at 09:00."
        ;;
    run)
        launchctl kickstart -k "${service}"
        echo "Triggered ${label}."
        ;;
    status)
        show_status
        ;;
    uninstall)
        if launchctl print "${service}" >/dev/null 2>&1; then
            launchctl bootout "${service}"
        fi
        if [[ -f "${installed_plist}" ]]; then
            backup="${project_directory}/snapshots/${label}.uninstalled.plist"
            mv "${installed_plist}" "${backup}"
            echo "Unregistered ${label}; plist moved to ${backup}."
        else
            echo "Steam collection schedule was not installed."
        fi
        ;;
    *)
        echo "Usage: $0 {install|run|status|uninstall}" >&2
        exit 2
        ;;
esac
