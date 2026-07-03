#!/usr/bin/env bash
# Purpose: Regression test for the custom-provider fetch seam used by the
#          install-TUI model picker (_setup_custom_provider in
#          scripts/install-tui.sh). Two layers:
#          (1) the plain pipeline: serve an OpenAI-compatible /v1/models JSON
#              over a local HTTP server, then run exactly the
#              curl -H "Authorization: Bearer $KEY" <base>/v1/models
#                | python3 scripts/lib/model-catalog.py parse-models --name <p>
#              command the installer runs, asserting the id<TAB>label rows;
#          (2) the real function: source scripts/install-tui.sh in a subshell
#              (INSTALL_TUI_SCRIPT unset; source-guard stops MAIN) and call
#              _setup_custom_provider directly (Test 2.5 + the confirm-gate
#              tests), shadowing the _have_tty/_ask_yesno seams to drive the
#              headless path and the TTY confirm-before-send prompt.
#          Also asserts the merged (curated + custom) id pool still ranks
#          cleanly through bin/agentic-models (custom ids must not break the
#          picker's primary-first ordering).
#
# Public API: ./bin/tests/test_custom_provider_fetch.sh  (exit 0 pass / 1 fail)
# Upstream deps: bash 3.2+, python3, curl, bin/agentic-models. Localhost only;
#                the API key is a dummy string, never persisted or echoed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
READER="$REPO_DIR/scripts/lib/model-catalog.py"
RANKER="$REPO_DIR/bin/agentic-models"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

TMP="$(mktemp -d)"
SRV_PID=""
cleanup() { [[ -n "$SRV_PID" ]] && kill "$SRV_PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

echo "Test 0: fixtures + local HTTP server"
mkdir -p "$TMP/www/v1"
cat >"$TMP/www/v1/models" <<'JSON'
{"object":"list","data":[{"id":"9r/anthropic/claude-opus-4","object":"model"},{"id":"9r/openai/gpt-5","object":"model"}]}
JSON
# Bind to an ephemeral port (0 = kernel-chosen) and print it, then serve.
# Every request appends "<path>\t<Authorization-or-empty>" to the reqlog file
# (argv[2]) so tests can assert exactly what the client sent on the wire.
cat >"$TMP/serve.py" <<'PY'
import http.server, socketserver, sys, os
os.chdir(sys.argv[1])
REQLOG = sys.argv[2]
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass  # quiet
    def do_GET(self):
        with open(REQLOG, "a") as f:
            f.write("%s\t%s\n" % (self.path, self.headers.get("Authorization", "")))
        return super().do_GET()
with socketserver.TCPServer(("127.0.0.1", 0), H) as httpd:
    print(httpd.server_address[1], flush=True)
    httpd.serve_forever()
PY
python3 "$TMP/serve.py" "$TMP/www" "$TMP/reqlog" >"$TMP/port" 2>/dev/null &
SRV_PID=$!
PORT=""
for _ in $(seq 1 50); do
	PORT="$(cat "$TMP/port" 2>/dev/null || true)"
	[[ -n "$PORT" ]] && break
	sleep 0.1
done
[[ -n "$PORT" ]] && pass "server listening on 127.0.0.1:$PORT" || { fail "server did not start"; echo "1 assertion(s) FAILED" >&2; exit 1; }

echo "Test 1: curl | parse-models emits id<TAB>label rows (the install seam)"
KEY="dummy-not-a-real-key"
out="$(curl -fsS --max-time 10 -H "Authorization: Bearer $KEY" "http://127.0.0.1:$PORT/v1/models" \
	| python3 "$READER" parse-models --name testprov)"
printf '%s\n' "$out" | grep -q $'^9r/anthropic/claude-opus-4\ttestprov: 9r/anthropic/claude-opus-4$' \
	&& pass "opus row from custom provider" || fail "opus row missing: $out"
