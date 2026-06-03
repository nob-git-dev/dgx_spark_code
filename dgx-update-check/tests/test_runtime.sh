#!/usr/bin/env bash
# tests/test_runtime.sh — runs collect.sh once (read-only) and verifies the JSON
# contract (ADR-4), size logic (ADR-6), preflight (AC1), and zero side-effects (AC9/ADR-8).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
. "$HERE/lib.sh"

COLLECT="$ROOT/scripts/collect.sh"

if [ ! -x "$COLLECT" ] && [ ! -f "$COLLECT" ]; then
  _t_no "T-RUNTIME-precond collect.sh present" "missing $COLLECT"
  t_summary "runtime"; exit 1
fi

# ---- capture side-effect baseline BEFORE running collect.sh (AC9 / ADR-8) ----
lists_mtime_before="$(ls -l --time-style=long-iso /var/lib/apt/lists/ 2>/dev/null | awk '{print $6" "$7}' | sort | tail -1)"
svc_before="$(systemctl is-active dgx-dashboard.service dgx-dashboard-admin.service 2>&1 | tr '\n' ',')"

# ---- run collect.sh, capture JSON (normal preflight-pass case) ----
OUT="$(mktemp)"; ERR="$(mktemp)"
trap 'rm -f "$OUT" "$ERR"' EXIT
bash "$COLLECT" >"$OUT" 2>"$ERR"
rc=$?

# ---- capture side-effect state AFTER ----
lists_mtime_after="$(ls -l --time-style=long-iso /var/lib/apt/lists/ 2>/dev/null | awk '{print $6" "$7}' | sort | tail -1)"
svc_after="$(systemctl is-active dgx-dashboard.service dgx-dashboard-admin.service 2>&1 | tr '\n' ',')"

echo "== runtime: preflight pass + exit code (T-PRE-1) =="
assert_eq "T-PRE-1a collect.sh exit 0 on valid env" "0" "$rc"

echo "== runtime: JSON validity (T-JSON-1) =="
assert_true "T-JSON-1a jq parses stdout"     jq -e . "$OUT"
assert_true "T-JSON-1b python3 parses stdout" python3 -c 'import sys,json; json.load(open(sys.argv[1]))' "$OUT"

# helper: KEY-PRESENCE check (tolerates values that are false/null/0/"").
# Naively `jq -e .a.b` would FAIL on a legitimate false/null value, so instead we
# descend to the parent object via getpath and assert has("lastkey").
jhas() {
  _p="${1#.}"; _last="${_p##*.}"; _parent="${_p%.*}"
  if [ "$_parent" = "$_p" ]; then
    jq -e --arg k "$_last" 'has($k)' "$OUT" >/dev/null 2>&1
  else
    _pj="$(printf '%s' "$_parent" | jq -R 'split(".")')"
    jq -e --argjson pp "$_pj" --arg k "$_last" 'getpath($pp) | objects | has($k)' "$OUT" >/dev/null 2>&1
  fi
}

echo "== runtime: required top-level keys (T-JSON-2 / ADR-4) =="
for k in preflight ota apt estimate freshness safety errors; do
  assert_true "T-JSON-2 has .$k" jhas ".$k"
done

echo "== runtime: preflight contract (AC1) =="
assert_true "T-PRE-1b preflight.ok == true" jq -e '.preflight.ok == true' "$OUT"
assert_true "T-PRE-1c preflight.arch present" jhas '.preflight.arch'
assert_true "T-PRE-1d preflight.codename present" jhas '.preflight.codename'
assert_true "T-PRE-1e preflight.ota_tool present" jhas '.preflight.ota_tool'

echo "== runtime: OTA layer-1 contract (T-JSON-3 / AC2 / AC3) =="
for k in available name description releaseNotesUrl releaseDate; do
  assert_true "T-JSON-3 ota.is_available.$k" jhas ".ota.is_available.$k"
done
assert_true "T-JSON-3 ota.installed_name" jhas '.ota.installed_name'
assert_true "T-JSON-3 ota.torn"           jhas '.ota.torn'

echo "== runtime: apt layer-2 contract (T-JSON-4 / AC4 / AC5) =="
assert_true "T-JSON-4 apt.upgradable_raw is string" jq -e '.apt.upgradable_raw | type == "string"' "$OUT"
assert_true "T-JSON-4 apt.packages is array"        jq -e '.apt.packages | type == "array"' "$OUT"
for k in install phasing remove new; do
  assert_true "T-JSON-4 apt.counts.$k is number" jq -e ".apt.counts.$k | type == \"number\"" "$OUT"
