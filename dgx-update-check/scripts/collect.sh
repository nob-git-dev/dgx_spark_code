#!/usr/bin/env bash
# collect.sh — DATA LAYER (decisive, read-only) for the dgx-update-check skill.
#
# Emits a single JSON document on stdout describing what a DGX/Ubuntu update would
# bring, WITHOUT any side-effects: no apt update, no downloads, no service changes,
# no sudo. Only the read-only ALLOWLIST in config.sh is used (ADR-1/ADR-2).
#
# Design notes:
#   - preflight failure => fail-fast: emit JSON with preflight.ok=false and exit non-zero,
#     WITHOUT touching the apt layer (ADR-5 / AC1).
#   - individual command failures after preflight => recorded in errors[]; collect continues
#     and still emits a valid JSON (fail-soft / ADR-5).
#   - download size = Σ of apt-cache "Size:" of install-action packages (ADR-6); never a real fetch.
#   - apt CLI forced to LC_ALL=C for stable parsing (ADR-7).
#   - DGXUC_FAKE_ARCH may override detected arch (TEST HOOK ONLY) to exercise the fail-fast path.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/config.sh"

# ---------- preflight (AC1) ----------
ARCH="$(uname -m 2>/dev/null || echo unknown)"
# test hook: allow arch override so the fail-fast branch is verifiable without a real x86 box
if [ -n "${DGXUC_FAKE_ARCH:-}" ]; then ARCH="$DGXUC_FAKE_ARCH"; fi

CODENAME="unknown"
VERSION_ID_VAL="unknown"
if [ -r /etc/os-release ]; then
  # read values without executing arbitrary content
  CODENAME="$(. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-unknown}")"
  VERSION_ID_VAL="$(. /etc/os-release 2>/dev/null; echo "${VERSION_ID:-unknown}")"
fi

OTA_TOOL_PATH="$(command -v "$DGXUC_OTA_TOOL" 2>/dev/null || true)"

PRE_OK="true"
PRE_REASON="null"   # JSON null literal unless set
if [ "$ARCH" != "$DGXUC_REQUIRED_ARCH" ]; then
  PRE_OK="false"; PRE_REASON="arch '$ARCH' != required '$DGXUC_REQUIRED_ARCH'"
elif [ "$CODENAME" != "$DGXUC_REQUIRED_CODENAME" ]; then
  PRE_OK="false"; PRE_REASON="OS codename '$CODENAME' != required '$DGXUC_REQUIRED_CODENAME'"
elif [ -z "$OTA_TOOL_PATH" ]; then
  PRE_OK="false"; PRE_REASON="'$DGXUC_OTA_TOOL' not found on PATH"
fi

# emit_json builds the final document from environment variables using python3 (robust escaping).
# All *_RAW vars hold raw command output (or empty). PRE_* hold preflight scalars.
emit_json() {
  PRE_OK="$PRE_OK" PRE_REASON="$PRE_REASON" ARCH="$ARCH" CODENAME="$CODENAME" \
  VERSION_ID_VAL="$VERSION_ID_VAL" OTA_TOOL_PATH="$OTA_TOOL_PATH" \
  OTA_AVAIL_RAW="${OTA_AVAIL_RAW:-}" OTA_INSTALLED_RAW="${OTA_INSTALLED_RAW:-}" \
  OTA_TORN_RAW="${OTA_TORN_RAW:-}" OTA_VERSIONS_RAW="${OTA_VERSIONS_RAW:-}" \
  UPGRADABLE_RAW="${UPGRADABLE_RAW:-}" FULLUPG_RAW="${FULLUPG_RAW:-}" \
  APTCACHE_RAW="${APTCACHE_RAW:-}" MEM_RAW="${MEM_RAW:-}" \
  IDX_MTIME="${IDX_MTIME:-}" IDX_FILE="${IDX_FILE:-}" \
  LISTS_SNAPSHOT="${LISTS_SNAPSHOT:-}" SVC_RAW="${SVC_RAW:-}" \
  DGXUC_DASHBOARD_SERVICES="$DGXUC_DASHBOARD_SERVICES" \
  ERRORS_RAW="${ERRORS_RAW:-}" \
  python3 "$SCRIPT_DIR/build_json.py"
}

# fail-fast on preflight failure: do NOT touch apt layer (ADR-5 / AC1)
if [ "$PRE_OK" != "true" ]; then
  ERRORS_RAW=""
  emit_json
  exit 2
fi

