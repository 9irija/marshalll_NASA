#!/usr/bin/env bash
# PostToolUse hook: lint + targeted tests after an edit. Exit 2 feeds failures back to Claude.
cd "$(dirname "$0")/../.." || exit 0
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python
f=$("$PY" -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('file_path','').replace(chr(92),'/'))" 2>/dev/null)
out=""
rc=0
run() {
  local o
  o=$("$@" 2>&1) || { rc=2; out="$out
\$ $*
$(echo "$o" | tail -25)"; }
}
case "$f" in
  *.py)
    run "$PY" -m ruff check "$f"
    case "$f" in
      */planner/*)           run "$PY" -m pytest -q -x tests/test_cost.py tests/test_planner.py ;;
      */pipeline/*)          run "$PY" -m pytest -q -x tests/test_geo_and_layers.py ;;
      */flight_controller/*) run "$PY" -m pytest -q -x tests/test_verifier.py ;;
      */api/*)               run "$PY" -m pytest -q -x tests/test_api.py ;;
      */tests/*)             run "$PY" -m pytest -q -x "$f" ;;
    esac ;;
  *.ts|*.tsx)
    run bash -c "cd web && npx tsc --noEmit && npx eslint '${f#*web/}'" ;;
esac
if [ $rc -ne 0 ]; then echo "post-edit checks failed:$out" >&2; fi
exit $rc
