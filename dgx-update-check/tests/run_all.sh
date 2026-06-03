#!/usr/bin/env bash
# tests/run_all.sh — run the full dgx-update-check test suite (static + runtime).
# No pip / no bats: pure shell + jq + python3 (all OS-bundled).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "########## dgx-update-check :: STATIC tests ##########"
bash "$HERE/test_static.sh"
rc_static=$?

echo ""
echo "########## dgx-update-check :: RUNTIME tests (read-only) ##########"
bash "$HERE/test_runtime.sh"
rc_runtime=$?

echo ""
echo "########## dgx-update-check :: GLOB hardening tests ##########"
bash "$HERE/test_glob.sh"
rc_glob=$?

echo ""
echo "######################################################"
if [ "$rc_static" -eq 0 ] && [ "$rc_runtime" -eq 0 ] && [ "$rc_glob" -eq 0 ]; then
  echo "ALL SUITES PASSED ✅"
  exit 0
else
  echo "SOME SUITES FAILED ❌  (static=$rc_static runtime=$rc_runtime glob=$rc_glob)"
  exit 1
fi