# ---------- error accumulator (fail-soft / ADR-5) ----------
ERRORS_RAW=""
note_err() { ERRORS_RAW="${ERRORS_RAW}${1}"$'\n'; }

# ---------- layer 1: DGX OTA (AC2/AC3) ----------
OTA_AVAIL_RAW="$("$DGXUC_OTA_TOOL" is-ota-available 2>/dev/null)"  || note_err "ota:is-ota-available failed"
OTA_INSTALLED_RAW="$("$DGXUC_OTA_TOOL" installed-name 2>/dev/null)" || note_err "ota:installed-name failed"
OTA_TORN_RAW="$("$DGXUC_OTA_TOOL" torn-score 2>/dev/null)"         || note_err "ota:torn-score failed"

# only pull the (large) ota-versions when a new generation is actually available
OTA_VERSIONS_RAW=""
if printf '%s' "$OTA_AVAIL_RAW" | jq -e '.available == true' >/dev/null 2>&1; then
  OTA_VERSIONS_RAW="$("$DGXUC_OTA_TOOL" ota-versions 2>/dev/null)" || note_err "ota:ota-versions failed"
fi

# ---------- layer 2: apt (AC4/AC5) ----------
UPGRADABLE_RAW="$(apt list --upgradable 2>/dev/null)"     || note_err "apt:list --upgradable failed"
FULLUPG_RAW="$(apt-get -s full-upgrade 2>/dev/null)"      || note_err "apt:apt-get -s full-upgrade failed"

# Gather apt-cache show only for the packages that will actually be installed (Inst lines).
# Format the cache output as: ===PKG:<name>=== <stanza...> so build_json can map Size per pkg.
# Harden the iteration: read the harvested names into an ARRAY (mapfile -t) and iterate the
# QUOTED expansion. This disables BOTH glob expansion (a pseudo name like 'foo-*' is NOT
# expanded against CWD filenames) and word-splitting (a name with whitespace stays one token).
# dpkg forbids metachars in real package names, so this is defensive hardening, not a live hole.
mapfile -t INST_PKGS < <(printf '%s\n' "$FULLUPG_RAW" | awk '/^Inst /{print $2}')
APTCACHE_RAW=""
for p in "${INST_PKGS[@]}"; do
  [ -n "$p" ] || continue   # mapfile yields one empty element when there are no Inst lines
  stanza="$(apt-cache show "$p" 2>/dev/null)" || { note_err "apt:apt-cache show $p failed"; continue; }
  APTCACHE_RAW="${APTCACHE_RAW}===PKG:${p}===
${stanza}
"
done

# ---------- estimate: memory (AC8) ----------
MEM_RAW="$(free -b 2>/dev/null)" || note_err "free failed"

# ---------- freshness: newest apt index mtime (AC10) ----------
IDX_LINE="$(ls -lt --time-style=long-iso "$DGXUC_APT_LISTS_DIR"/*Packages* 2>/dev/null | head -1)"
IDX_MTIME="$(printf '%s' "$IDX_LINE" | awk '{print $6" "$7}')"
IDX_FILE="$(printf '%s' "$IDX_LINE" | awk '{print $NF}')"
[ -n "$IDX_MTIME" ] || note_err "freshness: could not read apt index mtime"

# ---------- safety material (AC9 / ADR-8) ----------
# newest mtime across the index FILES (not the volatile 'partial/' working dir, which
# apt/dashboard activity can touch independently). Only regular index files are read so
# the before/after snapshot is a stable witness that *this skill* changed nothing.
LISTS_SNAPSHOT="$(ls -l --time-style=long-iso "$DGXUC_APT_LISTS_DIR"/*Packages* "$DGXUC_APT_LISTS_DIR"/*Release* 2>/dev/null | awk '/^-/ && NF>=7{print $6" "$7" "$NF}' | sort | tail -1)"
# observe dashboard services WITHOUT touching them (F2): is-active only.
# Split the (config-controlled, metachar-free) service list into an array via `read -ra`
# rather than relying on unquoted word-splitting, so glob expansion can never apply here
# either — consistent with the Inst-package iteration above.
SVC_RAW=""
read -ra DGXUC_SVC_ARR <<< "$DGXUC_DASHBOARD_SERVICES"
for s in "${DGXUC_SVC_ARR[@]}"; do
  st="$(systemctl is-active "$s" 2>/dev/null || true)"
  [ -n "$st" ] || st="unknown"
  SVC_RAW="${SVC_RAW}${s} ${st}"$'\n'
done

emit_json
exit 0
