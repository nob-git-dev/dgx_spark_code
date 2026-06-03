#!/usr/bin/env bash
# tests/test_glob.sh — regression test for the Inst-package iteration hardening
# (review Should, scripts/collect.sh). The package-name list that drives the
# `apt-cache show` loop must be iterated WITHOUT glob expansion and WITHOUT
# word-splitting, so that a pseudo package name containing `*` cannot be
# expanded against filenames in the current working directory, and a token
# containing whitespace is not split into multiple bogus "packages".
#
# Two layers of verification:
#   (T-GLOB-S) STATIC  — collect.sh must no longer iterate the Inst list via the
#              vulnerable unquoted `for p in $INST_PKGS`; it must build an array
#              (mapfile) and iterate the quoted "${INST_PKGS[@]}". This is the
#              guard that prevents the source from regressing.
#   (T-GLOB-R) RUNTIME — exercise the *exact* iteration construct collect.sh now
#              uses, inside a CWD that contains a `glob-canary-*` file, feeding a
#              `*`-token and a whitespace-token, and assert the iterated names are
#              byte-for-byte the inputs (no canary filename leaks in, no split).
#
# No pip / no bats: pure shell + the lib.sh assertion helpers. Read-only.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
. "$HERE/lib.sh"

COLLECT="$ROOT/scripts/collect.sh"

echo "== glob: STATIC — Inst loop is array-based, not unquoted word-splitting (T-GLOB-S) =="
# The vulnerable form must be gone.
assert_no_grep "T-GLOB-S1 no unquoted 'for p in \$INST_PKGS'" \
  'for[[:space:]]+p[[:space:]]+in[[:space:]]+\$INST_PKGS\b' "$COLLECT"
# INST_PKGS must be populated as an array via mapfile (-t strips trailing newlines).
assert_grep "T-GLOB-S2 INST_PKGS built as array via mapfile -t" \
  'mapfile[[:space:]]+-t[[:space:]]+INST_PKGS\b' "$COLLECT"
# The loop must iterate the QUOTED array expansion.
assert_grep "T-GLOB-S3 loop iterates quoted \"\${INST_PKGS[@]}\"" \
  'in[[:space:]]+"\$\{INST_PKGS\[@\]\}"' "$COLLECT"

echo "== glob: RUNTIME — iteration does not glob-expand or word-split (T-GLOB-R) =="
# Sandbox CWD with a canary file that a glob WOULD pick up if expansion were active.
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
: > "$SANDBOX/glob-canary-evil.deb"
: > "$SANDBOX/glob-canary-2.deb"

# Reproduce EXACTLY how collect.sh derives + iterates the install-package list:
# build_json/collect take the `Inst <name>` second field via awk, then iterate.
# We feed an adversarial simulated `apt-get -s full-upgrade` body.
FAKE_FULLUPG="$(printf '%s\n' \
  'Reading package lists...' \
  'Inst liblzma5 [5.6.1-1] (5.6.1-2 Ubuntu:24.04/noble-updates [arm64])' \
  'Inst glob-canary-* [1.0] (2.0 Ubuntu:24.04/noble-updates [arm64])' \
  'Conf liblzma5 (5.6.1-2 Ubuntu:24.04/noble-updates [arm64])')"

# Run the harvest+iteration in a subshell whose CWD is the canary sandbox, using
# the SAME constructs as collect.sh (awk extract -> mapfile array -> quoted iterate).
iterated="$(
  cd "$SANDBOX" || exit 9
  inst="$(printf '%s\n' "$FAKE_FULLUPG" | awk '/^Inst /{print $2}')"
  mapfile -t INST_PKGS <<< "$inst"
  for p in "${INST_PKGS[@]}"; do
    printf '<%s>\n' "$p"
  done
)"

# Expectation: exactly the two Inst names, the second kept literally as
# 'glob-canary-*' (NOT expanded to glob-canary-evil.deb / glob-canary-2.deb),
# and no token split on whitespace.
expected="$(printf '<%s>\n' 'liblzma5' 'glob-canary-*')"
assert_eq "T-GLOB-R1 iterated names are literal (no glob expansion, no split)" \
  "$expected" "$iterated"

# Defensive: the canary filenames must never appear among iterated tokens.
if printf '%s\n' "$iterated" | grep -q 'glob-canary-evil.deb'; then
  _t_no "T-GLOB-R2 canary filename did NOT leak into iteration" \
    "glob expansion picked up a CWD filename: $iterated"
else
  _t_ok "T-GLOB-R2 canary filename did NOT leak into iteration"
fi

# Whitespace-token must stay a single element (word-splitting disabled).
ws_count="$(
  inst="$(printf '%s\n' 'pkg with space' 'second')"
  mapfile -t INST_PKGS <<< "$inst"
  printf '%s\n' "${#INST_PKGS[@]}"
)"
assert_eq "T-GLOB-R3 whitespace token not split (2 elements, not 3+)" "2" "$ws_count"

t_summary "glob"
exit $?
