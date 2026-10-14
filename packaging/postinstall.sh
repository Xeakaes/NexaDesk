#!/bin/sh
# Refresh desktop database if available (best-effort).
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
# Refresh the GTK icon cache too — some distros show no icon until this runs.
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
exit 0
