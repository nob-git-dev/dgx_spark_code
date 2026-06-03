#!/usr/bin/env bash
# tests/test_static.sh — static safety & structure checks (no machine state needed).
# Verifies F1-F3 / AC11 / ADR-2 / ADR-7 / ADR-9 by inspecting source strings.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
. "$HERE/lib.sh"

COLLECT="$ROOT/scripts/collect.sh"
CONFIG="$ROOT/scripts/config.sh"
SKILL="$ROOT/SKILL.md"
README="$ROOT/README.md"

echo "== static: file structure (T-FILE) =="
assert_file "T-FILE-1a scripts/collect.sh exists" "$COLLECT"
assert_file "T-FILE-1b scripts/config.sh exists" "$CONFIG"
assert_file "T-FILE-1c SKILL.md exists" "$SKILL"
assert_file "T-FILE-1d README.md exists" "$README"
if [ -f "$SKILL" ]; then
  # frontmatter must declare name and description
  assert_grep "T-FILE-1e SKILL.md frontmatter has name:" "^name:[[:space:]]*dgx-update-check" "$SKILL"
  assert_grep "T-FILE-1f SKILL.md frontmatter has description:" "^description:[[:space:]]*.+" "$SKILL"
  # ADR-9: must NOT fork (report is presented in user conversation; jlmb precedent has no context)
  assert_no_grep "T-FILE-2 SKILL.md has no 'context: fork'" "^context:[[:space:]]*fork" "$SKILL"
fi

# Build a comment-stripped view of the executable scripts.
# Rationale: config.sh MUST document the forbidden-command allowlist in comments
# (SPEC ADR-2). The safety tests target *executed* commands, so we strip lines that
# are pure comments and inline trailing comments before scanning for forbidden verbs.
STRIP_COLLECT="$(mktemp)"
STRIP_CONFIG="$(mktemp)"
trap 'rm -f "$STRIP_COLLECT" "$STRIP_CONFIG"' EXIT
strip_comments() {
  # remove full-line comments (optionally indented) and inline ' # ...' trailers;
  # keep shebang harmlessly (it contains no forbidden verbs)
  sed -e 's/[[:space:]]#[[:space:]].*$//' -e '/^[[:space:]]*#/d' "$1"
}
if [ -f "$COLLECT" ]; then strip_comments "$COLLECT" > "$STRIP_COLLECT"; fi
if [ -f "$CONFIG" ];  then strip_comments "$CONFIG"  > "$STRIP_CONFIG"; fi

echo "== static: safety — forbidden commands absent from EXECUTED code (T-SAFE) =="
for pair in "collect:$STRIP_COLLECT" "config:$STRIP_CONFIG"; do
  label="${pair%%:*}"; f="${pair#*:}"
  [ -f "$f" ] || continue
  assert_no_grep "T-SAFE-1 ($label) no 'sudo' executed"            '(^|[[:space:];&|(])sudo([[:space:]]|$)' "$f"
  assert_no_grep "T-SAFE-2 ($label) no 'apt update/apt-get update'" '\bapt(-get)?[[:space:]]+update\b' "$f"
  # real (non -s) mutating apt subcommands: catch the verb when NOT immediately part of a simulated call.
  assert_no_grep "T-SAFE-3 ($label) no real apt upgrade/install/remove/autoremove/purge/dist/full" \
    '\bapt(-get)?[[:space:]]+(install|remove|autoremove|purge|dist-upgrade)\b' "$f"
  # upgrade / full-upgrade must never appear without -s on the same apt-get invocation
  assert_no_grep "T-SAFE-3b ($label) no 'apt-get ... upgrade' without -s" \
    '\bapt-get[[:space:]]+(upgrade|full-upgrade)\b' "$f"
  assert_no_grep "T-SAFE-4 ($label) no .deb download (download/-d/--download-only)" \
    '\bapt-get[[:space:]].*(\bdownload\b|[[:space:]]-d\b|--download-only)' "$f"
  assert_no_grep "T-SAFE-5 ($label) no systemctl mutate (start/stop/restart/reload/mask)" \
    '\bsystemctl[[:space:]]+(start|stop|restart|reload|mask|unmask|enable|disable)\b' "$f"
  assert_no_grep "T-SAFE-6 ($label) no 'dpkg -i' / 'dpkg --install'" \
    '\bdpkg[[:space:]].*(-i\b|--install\b)' "$f"
done

# T-SAFE-7: every apt-get invocation in the EXECUTED collect code must carry -s.
if [ -f "$STRIP_COLLECT" ]; then
  bad_aptget="$(grep -nE '\bapt-get\b' "$STRIP_COLLECT" | grep -vE '\bapt-get[[:space:]]+(-s|--simulate|--dry-run|--just-print|--no-act|--recon|--simulate-only)\b' || true)"
  if [ -z "$bad_aptget" ]; then
    _t_ok "T-SAFE-7 every apt-get call carries -s (simulation)"
  else
    _t_no "T-SAFE-7 every apt-get call carries -s (simulation)" "offending: $(echo "$bad_aptget" | tr '\n' ' ')"
  fi
fi

echo "== static: allowlist documented + locale fixed (T-SAFE-8 / T-LOCALE) =="
if [ -f "$CONFIG" ]; then
  # ADR-2: allowlist must be documented in config.sh comments (machine-greppable marker)
  assert_grep "T-SAFE-8 config.sh documents allowlist (ALLOWLIST marker)" "ALLOWLIST" "$CONFIG"
  # ADR-7 / F5: LC_ALL=C exported for stable apt parsing
  assert_grep "T-LOCALE-1 config.sh exports LC_ALL=C" "export[[:space:]]+LC_ALL=C" "$CONFIG"
fi

t_summary "static"
exit $?
