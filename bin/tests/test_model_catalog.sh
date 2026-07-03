#!/usr/bin/env bash
# Purpose: Regression tests for the curated install-TUI model suggestion pool
#          (scripts/lib/model-catalog.json + scripts/lib/model-catalog.py).
#          Asserts the reader emits well-formed rows and that the pool feeds
#          bin/agentic-models ranking (the picker's primary-first ordering).
#
# Public API: ./bin/tests/test_model_catalog.sh  (exit 0 on pass, 1 on fail)
# Upstream deps: bash 3.2+, python3, bin/agentic-models. Offline; no network.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
READER="$REPO_DIR/scripts/lib/model-catalog.py"
JSON="$REPO_DIR/scripts/lib/model-catalog.json"
RANKER="$REPO_DIR/bin/agentic-models"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }
has() { case "$2" in *"$1"*) pass "contains: $1" ;; *) fail "missing: $1" ;; esac }

echo "Test 0: files present + reader runs"
[[ -f "$JSON" ]] && pass "catalog json present" || fail "catalog json missing"
[[ -f "$READER" ]] && pass "reader present" || fail "reader missing"

echo "Test 1: catalog is valid JSON with the 7 providers"
if python3 - "$JSON" <<'PY' 2>/dev/null; then
import json, sys
d = json.load(open(sys.argv[1]))
need = {"anthropic","openai","z.ai","kimi","minimax","mistral","xai"}
have = set(d.get("providers", {}))
missing = need - have
assert not missing, f"missing providers: {missing}"
for k in need:
    ms = d["providers"][k].get("models", [])
    assert ms, f"provider {k} has no models"
    for m in ms:
        assert m.get("id"), f"provider {k} has a model with no id"
print("providers+models ok")
PY
  pass "valid JSON, 7 providers with models"
else
  fail "invalid JSON or missing providers/models"
fi

echo "Test 2: providers subcommand lists all 7 keys"
prov="$(python3 "$READER" providers)"
for k in anthropic openai z.ai kimi minimax mistral xai; do
  printf '%s' "$prov" | grep -q "^$k	" && pass "provider listed: $k" || fail "provider missing: $k"
done

echo "Test 3: ids subcommand emits the known flagship ids"
ids="$(python3 "$READER" ids)"
for id in opus sonnet haiku gpt-5 kimi-k2.7 glm-5.2 grok-4 mistral-large-latest; do
  printf '%s\n' "$ids" | grep -qx "$id" && pass "id present: $id" || fail "id missing: $id"
done
count="$(printf '%s\n' "$ids" | grep -c . || true)"
[[ "$count" -ge 20 ]] && pass "pool has $count ids (>=20)" || fail "pool too small: $count"

echo "Test 4: pairs --provider anthropic emits id<TAB>label rows"
pairs="$(python3 "$READER" pairs --provider anthropic)"
printf '%s\n' "$pairs" | grep -q $'^opus\t' && pass "pairs: opus row" || fail "pairs: opus row missing"
printf '%s\n' "$pairs" | grep -q $'^sonnet\t' && pass "pairs: sonnet row" || fail "pairs: sonnet row missing"
# unknown provider -> empty, exit 0
unk="$(python3 "$READER" ids --provider does-not-exist 2>/dev/null)"
[[ -z "$unk" ]] && pass "unknown provider yields empty" || fail "unknown provider yielded rows"

echo "Test 5: pool feeds agentic-models ranking (picker primary ordering)"
eng="$(printf '%s\n' "$ids" | python3 "$RANKER" --suggest engineer 2>/dev/null)"
[[ "$eng" == "sonnet" ]] && pass "engineer primary = sonnet" || fail "engineer primary = $eng (want sonnet)"
skep="$(printf '%s\n' "$ids" | python3 "$RANKER" --suggest skeptic 2>/dev/null)"
[[ "$skep" == "opus" ]] && pass "skeptic primary = opus" || fail "skeptic primary = $skep (want opus)"