printf '%s\n' "$out" | grep -q $'^9r/openai/gpt-5\ttestprov: 9r/openai/gpt-5$' \
	&& pass "gpt-5 row from custom provider" || fail "gpt-5 row missing: $out"
[[ "$(printf '%s\n' "$out" | grep -c .)" -eq 2 ]] && pass "exactly 2 custom models" || fail "unexpected row count: $out"

echo "Test 2: trailing-slash base + missing-key cases"
# base with trailing slash normalises to .../v1/models (no double slash)
out2="$(curl -fsS --max-time 10 "http://127.0.0.1:$PORT/v1/models" | python3 "$READER" parse-models --name p)"
printf '%s\n' "$out2" | grep -q $'^9r/openai/gpt-5\t' && pass "unauthenticated fetch works (key optional)" || fail "unauth fetch failed"
# non-JSON endpoint -> parse-models exits 2 (installer falls back to curated)
cat >"$TMP/www/v1/bad" <<'TXT'
not a json document
TXT
set +e
curl -fsS --max-time 10 "http://127.0.0.1:$PORT/v1/bad" | python3 "$READER" parse-models --name p >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -ne 0 ]] && pass "non-JSON response is rejected (rc=$rc)" || fail "non-JSON response was accepted"

echo "Test 2.5: _setup_custom_provider called directly (source-guard path)"
TUI="$REPO_DIR/scripts/install-tui.sh"
# (a) env-driven path with explicit keyvar + trailing-slash base: the function
# must normalize ${base%/}, send the Bearer header, and fill CUSTOM_* arrays.
# Sourced in a subshell with INSTALL_TUI_SCRIPT unset (its preload block would
# exit 1 on an unreadable file); the source-guard stops MAIN from running.
# _have_tty is shadowed to return 1 (headless) so the explicit env keyvar IS
# the consent and no confirm prompt fires, regardless of the test runner's TTY.
# The fixture binds 127.0.0.1 (an internal host by the SSRF denylist), so every
# fixture-fetching subshell sets AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1.
: >"$TMP/reqlog"
out_a="$(
	unset INSTALL_TUI_SCRIPT
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1/"
	export AE_CUSTOM_PROVIDER_KEYVAR=TEST_PROV_KEY
	export TEST_PROV_KEY="dummy-not-a-real-key"
	export AE_CUSTOM_PROVIDER_NAME=testprov
	export AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1
	source "$TUI"
	_have_tty() { return 1; }
	_setup_custom_provider >/dev/null
	printf '%s\n%s\n%s\n' "${#CUSTOM_IDS[@]}" "${CUSTOM_LABELS[0]}" "$CUSTOM_NAME"
)"
count_a="$(printf '%s\n' "$out_a" | sed -n 1p)"
label_a="$(printf '%s\n' "$out_a" | sed -n 2p)"
name_a="$(printf '%s\n' "$out_a" | sed -n 3p)"
[[ "$count_a" -eq 2 ]] && pass "direct call: 2 models in CUSTOM_IDS" || fail "direct call: CUSTOM_IDS count=$count_a (want 2)"
[[ "$label_a" == "testprov: 9r/anthropic/claude-opus-4" ]] && pass "direct call: CUSTOM_LABELS[0] shape" || fail "direct call: CUSTOM_LABELS[0]='$label_a'"
[[ "$name_a" == "testprov" ]] && pass "direct call: CUSTOM_NAME set" || fail "direct call: CUSTOM_NAME='$name_a'"
# Wire-level asserts: the trailing-slash base must normalize to exactly
# /v1/models (not /v1//models), and the explicit keyvar's Bearer must be sent.
req_a="$(tail -n 1 "$TMP/reqlog")"
[[ "${req_a%%$'\t'*}" == "/v1/models" ]] && pass "direct call: request path is /v1/models (no double slash)" \
	|| fail "direct call: request path was '${req_a%%$'\t'*}' (want /v1/models)"
