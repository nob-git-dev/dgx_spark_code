#!/usr/bin/env bash
# config.sh — externalised settings for the dgx-update-check skill (CLAUDE.md 第5条).
# Sourced by collect.sh. Contains NO executable side-effects: only constants and the
# documented read-only command ALLOWLIST (ADR-2). Reviewers can grep this file to
# machine-verify F1/F3 compliance.
#
# ============================ ALLOWLIST (ADR-2) ============================
# collect.sh may ONLY invoke the following read-only commands. This is an
# allowlist (default-deny): anything not listed here must never be executed.
#
#   ALLOW  nvidia-spark-ota-check  is-ota-available | installed-name | torn-score
#                                  | ota-versions            (read-only subcommands)
#   ALLOW  apt list --upgradable                              (read-only listing)
#   ALLOW  apt-get -s full-upgrade                            (SIMULATION only; -s mandatory)
#   ALLOW  apt-cache show <pkg>                               (local metadata only)
#   ALLOW  free                                               (memory read)
#   ALLOW  ls                                                 (mtime / snapshot read)
#   ALLOW  uname                                              (arch detection)
#   ALLOW  systemctl is-active <svc>                          (OBSERVE only — F2 boundary)
#   ALLOW  dpkg-query -W                                      (installed query, read-only)
#   ALLOW  jq / python3                                       (JSON shaping, no I/O side-effects)
#
# FORBIDDEN — must never appear as executed commands in collect.sh/config.sh:
#   sudo
#   apt update | apt-get update                               (rewrites the index — F3)
#   apt(-get) upgrade | full-upgrade | dist-upgrade | install | remove | autoremove | purge   (real mutation — F1/F3)
#       NB: "apt-get -s full-upgrade" is allowed because -s makes it a no-op simulation.
#   apt-get download | apt-get -d | --download-only           (fetches real .deb — F1)
#   systemctl start|stop|restart|reload|mask|enable|disable   (mutates dashboard mechanism — F2)
#   dpkg -i | dpkg --install                                  (installs packages — F1)
#   any write redirection (> / >>) into production resources
# ==========================================================================

# --- locale: force C so apt CLI emits stable English tokens (ADR-7 / F5) ---
export LC_ALL=C
export LANG=C

# --- default release-notes URL (used only as a fallback hint for the judge layer).
#     The authoritative URL is whatever `nvidia-spark-ota-check is-ota-available`
#     returns at runtime; this is just a documented default (第5条: no hardcoding in SKILL.md body). ---
DGXUC_DEFAULT_RELEASE_NOTES_URL="https://docs.nvidia.com/dgx/dgx-spark/release-notes.html"

# --- dashboard services that must NOT be touched (F2). Observed via is-active only. ---
DGXUC_DASHBOARD_SERVICES="dgx-dashboard.service dgx-dashboard-admin.service"

# --- environment preconditions (AC1) ---
DGXUC_REQUIRED_ARCH="aarch64"
DGXUC_REQUIRED_CODENAME="noble"
DGXUC_OTA_TOOL="nvidia-spark-ota-check"

# --- apt index location (read-only; freshness/AC10 + side-effect snapshot/AC9) ---
DGXUC_APT_LISTS_DIR="/var/lib/apt/lists"