done
assert_true "T-JSON-4 apt.phasing_deferred is array"      jq -e '.apt.phasing_deferred | type == "array"' "$OUT"
assert_true "T-JSON-4 apt.autoremove_candidates is array" jq -e '.apt.autoremove_candidates | type == "array"' "$OUT"
# every package element must carry the full field set (AC4/AC5). Skip if no upgrades available.
pkgcount="$(jq -r '.apt.packages | length' "$OUT" 2>/dev/null || echo 0)"
if [ "${pkgcount:-0}" -gt 0 ]; then
  for fld in name ver_from ver_to repos is_security action size_bytes description; do
    assert_true "T-JSON-4 every package has .$fld" \
      jq -e "[.apt.packages[] | has(\"$fld\")] | all" "$OUT"
  done
  assert_true "T-JSON-4 action enum ⊆ {install,phasing,remove}" \
    jq -e '[.apt.packages[].action] | all(. == "install" or . == "phasing" or . == "remove")' "$OUT"
else
  _t_ok "T-JSON-4 packages empty (no upgrades) — field-set check skipped"
fi

echo "== runtime: estimate contract (T-JSON-5 / AC8) =="
for k in download_bytes_total download_human mem_available_bytes mem_available_human; do
  assert_true "T-JSON-5 estimate.$k present" jhas ".estimate.$k"
done
assert_true "T-JSON-5 mem_available_bytes is number" jq -e '.estimate.mem_available_bytes | type == "number"' "$OUT"

echo "== runtime: freshness contract (T-JSON-6 / AC10) =="
assert_true "T-JSON-6 freshness.apt_index_mtime" jhas '.freshness.apt_index_mtime'
assert_true "T-JSON-6 freshness.apt_index_file"  jhas '.freshness.apt_index_file'

echo "== runtime: size logic = sum of install size_bytes (T-SIZE-1 / ADR-6) =="
# download_bytes_total must equal the sum of size_bytes over action==install where size_bytes!=null.
expected_sum="$(jq -r '[.apt.packages[] | select(.action=="install") | .size_bytes | select(. != null)] | add // 0' "$OUT" 2>/dev/null)"
actual_total="$(jq -r '.estimate.download_bytes_total // 0' "$OUT" 2>/dev/null)"
assert_eq "T-SIZE-1 download_bytes_total == Σ install size_bytes" "$expected_sum" "$actual_total"

echo "== runtime: safety material present (T-NOFX-3 / ADR-8) =="
assert_true "T-NOFX-3a safety.apt_lists_snapshot" jhas '.safety.apt_lists_snapshot'
assert_true "T-NOFX-3b safety.dashboard_services" jhas '.safety.dashboard_services'

echo "== runtime: ZERO side-effects across the run (T-NOFX-1 / T-NOFX-2 / AC9) =="
assert_eq "T-NOFX-1 apt lists newest mtime unchanged" "$lists_mtime_before" "$lists_mtime_after"
assert_eq "T-NOFX-2 dashboard services state unchanged" "$svc_before" "$svc_after"

echo "== runtime: preflight FAIL path is fail-fast (T-PRE-2 / AC1 / ADR-5) =="
# Inject a fake arch so preflight must fail WITHOUT touching layer-2.
OUT2="$(mktemp)"; ERR2="$(mktemp)"
DGXUC_FAKE_ARCH="x86_64" bash "$COLLECT" >"$OUT2" 2>"$ERR2"
rc2=$?
assert_true  "T-PRE-2a non-zero exit when arch wrong" test "$rc2" -ne 0
# Output (if any) must still be valid JSON and report ok=false with a reason.
if jq -e . "$OUT2" >/dev/null 2>&1; then
  assert_true "T-PRE-2b preflight.ok == false" jq -e '.preflight.ok == false' "$OUT2"
  assert_true "T-PRE-2c reason is non-null"     jq -e '.preflight.reason != null' "$OUT2"
  # fail-fast: apt layer must not be populated (null or empty)
  assert_true "T-PRE-2d apt layer not populated (fail-fast)" \
    jq -e '(.apt == null) or (.apt.packages == null) or ((.apt.packages | length) == 0)' "$OUT2"
else
  _t_no "T-PRE-2b/c/d preflight-fail JSON" "expected valid JSON on preflight failure, got: $(head -c 200 "$OUT2")"
fi
rm -f "$OUT2" "$ERR2"

# Surface collect.sh stderr if the main run failed, to aid debugging.
if [ "$rc" -ne 0 ] && [ -s "$ERR" ]; then
  echo "  (collect.sh stderr on main run:)"; sed 's/^/    /' "$ERR"
fi

t_summary "runtime"
exit $?