[[ "${req_a#*$'\t'}" == "Bearer dummy-not-a-real-key" ]] && pass "direct call: explicit keyvar sent as Bearer" \
	|| fail "direct call: Authorization was '${req_a#*$'\t'}'"
# (b) no keyvar set -> NO key is read or sent, even when OPENAI_API_KEY exists
# in the environment (regression: the old implicit OPENAI_API_KEY default would
# leak it as a Bearer header here). Fetch must succeed unauthenticated AND the
# server must have received an empty Authorization header.
: >"$TMP/reqlog"
out_b="$(
	unset INSTALL_TUI_SCRIPT
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1"
	export AE_CUSTOM_PROVIDER_NAME=nokey
	export OPENAI_API_KEY="sentinel-not-a-real-key"
	export AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1
	source "$TUI"
	_setup_custom_provider >/dev/null
	printf '%s\n' "${#CUSTOM_IDS[@]}"
)"
[[ "$out_b" -eq 2 ]] && pass "direct call: unauthenticated fetch (no keyvar) works" || fail "direct call: no-keyvar count=$out_b (want 2)"
req_b="$(tail -n 1 "$TMP/reqlog")"
[[ "${req_b#*$'\t'}" == "" ]] && pass "direct call: no keyvar -> no Authorization header (OPENAI_API_KEY not leaked)" \
	|| fail "direct call: leaked Authorization '${req_b#*$'\t'}' without explicit keyvar"

echo "Test 2.6: TTY confirm-before-send gates the key even on the env branch"
# Regression for the env-presence-!=-consent hole: with a (shadowed) TTY
# present, the env-driven branch must still confirm before sending the key.
# (c) decline (_ask_yesno -> 1): fetch proceeds WITHOUT Authorization.
: >"$TMP/reqlog"
out_c="$(
	unset INSTALL_TUI_SCRIPT
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1"
	export AE_CUSTOM_PROVIDER_KEYVAR=SEND_SECRET
	export SEND_SECRET="sentinel-should-not-send"
	export AE_CUSTOM_PROVIDER_NAME=confirmprov
	export AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1
	source "$TUI"
	_have_tty() { return 0; }
	_ask_yesno() { return 1; }
	_setup_custom_provider >/dev/null
	printf '%s\n' "${#CUSTOM_IDS[@]}"
)"
[[ "$out_c" -eq 2 ]] && pass "confirm declined: fetch still works keyless" || fail "confirm declined: count=$out_c (want 2)"
req_c="$(tail -n 1 "$TMP/reqlog")"
[[ "${req_c#*$'\t'}" == "" ]] && pass "confirm declined: NO Authorization header sent" \
	|| fail "confirm declined: key leaked as '${req_c#*$'\t'}'"
# (d) accept (_ask_yesno -> 0): the Bearer IS sent.
: >"$TMP/reqlog"
out_d="$(
	unset INSTALL_TUI_SCRIPT
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1"
	export AE_CUSTOM_PROVIDER_KEYVAR=SEND_SECRET
	export SEND_SECRET="sentinel-should-not-send"
	export AE_CUSTOM_PROVIDER_NAME=confirmprov
	export AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1
	source "$TUI"
	_have_tty() { return 0; }
	_ask_yesno() { return 0; }
	_setup_custom_provider >/dev/null
	printf '%s\n' "${#CUSTOM_IDS[@]}"
)"
[[ "$out_d" -eq 2 ]] && pass "confirm accepted: fetch works" || fail "confirm accepted: count=$out_d (want 2)"
req_d="$(tail -n 1 "$TMP/reqlog")"
[[ "${req_d#*$'\t'}" == "Bearer sentinel-should-not-send" ]] && pass "confirm accepted: Bearer sent" \
	|| fail "confirm accepted: Authorization was '${req_d#*$'\t'}'"

