# tests/lib.sh — minimal POSIX-sh assertion helpers (no pip, no bats)
# Sourced by test_static.sh / test_runtime.sh. Tracks pass/fail counts.

T_PASS=0
T_FAIL=0
T_FAILED_NAMES=""

_t_ok() {
  T_PASS=$((T_PASS + 1))
  printf '  \033[32mPASS\033[0m %s\n' "$1"
}

_t_no() {
  T_FAIL=$((T_FAIL + 1))
  T_FAILED_NAMES="${T_FAILED_NAMES}\n  - $1"
  printf '  \033[31mFAIL\033[0m %s\n' "$1"
  if [ -n "$2" ]; then printf '       %s\n' "$2"; fi
}

# assert_true NAME CMD...   -> CMD exits 0
assert_true() {
  name="$1"; shift
  if "$@" >/dev/null 2>&1; then _t_ok "$name"; else _t_no "$name" "expected success: $*"; fi
}

# assert_false NAME CMD...  -> CMD exits non-zero
assert_false() {
  name="$1"; shift
  if "$@" >/dev/null 2>&1; then _t_no "$name" "expected failure: $*"; else _t_ok "$name"; fi
}

# assert_eq NAME EXPECTED ACTUAL
assert_eq() {
  if [ "$2" = "$3" ]; then _t_ok "$1"; else _t_no "$1" "expected [$2] got [$3]"; fi
}

# assert_file NAME PATH
assert_file() {
  if [ -f "$2" ]; then _t_ok "$1"; else _t_no "$1" "missing file: $2"; fi
}

# assert_grep NAME PATTERN FILE  -> PATTERN found (extended regex)
assert_grep() {
  if grep -Eq "$2" "$3" 2>/dev/null; then _t_ok "$1"; else _t_no "$1" "pattern not found: $2 in $3"; fi
}

# assert_no_grep NAME PATTERN FILE  -> PATTERN NOT found
assert_no_grep() {
  if grep -Eq "$2" "$3" 2>/dev/null; then
    _t_no "$1" "forbidden pattern present: $2 in $3 -> $(grep -nE "$2" "$3" | head -3 | tr '\n' ' ')"
  else
    _t_ok "$1"
  fi
}

t_summary() {
  echo ""
  echo "---- $1 ----"
  echo "  passed: $T_PASS   failed: $T_FAIL"
  if [ "$T_FAIL" -ne 0 ]; then
    printf "  failures:%b\n" "$T_FAILED_NAMES"
    return 1
  fi
  return 0
}