echo "Test 6: parse-models reads OpenAI /v1/models JSON from STDIN"
pm_out="$(printf '%s' '{"data":[{"id":"9r/anthropic/claude-opus-4"},{"id":"9r/openai/gpt-5"}]}' | python3 "$READER" parse-models --name 9router)"
printf '%s\n' "$pm_out" | grep -q $'^9r/anthropic/claude-opus-4\t9router: 9r/anthropic/claude-opus-4$' && pass "parse-models: opus row" || fail "parse-models: opus row missing"
printf '%s\n' "$pm_out" | grep -q $'^9r/openai/gpt-5\t9router: 9r/openai/gpt-5$' && pass "parse-models: gpt-5 row" || fail "parse-models: gpt-5 row missing"
# bare list shape tolerated (some gateways omit the {"data":...} envelope)
pm_list="$(printf '%s' '[{"id":"x/a"}]' | python3 "$READER" parse-models --name x)"
printf '%s\n' "$pm_list" | grep -q $'^x/a\tx: x/a$' && pass "parse-models: bare list" || fail "parse-models: bare list missing"
# entries without a string id are skipped
pm_skip="$(printf '%s' '{"data":[{"name":"no-id"},{"id":"ok/1"}]}' | python3 "$READER" parse-models --name s)"
[[ "$(printf '%s\n' "$pm_skip" | grep -c .)" -eq 1 ]] && pass "parse-models: skips id-less entries" || fail "parse-models: did not skip id-less entries"
# ids containing control chars (tab/newline) break the id<TAB>label row
# contract and are skipped, same as id-less entries
pm_ctrl="$(printf '%s' '{"data":[{"id":"a\nb"},{"id":"good\tmodel"},{"id":"clean/1"}]}' | python3 "$READER" parse-models --name c)"
[[ "$(printf '%s\n' "$pm_ctrl" | grep -c .)" -eq 1 ]] && pass "parse-models: skips control-char ids" || fail "parse-models: did not skip control-char ids"
printf '%s\n' "$pm_ctrl" | grep -q $'^clean/1\t' && pass "parse-models: clean id still emitted" || fail "parse-models: clean id missing"
# invalid JSON -> exit 2 (signals caller to fall back to curated pool)
set +e
printf '%s' 'not json' | python3 "$READER" parse-models >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]] && pass "parse-models: invalid JSON -> exit 2" || fail "parse-models: invalid JSON rc=$rc (want 2)"
# non-UTF-8 stdin -> exit 2, no traceback (UnicodeDecodeError must honor the
# exit-2 contract, not crash)
set +e
utf8_err="$(printf '\xff\xfe' | python3 "$READER" parse-models --name x 2>&1 >/dev/null)"
rc=$?
set -e
[[ "$rc" -eq 2 ]] && pass "parse-models: non-UTF-8 stdin -> exit 2" || fail "parse-models: non-UTF-8 rc=$rc (want 2)"
case "$utf8_err" in
*Traceback*) fail "parse-models: non-UTF-8 stdin printed a traceback" ;;
*) pass "parse-models: non-UTF-8 stdin has no traceback" ;;
esac
# pathologically nested JSON (RecursionError) -> exit 2, not a crash
set +e
python3 -c 'print("["*100000)' | python3 "$READER" parse-models --name x >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]] && pass "parse-models: deep nesting -> exit 2" || fail "parse-models: deep nesting rc=$rc (want 2)"
# DEL (0x7F) and C1 (0x80-0x9F) control chars are skipped like C0 ones
pm_del="$(printf '{"data":[{"id":"del\x7fmodel"},{"id":"c1\xc2\x85model"},{"id":"fine/2"}]}' | python3 "$READER" parse-models --name d)"
[[ "$(printf '%s\n' "$pm_del" | grep -c .)" -eq 1 ]] && pass "parse-models: skips DEL/C1 ids" || fail "parse-models: did not skip DEL/C1 ids"
printf '%s\n' "$pm_del" | grep -q $'^fine/2\t' && pass "parse-models: clean id survives DEL/C1 filter" || fail "parse-models: clean id missing after DEL/C1 filter"
# bidi/zero-width code points are rejected (they persist to disk in
# CUSTOM_IDS/team config); ordinary non-ASCII letters must NOT be over-blocked.
# U+202E = RIGHT-TO-LEFT OVERRIDE (UTF-8 e2 80 ae).
pm_bidi="$(printf '{"data":[{"id":"evil\xe2\x80\xaemodel"},{"id":"caf\xc3\xa9/\xe6\xa8\xa1\xe5\x9e\x8b-1"}]}' | python3 "$READER" parse-models --name b)"
[[ "$(printf '%s\n' "$pm_bidi" | grep -c .)" -eq 1 ]] && pass "parse-models: skips bidi (U+202E) id" || fail "parse-models: did not skip bidi id"
printf '%s\n' "$pm_bidi" | grep -q $'^caf\xc3\xa9/\xe6\xa8\xa1\xe5\x9e\x8b-1\t' && pass "parse-models: plain Unicode id (é/CJK) still passes" || fail "parse-models: plain Unicode id over-blocked"

echo
if [[ "$FAILS" -eq 0 ]]; then echo "ALL PASS"; exit 0; fi
echo "$FAILS assertion(s) FAILED" >&2
exit 1