echo "Test 2.7: SSRF denylist refuses internal hosts without the allow override"
# (e) cloud-metadata target WITHOUT AE_CUSTOM_PROVIDER_ALLOW_INTERNAL: must
# return 0 (skip, curated pool still works) with CUSTOM_IDS empty, print the
# refusal message, and make NO network call. Discriminating: removing the
# denylist would let curl attempt 169.254.169.254 and this test would fail
# (no refusal message + nonzero/hung fetch path instead of the clean skip).
: >"$TMP/reqlog"
out_e="$(
	unset INSTALL_TUI_SCRIPT AE_CUSTOM_PROVIDER_ALLOW_INTERNAL
	export AE_CUSTOM_PROVIDER_BASE="http://169.254.169.254/v1"
	export AE_CUSTOM_PROVIDER_NAME=metadata
	source "$TUI"
	_have_tty() { return 1; }
	msg="$(_setup_custom_provider)"; rc=$?
	printf '%s\n%s\n%s\n' "$rc" "${#CUSTOM_IDS[@]}" "$msg"
)"
rc_e="$(printf '%s\n' "$out_e" | sed -n 1p)"
count_e="$(printf '%s\n' "$out_e" | sed -n 2p)"
msg_e="$(printf '%s\n' "$out_e" | sed -n '3,$p')"
[[ "$rc_e" -eq 0 ]] && pass "SSRF refusal: returns 0 (soft skip)" || fail "SSRF refusal: rc=$rc_e (want 0)"
[[ "$count_e" -eq 0 ]] && pass "SSRF refusal: CUSTOM_IDS empty" || fail "SSRF refusal: CUSTOM_IDS count=$count_e (want 0)"
printf '%s\n' "$msg_e" | grep -q "refusing internal/loopback host '169.254.169.254'" \
	&& pass "SSRF refusal: message names the refused host" || fail "SSRF refusal: message was '$msg_e'"
[[ ! -s "$TMP/reqlog" ]] && pass "SSRF refusal: no network request made" || fail "SSRF refusal: fixture was hit: $(cat "$TMP/reqlog")"
# (f) loopback fixture WITHOUT the override is refused too (127.* branch) -
# proves the denylist is on the host regardless of key presence (the keyless
# internal-probe hole is closed by the same gate).
: >"$TMP/reqlog"
out_f="$(
	unset INSTALL_TUI_SCRIPT AE_CUSTOM_PROVIDER_ALLOW_INTERNAL
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1"
	export AE_CUSTOM_PROVIDER_NAME=loop
	source "$TUI"
	_have_tty() { return 1; }
	_setup_custom_provider >/dev/null
	printf '%s\n' "${#CUSTOM_IDS[@]}"
)"
[[ "$out_f" -eq 0 ]] && pass "SSRF refusal: loopback fixture refused without override" \
	|| fail "SSRF refusal: loopback fetched anyway (count=$out_f)"
[[ ! -s "$TMP/reqlog" ]] && pass "SSRF refusal: loopback fixture never hit" || fail "SSRF refusal: loopback fixture was hit"

echo "Test 2.8: argv-safety - key still delivered via curl stdin config (-K -)"
# The key travels as a curl config on stdin, never on argv (CWE-214). The
# behavioral assert: the fixture must STILL receive the exact Bearer header
# end-to-end through the -K - path, including config-syntax metacharacters
# (backslash + double-quote) surviving the escaping.
: >"$TMP/reqlog"
out_g="$(
	unset INSTALL_TUI_SCRIPT
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1"
	export AE_CUSTOM_PROVIDER_KEYVAR=TRICKY_KEY
	export TRICKY_KEY='ab\c"d-not-a-real-key'
	export AE_CUSTOM_PROVIDER_NAME=argvprov
	export AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1
	source "$TUI"
	_have_tty() { return 1; }
	_setup_custom_provider >/dev/null
	printf '%s\n' "${#CUSTOM_IDS[@]}"
)"
[[ "$out_g" -eq 2 ]] && pass "stdin-config fetch works (2 models)" || fail "stdin-config fetch: count=$out_g (want 2)"
req_g="$(tail -n 1 "$TMP/reqlog")"
[[ "${req_g#*$'\t'}" == 'Bearer ab\c"d-not-a-real-key' ]] && pass "Bearer with config metachars survives -K - escaping" \
	|| fail "stdin-config Authorization was '${req_g#*$'\t'}'"

echo "Test 2.9: alt-encoding SSRF bypasses are refused (no override)"
# Each row is a non-canonical respelling of an internal IP that inet_aton /
# the IPv6 parser would happily resolve: bare decimal integer, octal and hex
# dotted octets, IPv4-mapped IPv6, uncompressed IPv6 loopback. Discriminating:
# loopback rows carry the fixture port, so removing the canonicalization lets
# curl fetch the fixture (count=2, no refusal message) and the row fails.
for spec in \
	"http://2130706433:$PORT/v1|2130706433" \
	"http://2852039166/v1|2852039166" \
	"http://0177.0.0.1:$PORT/v1|0177.0.0.1" \
	"http://0x7f.0.0.1:$PORT/v1|0x7f.0.0.1" \
	"http://[::ffff:127.0.0.1]:$PORT/v1|::ffff:127.0.0.1" \
	"http://[0:0:0:0:0:0:0:1]:$PORT/v1|0:0:0:0:0:0:0:1" \
	"http://[::0.0.0.1]:$PORT/v1|::0.0.0.1"; do
	b="${spec%%|*}"; hlabel="${spec#*|}"
	: >"$TMP/reqlog"
	out_h="$(
		unset INSTALL_TUI_SCRIPT AE_CUSTOM_PROVIDER_ALLOW_INTERNAL
		export AE_CUSTOM_PROVIDER_BASE="$b"
		export AE_CUSTOM_PROVIDER_NAME=bypass
		source "$TUI"
		_have_tty() { return 1; }
		msg="$(_setup_custom_provider)"; rc=$?
		printf '%s\n%s\n%s\n' "$rc" "${#CUSTOM_IDS[@]}" "$msg"
	)"
	rc_h="$(printf '%s\n' "$out_h" | sed -n 1p)"
	count_h="$(printf '%s\n' "$out_h" | sed -n 2p)"
	msg_h="$(printf '%s\n' "$out_h" | sed -n '3,$p')"
	if [[ "$rc_h" -eq 0 && "$count_h" -eq 0 && ! -s "$TMP/reqlog" ]] \
		&& printf '%s\n' "$msg_h" | grep -qF "refusing internal/loopback host '$hlabel'"; then
		pass "bypass refused: $b"
	else
		fail "bypass NOT refused: $b (rc=$rc_h count=$count_h msg='$msg_h' reqlog='$(cat "$TMP/reqlog" 2>/dev/null)')"
	fi
done

echo "Test 2.9b: _host_is_internal - embedded-dotted IPv6 refused, hex-named DNS allowed"
# Unit-level rows on the denylist itself. Refuse side: IPv6 literals with an
# embedded dotted-quad tail (curl folds ::0.0.0.1 -> ::1 loopback, ::0.0.0.0 ->
# :: unspecified) must return 0 - fails if the Major-1 dot-strip fix reverts.
# Allow side: real DNS hostnames that merely START with 0x (0x-labs.com,
# api.0x.org) are never IPs to curl and must return nonzero - fails if the
# Major-2 over-broad 0x* glob returns. Real hex/octal/decimal evasion spellings
# stay refused (covered here and end-to-end in Test 2.9).
host_rows="$(
	unset INSTALL_TUI_SCRIPT
	source "$TUI"
	for hh in "::0.0.0.1" "::0.0.0.0" "0:0:0:0:0:0:0.0.0.1" "0x7f000001" "0x7f.0.0.1"; do
		if _host_is_internal "$hh"; then echo "refuse $hh"; else echo "ALLOW $hh"; fi
	done
	for hh in "0x-labs.com" "api.0x.org" "0x.org" "0xproject.com" "0xdeadbeef.io"; do
		if _host_is_internal "$hh"; then echo "REFUSE $hh"; else echo "allow $hh"; fi
	done
)"
for hh in "::0.0.0.1" "::0.0.0.0" "0:0:0:0:0:0:0.0.0.1" "0x7f000001" "0x7f.0.0.1"; do
	printf '%s\n' "$host_rows" | grep -qxF "refuse $hh" \
		&& pass "host refused: $hh" || fail "host NOT refused: $hh"
done
for hh in "0x-labs.com" "api.0x.org" "0x.org" "0xproject.com" "0xdeadbeef.io"; do
	printf '%s\n' "$host_rows" | grep -qxF "allow $hh" \
		&& pass "host allowed (DNS name): $hh" || fail "host WRONGLY refused: $hh"
done

echo "Test 2.10: newline in key is rejected (curl-config directive injection)"
# A key holding a newline would start a new -K - config line (e.g. a rogue
# url = directive). The function must skip WITHOUT sending any request.
# Discriminating: removing the newline check lets the printf emit two config
# lines and curl fetches the fixture (count=2) instead of the clean skip.
: >"$TMP/reqlog"
out_i="$(
	unset INSTALL_TUI_SCRIPT
	export AE_CUSTOM_PROVIDER_BASE="http://127.0.0.1:$PORT/v1"
	export AE_CUSTOM_PROVIDER_KEYVAR=EVIL_KEY
	EVIL_KEY="$(printf 'abc\nurl = "http://127.0.0.1:%s/v1/models"' "$PORT")"
	export EVIL_KEY
	export AE_CUSTOM_PROVIDER_NAME=evil
	export AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1
	source "$TUI"
	_have_tty() { return 1; }
	msg="$(_setup_custom_provider)"; rc=$?
	printf '%s\n%s\n%s\n' "$rc" "${#CUSTOM_IDS[@]}" "$msg"
)"
rc_i="$(printf '%s\n' "$out_i" | sed -n 1p)"
count_i="$(printf '%s\n' "$out_i" | sed -n 2p)"
msg_i="$(printf '%s\n' "$out_i" | sed -n '3,$p')"
[[ "$rc_i" -eq 0 && "$count_i" -eq 0 ]] && pass "newline key: soft skip, CUSTOM_IDS empty" \
	|| fail "newline key: rc=$rc_i count=$count_i (want 0/0)"
printf '%s\n' "$msg_i" | grep -q "contains a newline" && pass "newline key: rejection message printed" \
	|| fail "newline key: message was '$msg_i'"
[[ ! -s "$TMP/reqlog" ]] && pass "newline key: no request sent" || fail "newline key: fixture was hit"

echo "Test 3: merged curated + custom pool still ranks through agentic-models"
curated="$(python3 "$READER" ids)"
merged="$(printf '%s\n%s\n%s\n' "$curated" "9r/anthropic/claude-opus-4" "9r/openai/gpt-5")"
primary="$(printf '%s\n' "$merged" | python3 "$RANKER" --suggest skeptic 2>/dev/null)"
[[ -n "$primary" && "$primary" != "(no match)" ]] && pass "skeptic primary resolves on merged pool: $primary" \
	|| fail "skeptic primary broke on merged pool: $primary"
printf '%s\n' "$merged" | grep -qx "$primary" && pass "primary is a member of the merged pool" \
	|| fail "primary '$primary' not in merged pool"

echo
if [[ "$FAILS" -eq 0 ]]; then echo "ALL PASS"; exit 0; fi
echo "$FAILS assertion(s) FAILED" >&2
exit 1
