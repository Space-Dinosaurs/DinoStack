#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Module Manifest
#
# Purpose: Pure-bash, zero-dependency interactive installer (TUI) for
#          agentic-engineering. Walks the operator through harness selection,
#          mode/tier, optional team/model assignment, and optional per-tenant
#          profiles, then invokes each selected adapter's install.sh with the
#          composed flags. It COMPOSES adapter flags; it never re-implements
#          adapter install logic or team.yml writing.
#
# Public API:
#   ./scripts/install-tui.sh [--no-tui] [--reconfigure]
#     Interactive mode (default) when: /dev/tty readable AND stdout is a TTY
#     AND --no-tui absent AND INSTALL_TUI_SCRIPT unset. --reconfigure forces
#     re-prompting when the per-harness config already exists (ask-once gate).
#   INSTALL_TUI_SCRIPT=<file> ./scripts/install-tui.sh
#     Scripted mode for CI: <file> holds newline-separated pre-answers (format
#     below); drives the SAME code paths deterministically, no /dev/tty needed.
#   DRY_RUN=1 ...
#     Print the composed `install.sh` command lines instead of executing them.
#
# Exit codes:
#   0  = TUI ran; all selected adapters installed OK (or DRY_RUN print).
#   1  = TUI ran; one or more adapters failed.
#   75 = fall-through marker (conditions not met / --no-tui): the caller
#        should continue its normal flag-based install flow. Nothing printed.
#
# Scripted answer-file format (one answer per non-comment line, in order):
#   1. harnesses   : space/comma list of labels, or the word `detected`
#   2. mode        : dormant | resident
#   3. tier        : minimal | medium | full
#   4. team        : `skip`, or `default=<h>` and/or `role=harness[:model],...`
#                    e.g. `default=claude;engineer=codex,skeptic=gemini:pro`
#   5. profiles    : `skip`, or space/comma tenant names
#   6. tools       : `skip`, or space/comma subset of:
#                    gh agent-browser lc jira rclone   (claude adapter only)
#   7. mcps        : `skip`, or space/comma subset of:
#                    chrome-devtools mcp-atlassian     (claude adapter only)
#   8. permissions : `skip` | `bypass`                  (claude adapter only)
#   9. confirm     : yes | no
#   Blank lines and lines beginning with `#` are ignored. Trailing optional
#   answers may be omitted: a drained queue reads as empty, which maps tools/
#   mcps to `skip` and permissions to `skip`. Only `confirm` (line 9) actually
#   runs the plan; omitting it cancels (safe default).
#   Legacy 6-line format (pre-tools: harnesses mode tier team profiles
#   confirm) is still accepted with a stderr deprecation warning: when line 6
#   is a yes/no token AND the queue drains right after it is popped, it is
#   treated as the confirm answer and tools/mcps/permissions default to skip.
#
# Upstream deps: bash 3.2+ (macOS system bash) or newer; the per-adapter
#   .<harness>/install.sh scripts; bin/agentic-team (for team config only).
#   No associative arrays, no ${var,,} - parallel indexed arrays + tr, so it
#   runs on macOS bash 3.2 and Linux alike. All interactive I/O is on /dev/tty
#   (survives `curl | bash` piped stdin, same rationale as ae_confirm).
#
# Failure modes: continue-on-error across adapters; failures collected and
#   surfaced in a final summary; exit 1 if any failed. Unknown-to-adapter
#   flags are never sent - each flag is grep-probed in the target script
#   before composition, so an adapter that has not yet grown --tier/--dormant/
#   --config-dir simply does not receive it.
# =============================================================================

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Harness registry - parallel indexed arrays (bash 3.2: no associative arrays).
# label -> adapter dir (.<label>) and detection binary (command -v <bin>).
# Binary names verified against bin/agentic-team HARNESS_BINARY; cursor's CLI
# is `cursor-agent`, kimi's is `kimi-cli`.
# ---------------------------------------------------------------------------
H_LABELS=(claude codex cursor gemini kimi opencode pi omp hermes openclaw copilot)
H_BINS=(claude codex cursor-agent gemini kimi-cli opencode pi omp hermes openclaw copilot)
H_COUNT=${#H_LABELS[@]}

# Adapter label -> dispatchable harness name (bin/_role_spec KNOWN_HARNESSES).
# The adapter-install label space (above) is a SUPERSET of the team-dispatchable
# harness space: `cursor` installs the `cursor-agent` CLI, and `hermes`/`openclaw`
# are installable adapters with no worker-dispatch support in bin/agentic-team.
# Screen 3 assignments must be expressed in dispatchable names or agentic-team
# silently drops them (its --assign validates against KNOWN_HARNESSES). Empty
# string = installable but NOT team-dispatchable.
team_harness_for_label() {
	case "$1" in
	cursor)            printf 'cursor-agent' ;;   # adapter label -> CLI/dispatch name
	hermes|openclaw)   printf '' ;;               # installable, not dispatchable
	*)                 printf '%s' "$1" ;;         # claude/codex/gemini/kimi/opencode/pi/omp/copilot
	esac
}

adapter_dir()  { printf '%s/.%s' "$REPO_DIR" "$1"; }
adapter_script(){ printf '%s/.%s/install.sh' "$REPO_DIR" "$1"; }

# grep-probe: does the target install.sh advertise this flag token?
script_supports() {
	local script="$1" flag="$2"
	[[ -f "$script" ]] && grep -q -- "$flag" "$script"
}

# ---------------------------------------------------------------------------
# Answer source: interactive (/dev/tty) vs scripted (INSTALL_TUI_SCRIPT queue).
# In scripted mode we preload non-comment lines into a FIFO array and pop.
# ---------------------------------------------------------------------------
SCRIPTED=false
ANSWERS=()
ANSWER_IDX=0
if [[ -n "${INSTALL_TUI_SCRIPT:-}" ]]; then
	SCRIPTED=true
	if [[ ! -r "$INSTALL_TUI_SCRIPT" ]]; then
		echo "install-tui: INSTALL_TUI_SCRIPT not readable: $INSTALL_TUI_SCRIPT" >&2
		exit 1
	fi
	while IFS= read -r _line || [[ -n "$_line" ]]; do
		case "$_line" in
		'#'*) continue ;;
		'') continue ;;
		esac
		ANSWERS+=("$_line")
	done <"$INSTALL_TUI_SCRIPT"
fi

# Pop the next scripted answer into global ANSWER (empty when queue drained).
# Returns via a global, NOT stdout: callers invoke it directly (never in a
# $(...) subshell) so the ANSWER_IDX advance survives in the parent shell.
ANSWER=""
REPLY_VAL=""
next_answer() {
	ANSWER=""
	if [[ "$ANSWER_IDX" -lt "${#ANSWERS[@]}" ]]; then
		ANSWER="${ANSWERS[$ANSWER_IDX]}"
		ANSWER_IDX=$((ANSWER_IDX + 1))
	fi
}

# ---------------------------------------------------------------------------
# Entry gate. Return 0 => run (interactive or scripted); 1 => fall through.
# ---------------------------------------------------------------------------
NO_TUI=false
# --reconfigure bypasses the already-configured gate below (fresh answers).
RECONFIGURE=false
for arg in "$@"; do
	[[ "$arg" == "--no-tui" ]] && NO_TUI=true
	[[ "$arg" == "--reconfigure" ]] && RECONFIGURE=true
done

should_run() {
	$NO_TUI && return 1
	$SCRIPTED && return 0
	[[ -r /dev/tty && -t 1 ]]
}

# ===========================================================================
# Interactive primitives (ANSI, /dev/tty). Only used when !SCRIPTED.
# ===========================================================================
ESC=$'\033'
_hide_cursor() { printf '%s[?25l' "$ESC" >/dev/tty; }
_show_cursor() { printf '%s[?25h' "$ESC" >/dev/tty; }
_clear()       { printf '%s[2J%s[H' "$ESC" "$ESC" >/dev/tty; }

# Read one key from /dev/tty, echo a token: UP DOWN SPACE ENTER QUIT OTHER.
# Arrow keys arrive as ESC [ A/B; a bare byte otherwise. bash 3.2-safe reads.
read_key() {
	local k rest
	IFS= read -rsn1 k </dev/tty || { printf 'QUIT'; return; }
	case "$k" in
	"$ESC")
		IFS= read -rsn2 rest </dev/tty 2>/dev/null || rest=""
		case "$rest" in
		'[A') printf 'UP' ;;
		'[B') printf 'DOWN' ;;
		*) printf 'OTHER' ;;
		esac
		;;
	'') printf 'ENTER' ;;
	' ') printf 'SPACE' ;;
	k | K) printf 'UP' ;;
	j | J) printf 'DOWN' ;;
	q | Q) printf 'QUIT' ;;
	*) printf 'OTHER' ;;
	esac
}

# ---------------------------------------------------------------------------
# _ask_multiselect: choose any subset of N labelled options.
#   $1 title; then triples: label, annotation, preselect(0/1) x N.
# Sets global reply array SELECTED=(labels...).
# Scripted: consumes one answer line (space/comma labels, or `detected`).
# ---------------------------------------------------------------------------
SELECTED=()
_ask_multiselect() {
	local title="$1"; shift
	local labels=() annos=() state=()
	while [[ $# -ge 3 ]]; do
		labels+=("$1"); annos+=("$2"); state+=("$3"); shift 3
	done
	local n=${#labels[@]}

	if $SCRIPTED; then
		next_answer; local ans="$ANSWER"
		SELECTED=()
		if [[ "$ans" == "detected" ]]; then
			local i
			for ((i = 0; i < n; i++)); do
				[[ "${state[$i]}" == "1" ]] && SELECTED+=("${labels[$i]}")
			done
		else
			local tok i found
			for tok in ${ans//,/ }; do
				found=0
				for ((i = 0; i < n; i++)); do
					[[ "$tok" == "${labels[$i]}" ]] && { found=1; break; }
				done
				if [[ "$found" == "1" ]]; then
					SELECTED+=("$tok")
				else
					echo "install-tui: unknown harness label '$tok' in scripted answer; skipping" >&2
				fi
			done
		fi
		return
	fi

	local cur=0 key i
	_hide_cursor
	trap '_show_cursor' RETURN
	while true; do
		_clear
		{
			printf '%s\n\n' "$title"
			printf '  up/down move  space toggle  enter confirm  q cancel\n\n'
			for ((i = 0; i < n; i++)); do
				local mark=" "; [[ "${state[$i]}" == "1" ]] && mark="x"
				local ptr="  "; [[ "$i" -eq "$cur" ]] && ptr="> "
				if [[ "$i" -eq "$cur" ]]; then printf '%s[7m' "$ESC"; fi
				printf '%s[%s] %s%s%s[0m\n' "$ptr" "$mark" "${labels[$i]}" "${annos[$i]}" "$ESC"
			done
		} >/dev/tty
		key="$(read_key)"
		case "$key" in
		UP)   cur=$(((cur - 1 + n) % n)) ;;
		DOWN) cur=$(((cur + 1) % n)) ;;
		SPACE)
			if [[ "${state[$cur]}" == "1" ]]; then state[$cur]=0; else state[$cur]=1; fi
			;;
		ENTER)
			SELECTED=()
			for ((i = 0; i < n; i++)); do
				[[ "${state[$i]}" == "1" ]] && SELECTED+=("${labels[$i]}")
			done
			break
			;;
		QUIT) SELECTED=(); break ;;
		esac
	done
	_clear
}

# ---------------------------------------------------------------------------
# _ask_single: pick exactly one of the given values. Echoes the choice.
#   $1 title; rest: values (first is the default/highlighted).
# Scripted: consumes one answer line; validated against values, else default.
# ---------------------------------------------------------------------------
_ask_single() {
	local title="$1"; shift
	local values=("$@") n=${#@} i
	if $SCRIPTED; then
		next_answer; local ans="$ANSWER"
		for ((i = 1; i <= n; i++)); do
			[[ "$ans" == "${!i}" ]] && { REPLY_VAL="$ans"; return; }
		done
		REPLY_VAL="${values[0]}"
		return
	fi
	local cur=0 key
	_hide_cursor
	trap '_show_cursor' RETURN
	while true; do
		_clear
		{
			printf '%s\n\n' "$title"
			printf '  up/down move  enter select\n\n'
			for ((i = 0; i < n; i++)); do
				local ptr="  "; [[ "$i" -eq "$cur" ]] && ptr="> "
				if [[ "$i" -eq "$cur" ]]; then printf '%s[7m' "$ESC"; fi
				printf '%s%s%s[0m\n' "$ptr" "${values[$i]}" "$ESC"
			done
		} >/dev/tty
		key="$(read_key)"
		case "$key" in
		UP)   cur=$(((cur - 1 + n) % n)) ;;
		DOWN) cur=$(((cur + 1) % n)) ;;
		ENTER) break ;;
		QUIT) cur=0; break ;;
		esac
	done
	_clear
	REPLY_VAL="${values[$cur]}"
}

# ---------------------------------------------------------------------------
# _ask_text: free-text prompt (empty allowed). Echoes the entered line.
# Scripted: consumes one answer line.
# ---------------------------------------------------------------------------
_ask_text() {
	local prompt="$1"
	if $SCRIPTED; then next_answer; REPLY_VAL="$ANSWER"; return; fi
	local line=""
	printf '%s' "$prompt" >/dev/tty
	IFS= read -r line </dev/tty || line=""
	REPLY_VAL="$line"
}

# ---------------------------------------------------------------------------
# _ask_yesno: y/N confirm. Returns 0 for yes, 1 for no.
# Scripted: consumes one answer line (yes/y => 0).
# ---------------------------------------------------------------------------
_ask_yesno() {
	local prompt="$1"
	if $SCRIPTED; then
		next_answer; local ans; ans="$(printf '%s' "$ANSWER" | tr 'A-Z' 'a-z')"
		[[ "$ans" == "yes" || "$ans" == "y" ]]
		return
	fi
	local reply=""
	printf '%s' "$prompt" >/dev/tty
	IFS= read -rn1 reply </dev/tty || reply=""
	printf '\n' >/dev/tty
	[[ "$reply" =~ ^[Yy]$ ]]
}

# _have_tty: a real controlling terminal is present (same /dev/tty convention
# as should_run). Tiny seam so tests can shadow TTY presence.
_have_tty() { [[ -r /dev/tty ]]; }

# _host_is_internal HOST: 0 when HOST targets loopback / link-local / private /
# unspecified space (SSRF denylist for the custom-provider fetch, CWE-918);
# 1 for anything else. Conservative glob matching (bash 3.2 - no PCRE): a
# hostname that merely LOOKS like a private prefix (e.g. 10.example.com) is
# also refused - fail-closed, and AE_CUSTOM_PROVIDER_ALLOW_INTERNAL overrides.
# Alt-encoding hardening: inet_aton accepts many respellings of the same IP
# (bare integer 2130706433, octal 0177.0.0.1, hex 0x7f.0.0.1, 2/3-part
# shorthand 127.1), and IPv6 has mapped (::ffff:a.b.c.d) and uncompressed
# (0:0:0:0:0:0:0:1) forms - only the canonical dotted-quad / compressed
# shapes pass through to the prefix rules; every other numeric respelling is
# refused outright (its only purpose in a provider URL is evasion).
# Expects a bare host (no scheme/port/brackets - caller strips those).
_host_is_internal() {
	local h; h="$(printf '%s' "$1" | tr 'A-Z' 'a-z')"
	[[ -n "$h" ]] || return 0
	case "$h" in
		*:*) # IPv6 literal (caller strips brackets/port; hostnames never hold ':')
			case "$h" in
				# IPv4-mapped (::ffff:a.b.c.d): apply the IPv4 rules to the
				# dotted remainder; hex-group mapped forms (::ffff:7f00:1) are
				# refused as non-canonical evasion shapes.
				::ffff:*.*) _host_is_internal "${h#::ffff:}"; return ;;
				::ffff:*) return 0 ;;
			esac
			# Embedded dotted-quad in any non-mapped IPv6 form (::0.0.0.1,
			# 0:0:0:0:0:0:0.0.0.1, ::127.0.0.1): inet_pton folds the dotted
			# tail into the low hex groups (::0.0.0.1 == ::1, loopback), so
			# every such literal is a non-canonical evasion shape - refuse.
			# The only legitimate dotted IPv6 form, ::ffff:a.b.c.d, was
			# already routed through the IPv4 rules above.
			case "$h" in
				*.*) return 0 ;;
			esac
			# Any spelling of the unspecified/loopback address (::, ::1, 0::1,
			# 0:0:0:0:0:0:0:1, ...): drop every '0' and ':'; empty remainder is
			# the unspecified address, exactly "1" is loopback.
			local z="${h//0/}"; z="${z//:/}"
			[[ -z "$z" || "$z" == "1" ]] && return 0
			case "$h" in
				fe8*|fe9*|fea*|feb*) return 0 ;;             # link-local fe80::/10
				fc*|fd*) return 0 ;;                         # ULA fc00::/7
				ff*) return 0 ;;                             # multicast ff00::/8
				100*) return 0 ;;                            # discard prefix 100::/64 (RFC 6666)
			esac
			return 1 ;;
	esac
	# Hex alt-encoded IPv4 (inet_aton evasion): only a host made ENTIRELY of
	# hex digits, 'x', and dots can be an alternative spelling of an IP; any
	# other char (hyphen, g-z, ...) makes it a DNS name to curl, never an IP
	# (0x-labs.com, api.0x.org, 0xproject.com stay reachable). For a
	# candidate, refuse when every dot-label is a valid inet_aton token
	# (all-decimal/octal digits, or 0x-prefixed hex - bare "0x" parses as 0);
	# the all-digit spellings are vetted by the numeric block below.
	case "$h" in
		*[!0-9a-fx.]*) : ;;  # non-hex char present: a DNS name, fall through
		*x*)
			local hrest="$h" lab evasion=1
			while :; do
				lab="${hrest%%.*}"
				case "$lab" in
					0x) : ;;                       # inet_aton: "0x" == 0
					0x*[!0-9a-f]*) evasion=0 ;;    # stray 'x' after prefix
					0x*) : ;;                      # valid hex octet/dword
					''|*[!0-9]*) evasion=0 ;;      # empty, or hex chars w/o 0x
				esac
				[[ "$hrest" == *.* ]] || break
				hrest="${hrest#*.}"
			done
			[[ "$evasion" -eq 1 ]] && return 0 ;;
	esac
	# Purely numeric host (digits and dots only): only canonical dotted-quad
	# (exactly 4 octets, each 0-255, no leading zeros) may reach the prefix
	# rules; bare integers, 2/3-part shorthands, and 0-leading octal octets
	# are refused as respellings of arbitrary IPs.
	case "$h" in
		*[!0-9.]*) : ;;  # has non-numeric chars: a hostname, fall through
		*)
			local rest="$h" oct n=0
			while :; do
				oct="${rest%%.*}"
				case "$oct" in
					'' | 0[0-9]*) return 0 ;;  # empty octet / octal spelling
				esac
				[[ "${#oct}" -le 3 && "$oct" -le 255 ]] || return 0
				n=$((n + 1))
				[[ "$rest" == *.* ]] || break
				rest="${rest#*.}"
			done
			[[ "$n" -eq 4 ]] || return 0 ;;
	esac
	case "$h" in
		localhost|localhost.*|*.localhost) return 0 ;;      # loopback names
		127.*|0.0.0.0|0.*) return 0 ;;                      # 127/8, 0/8
		10.*|192.168.*) return 0 ;;                         # RFC1918
		172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;  # 172.16/12
		169.254.*) return 0 ;;                              # link-local (cloud metadata)
		100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*) return 0 ;;  # CGNAT 100.64/10
		192.0.0.*) return 0 ;;                              # IETF assignments 192.0.0.0/24
		22[4-9].*|23[0-9].*) return 0 ;;                    # multicast 224.0.0.0/4
	esac
	return 1
}

# _resolve_host_ips HOST: print every IP HOST resolves to, one per line;
# return 1 when resolution fails or yields nothing. Resolver order honors the
# AE_TEST_FAKE_RESOLVE seam first (comma-separated host=ip pairs, tests only;
# an explicit host= with empty ip forces failure), then OS resolvers in
# availability order, each guarded by command -v. Fail-closed: callers treat
# an unresolvable host as a refusal (an NXDOMAIN that later resolves - DNS
# rebinding, CWE-350 - must not slip past the SSRF gate).
_resolve_host_ips() {
	local h="$1" fake pair ips
	fake="${AE_TEST_FAKE_RESOLVE:-}"
	if [[ -n "$fake" ]]; then
		while :; do
			pair="${fake%%,*}"
			case "$pair" in
				"$h"=*)
					ips="${pair#*=}"
					[[ -n "$ips" ]] && printf '%s\n' "$ips" && return 0
					return 1 ;;
			esac
			[[ "$fake" == *,* ]] || break
			fake="${fake#*,}"
		done
	fi
	if command -v getent >/dev/null 2>&1; then
		ips="$(getent hosts "$h" 2>/dev/null | awk '{print $1}' | sort -u || true)"
		[[ -n "$ips" ]] && { printf '%s\n' "$ips"; return 0; }
	fi
	if command -v dscacheutil >/dev/null 2>&1; then
		ips="$(dscacheutil -q host -a name "$h" 2>/dev/null \
			| awk '/^(ip_address|ipv6_address):/{print $2}' | sort -u || true)"
		[[ -n "$ips" ]] && { printf '%s\n' "$ips"; return 0; }
	fi
	if command -v host >/dev/null 2>&1; then
		ips="$( { host -t a "$h"; host -t aaaa "$h"; } 2>/dev/null \
			| awk '/address/{print $NF}' | sort -u || true)"
		[[ -n "$ips" ]] && { printf '%s\n' "$ips"; return 0; }
	fi
	if command -v dig >/dev/null 2>&1; then
		ips="$( { dig +short a "$h"; dig +short aaaa "$h"; } 2>/dev/null \
			| grep -E '^[0-9a-fA-F:.]+$' | sort -u || true)"
		[[ -n "$ips" ]] && { printf '%s\n' "$ips"; return 0; }
	fi
	if command -v python3 >/dev/null 2>&1; then
		ips="$(python3 -c 'import socket,sys
try:
	for r in socket.getaddrinfo(sys.argv[1], None):
		print(r[4][0])
except OSError:
	sys.exit(1)' "$h" 2>/dev/null | sort -u || true)"
		[[ -n "$ips" ]] && { printf '%s\n' "$ips"; return 0; }
	fi
	return 1
}

# _host_resolves_internal HOST: 0 when HOST resolves to any internal address
# (refuse), 1 when every answer is external. IP literals are skipped - the
# lexical gate (_host_is_internal) already owns them. Sets the global
# _RESOLVED_IP to the first answer so the caller can pin the fetch to the
# vetted IP (DNS-rebinding / TOCTOU defense, CWE-367). Unresolvable hosts are
# refused: a name that answers nothing now but an internal IP at fetch time is
# the rebinding attack this gate exists to stop.
_RESOLVED_IP=""
_host_resolves_internal() {
	local h="$1" ips ip stripped
	case "$h" in *:*) return 1 ;; esac   # IPv6 literal: lexical gate owns it
	stripped="${h//[0-9]/}"; stripped="${stripped//./}"
	if [[ -z "$stripped" && "$h" == *.* ]]; then
		return 1                          # IPv4 literal: lexical gate owns it
	fi
	_RESOLVED_IP=""
	if ! ips="$(_resolve_host_ips "$h")"; then
		echo "  ! custom provider: cannot resolve host '$h' - refusing (fail-closed)"
		return 0
	fi
	while IFS= read -r ip; do
		[[ -n "$ip" ]] || continue
		if _host_is_internal "$ip"; then
			echo "  ! custom provider: host '$h' resolves to internal address '$ip' - refusing"
			return 0
		fi
		if [[ -z "$_RESOLVED_IP" ]]; then
			_RESOLVED_IP="$ip"
		fi
	done <<<"$ips"
	if [[ -n "$_RESOLVED_IP" ]]; then
		return 1
	fi
	echo "  ! custom provider: cannot resolve host '$h' - refusing (fail-closed)"
	return 0
}

# ---------------------------------------------------------------------------
# Model suggestion pool (curated, offline) helpers for the Screen-3 picker.
# Backed by scripts/lib/model-catalog.json via scripts/lib/model-catalog.py;
# optional primary-first ordering via bin/agentic-models ranking. All globals
# (bash 3.2: no associative arrays) - parallel indexed arrays id <-> label.
# Interactive-only: the scripted (INSTALL_TUI_SCRIPT) path never calls these.
# ---------------------------------------------------------------------------
CATALOG_IDS=()
CATALOG_LABELS=()
# Custom OpenAI-compatible provider pool (populated by _setup_custom_provider).
# Merged into CATALOG_* by _catalog_load so user-supplied gateways (9Router,
# LiteLLM, any OpenAI-shaped /v1/models) rank alongside the curated suggestions.
# The API key is never stored here - it is read from a named env var for one
# fetch and discarded.
CUSTOM_IDS=()
CUSTOM_LABELS=()
CUSTOM_NAME=""

# _setup_custom_provider: optionally fetch models from a user-supplied
# OpenAI-compatible endpoint and fill CUSTOM_IDS/CUSTOM_LABELS/CUSTOM_NAME.
#   Non-interactive / tests: set AE_CUSTOM_PROVIDER_BASE (+ optional
#     AE_CUSTOM_PROVIDER_KEYVAR - unset means no key is read or sent;
#     AE_CUSTOM_PROVIDER_NAME, default "custom"). The key is read via indirect
#     expansion of the env-var NAME and sent only as an Authorization header -
#     never echoed or persisted. In a true headless run (no /dev/tty) the
#     explicit keyvar IS the consent to send it - there is no human to ask.
#   Interactive: prompts for display name, base URL, and the key env-var name
#     (blank = none, no implicit default).
#   Whenever a real controlling TTY is present - regardless of which branch
#     set the base (env vars can arrive via inherited env, .envrc,
#     devcontainer, or a postinstall without the human's knowledge) - the key
#     send is confirmed via _ask_yesno before any request goes out.
# Every failure path warns and returns so the curated pool still works.
_setup_custom_provider() {
	CUSTOM_IDS=(); CUSTOM_LABELS=(); CUSTOM_NAME=""
	local base="" keyvar="" name="" key=""
	if [[ -n "${AE_CUSTOM_PROVIDER_BASE:-}" ]]; then
		base="$AE_CUSTOM_PROVIDER_BASE"
		keyvar="${AE_CUSTOM_PROVIDER_KEYVAR:-}"
		name="${AE_CUSTOM_PROVIDER_NAME:-custom}"
	elif $SCRIPTED; then
		return 0
	else
		_ask_yesno "Add a custom OpenAI-compatible provider (e.g. 9Router, LiteLLM)? [y/N] " || return 0
		_ask_text "  provider display name [custom]: "; name="${REPLY_VAL:-custom}"
		_ask_text "  base URL (e.g. http://127.0.0.1:9000/v1): "; base="$REPLY_VAL"
		_ask_text "  API-key env var name (blank = none): "; keyvar="${REPLY_VAL:-}"
	fi
	[[ -n "$base" ]] || { echo "  ! custom provider: no base URL - skipping"; return 0; }
	command -v curl >/dev/null 2>&1 || { echo "  ! custom provider: curl not found - skipping"; return 0; }
	key=""; [[ -n "$keyvar" ]] && key="${!keyvar:-}"
	local url="${base%/}/models"
	# SSRF denylist (CWE-918): $base can arrive via inherited env / .envrc /
	# postinstall, so an attacker-influenced value could steer this fetch at
	# cloud metadata (169.254.169.254), localhost services, or RFC1918 hosts.
	# Refuse internal targets unless explicitly overridden (same truthiness
	# style as ae_noninteractive; localhost gateways like LiteLLM set it).
	local host="$url"
	host="${host#*://}"; host="${host%%/*}"      # scheme://HOST[:port]/... -> HOST[:port]
	host="${host#*@}"                             # strip userinfo
	local port=""
	case "$host" in
		\[*\]*:*) port="${host##*:}"; host="${host#\[}"; host="${host%%\]*}" ;;  # [v6]:port -> v6 + port
		\[*\]*) host="${host#\[}"; host="${host%%\]*}" ;;                        # [v6] -> v6
		*:*) port="${host#*:}"; host="${host%%:*}" ;;                                # host:port -> host + port
	esac
	_RESOLVED_IP=""
	case "${AE_CUSTOM_PROVIDER_ALLOW_INTERNAL:-}" in
		""|0|false|no)
			if _host_is_internal "$host"; then
				echo "  ! custom provider: refusing internal/loopback host '$host' (set AE_CUSTOM_PROVIDER_ALLOW_INTERNAL=1 to allow) - skipping"
				return 0
			fi
			# DNS gate: a hostname passing the lexical denylist can still resolve
			# to an internal IP (attacker DNS, /etc/hosts, split-horizon). Vet
			# every answer and pin the fetch to the first vetted IP below, so a
			# re-resolution between check and connect (DNS rebinding / TOCTOU,
			# CWE-367) cannot redirect the request at an internal target.
			if _host_resolves_internal "$host"; then
				return 0
			fi ;;
	esac
	# Confirm before sending the key whenever a real controlling TTY exists,
	# independent of which branch set $base: env-presence is not consent for an
	# interactive human (AE_CUSTOM_PROVIDER_* may be inherited silently). A true
	# headless run (no /dev/tty) sends per explicit env-keyvar consent - there
	# is no human to ask. Only the env-var NAME is echoed - never the key value.
	if [[ -n "$key" ]] && _have_tty; then
		if ! _ask_yesno "  Send \$$keyvar as Bearer to $url? [y/N] "; then
			key=""
			echo "  - fetching without Authorization header"
		fi
	fi
	# TOCTOU pin (CWE-367): when the DNS gate vetted an answer, force curl to
	# connect to exactly that IP for this host - a second lookup returning an
	# internal address between the check above and the connect cannot redirect
	# the fetch. Empty when the host is an IP literal or the allow-override
	# skipped the gate (the lexical denylist already owns those paths).
	local pin=()
	if [[ -n "$_RESOLVED_IP" ]]; then
		if [[ -z "$port" ]]; then
			case "$url" in http://*) port=80 ;; *) port=443 ;; esac
		fi
		pin=(--resolve "$host:$port:$_RESOLVED_IP")
	fi
	local tmp; tmp="$(mktemp)" || { echo "  ! custom provider: mktemp failed - skipping"; return 0; }
	if [[ -n "$key" ]]; then
		# Key must never appear on argv (CWE-214: ps / /proc/<pid>/cmdline leak
		# to other local users). Feed the header via a curl config on stdin
		# (-K -): visible in neither argv nor on disk. Escape backslash and
		# double-quote for curl config syntax. A newline/CR in the key would
		# start a new config line (directive injection) - reject outright.
		case "$key" in *$'\n'*|*$'\r'*)
			echo "  ! custom provider: API key in \$$keyvar contains a newline - skipping"
			rm -f "$tmp"; return 0 ;;
		esac
		local esc="${key//\\/\\\\}"; esc="${esc//\"/\\\"}"
		if ! printf 'header = "Authorization: Bearer %s"\n' "$esc" \
			| curl -fsS --max-time 15 --max-filesize 1048576 --proto '=http,https' ${pin[@]+"${pin[@]}"} -K - "$url" -o "$tmp" 2>/dev/null; then
			echo "  ! custom provider: fetch failed ($url) - skipping"
			rm -f "$tmp"; return 0
		fi
	else
		if ! curl -fsS --max-time 15 --max-filesize 1048576 --proto '=http,https' ${pin[@]+"${pin[@]}"} "$url" -o "$tmp" 2>/dev/null; then
			echo "  ! custom provider: fetch failed ($url) - skipping"
			rm -f "$tmp"; return 0
		fi
	fi
	# Defense-in-depth size cap: curl <8.4 does not enforce --max-filesize on
	# chunked (no Content-Length) responses, so re-check the bytes on disk.
	if [[ "$(wc -c <"$tmp" 2>/dev/null || echo 0)" -gt 1048576 ]]; then
		echo "  ! custom provider: response too large - skipping"
		rm -f "$tmp"; return 0
	fi
	local reader="$REPO_DIR/scripts/lib/model-catalog.py"
	local parsed
	if ! parsed="$(python3 "$reader" parse-models --name "$name" <"$tmp" 2>/dev/null)"; then
		echo "  ! custom provider: response was not a /v1/models JSON - skipping"
		rm -f "$tmp"; return 0
	fi
	rm -f "$tmp"
	[[ -n "$parsed" ]] || { echo "  ! custom provider: no models returned - skipping"; return 0; }
	CUSTOM_NAME="$name"
	local line id label
	while IFS= read -r line; do
		id="${line%%$'\t'*}"; label="${line#*$'\t'}"
		[[ -n "$id" ]] || continue
		CUSTOM_IDS+=("$id"); CUSTOM_LABELS+=("${label:-$id}")
	done <<<"$parsed"
	echo "  + custom provider '$name': ${#CUSTOM_IDS[@]} model(s) added to the picker"
	return 0
}

_catalog_load() {
	CATALOG_IDS=(); CATALOG_LABELS=()
	local reader="$REPO_DIR/scripts/lib/model-catalog.py"
	[[ -f "$reader" ]] || return 1
	local line id label
	while IFS= read -r line; do
		id="${line%%$'\t'*}"; label="${line#*$'\t'}"
		[[ -n "$id" ]] || continue
		CATALOG_IDS+=("$id"); CATALOG_LABELS+=("${label:-$id}")
	done < <(python3 "$reader" pairs 2>/dev/null)
	# Merge any custom-provider models fetched by _setup_custom_provider so they
	# rank alongside the curated suggestions in _pick_model.
	local ci
	for ((ci = 0; ci < ${#CUSTOM_IDS[@]}; ci++)); do
		CATALOG_IDS+=("${CUSTOM_IDS[$ci]}")
		CATALOG_LABELS+=("${CUSTOM_LABELS[$ci]:-${CUSTOM_IDS[$ci]}}")
	done
	[[ "${#CATALOG_IDS[@]}" -gt 0 ]]
}

_catalog_primary_for_role() {
	# Rank the MERGED pool (curated + custom) for this role. _catalog_load runs
	# first in _pick_model, so CATALOG_IDS already holds the full set.
	local role="$1" ranker="$REPO_DIR/bin/agentic-models"
	[[ -f "$ranker" ]] || return 1
	[[ "${#CATALOG_IDS[@]}" -gt 0 ]] || return 1
	local primary
	primary="$(printf '%s\n' "${CATALOG_IDS[@]}" | python3 "$ranker" --suggest "$role" 2>/dev/null)" || return 1
	[[ "$primary" != "(no match)" && -n "$primary" ]] || return 1
	printf '%s\n' "$primary"
}

# _pick_model <role>: sets PICKED_MODEL to the chosen id ("" = harness default).
PICKED_MODEL=""
_pick_model() {
	local role="$1"
	PICKED_MODEL=""
	if ! _catalog_load; then
		_ask_text "  model id for $role (blank = harness default): "
		PICKED_MODEL="$REPLY_VAL"; return
	fi
	local primary; primary="$(_catalog_primary_for_role "$role" 2>/dev/null || true)"
	# Parallel arrays: values[i] is the displayed label, value_tags[i] is the
	# exact model id it maps to. Index-matched lookup after _ask_single avoids
	# parsing the id back out of the label (an id containing "[" would break
	# bracket-stripping - see DS install-tui F3).
	local values=() value_tags=() i n=${#CATALOG_IDS[@]}
	if [[ -n "$primary" ]]; then
		for ((i = 0; i < n; i++)); do
			if [[ "${CATALOG_IDS[$i]}" == "$primary" ]]; then
				values+=("${CATALOG_LABELS[$i]}  [${CATALOG_IDS[$i]}] (suggested)")
				value_tags+=("${CATALOG_IDS[$i]}")
				break
			fi
		done
	fi
	for ((i = 0; i < n; i++)); do
		[[ -n "$primary" && "${CATALOG_IDS[$i]}" == "$primary" ]] && continue
		values+=("${CATALOG_LABELS[$i]}  [${CATALOG_IDS[$i]}]")
		value_tags+=("${CATALOG_IDS[$i]}")
	done
	values+=("Custom model id..." "Skip - use harness default")
	value_tags+=("__custom__" "__skip__")
	_ask_single "  Model for $role (ranked for role; custom/skip at end):" "${values[@]}"
	local tag="" nv=${#values[@]}
	for ((i = 0; i < nv; i++)); do
		if [[ "${values[$i]}" == "$REPLY_VAL" ]]; then tag="${value_tags[$i]}"; break; fi
	done
	case "$tag" in
	__custom__) _ask_text "  custom model id: "; PICKED_MODEL="$REPLY_VAL" ;;
	__skip__) PICKED_MODEL="" ;;
	*) PICKED_MODEL="$tag" ;;
	esac
}

# ===========================================================================
# MAIN
# ===========================================================================
# Source-guard: when sourced (tests exercising the function defs directly),
# stop here - never run MAIN side effects in the sourcing shell.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0 2>/dev/null || exit 0; fi

should_run || exit 75

# ---------------------------------------------------------------------------
# Ask-once gate: the TUI's primary artifact is the per-harness config holding
# mode/tier (~/.claude/agentic-engineering.json, always written on a completed
# install; --config-dir only reroutes it under --dry-run, which never lands
# here). A second run on the same machine is an accidental re-prompt, so print
# a notice and exit 0; --reconfigure bypasses. Runs after should_run so the
# non-TTY fall-through (exit 75, which bootstrap chains on) is untouched.
# ---------------------------------------------------------------------------
AE_TUI_STATE="${AGENTIC_STATE_DIR:-$HOME/.agentic}/install-tui-state.json"
if ! $RECONFIGURE && [[ -f "$AE_TUI_STATE" ]]; then
	echo "install-tui: already configured (found $AE_TUI_STATE); re-run with --reconfigure to change"
	exit 0
fi

# Prompt-free child installs: every adapter inherits this so ae_confirm-based
# prompts and identity auto-detect default to "no" without a TTY read. Claude
# additionally receives explicit --with-*/--permissions flags (see compose).
export AE_NON_INTERACTIVE=true

# Legacy 6-line answer-file shim (see Screen 5): holds the confirm answer
# lifted from line 6 of a pre-tools-format file; empty = normal confirm flow.
LEGACY_CONFIRM=""

# --- Screen 1: harness multi-select --------------------------------------
ms_args=()
for ((i = 0; i < H_COUNT; i++)); do
	label="${H_LABELS[$i]}"; bin="${H_BINS[$i]}"
	if command -v "$bin" >/dev/null 2>&1; then
		anno=""; pre=1
	else
		anno="  (CLI not found)"; pre=0
	fi
	ms_args+=("$label" "$anno" "$pre")
done
_ask_multiselect "Select harnesses to install into:" "${ms_args[@]}"

if [[ "${#SELECTED[@]}" -eq 0 ]]; then
	echo "install-tui: no harnesses selected - nothing to do." >&2
	exit 75
fi
CHOSEN=(${SELECTED[@]+"${SELECTED[@]}"})

# --- Screen 2: mode + tier -----------------------------------------------
_ask_single "Activation mode:" dormant resident; MODE="$REPLY_VAL"
_ask_single "Methodology tier:" minimal medium full; TIER="$REPLY_VAL"

# --- Screen 3: team/model config (optional) ------------------------------
# Delegates to `bin/agentic-team configure --non-interactive` - no yml writing
# here. Scripted answer syntax: default=<h>;role=harness[:model],role=harness...
# Interactive: a guided builder (role -> harness -> model) whose model step is
# backed by the curated catalog picker (see _pick_model) + Custom/Skip entries.
TEAM_DEFAULT=""
TEAM_ASSIGNS=()
team_ans=""
if $SCRIPTED; then
	next_answer; team_ans="$ANSWER"
elif _ask_yesno "Configure per-role harness/model assignments now? [y/N] "; then
	# Optional: pull a user-supplied OpenAI-compatible gateway (9Router, LiteLLM,
	# ...) into the model picker before any role is configured.
	_setup_custom_provider
	# Only team-DISPATCHABLE harnesses can be assigned to a role. Map each
	# installed adapter label to its dispatch name and drop the ones with no
	# worker-dispatch support (hermes/openclaw) - otherwise the assignment is
	# silently rejected later by `agentic-team --assign` (KNOWN_HARNESSES).
	DISPATCHABLE=()
	for _lbl in ${CHOSEN[@]+"${CHOSEN[@]}"}; do
		_dh="$(team_harness_for_label "$_lbl")"
		[[ -n "$_dh" ]] && DISPATCHABLE+=("$_dh")
	done
	# Default harness for roles without an explicit assignment (optional).
	_DH_VALS=(${DISPATCHABLE[@]+"${DISPATCHABLE[@]}"} "(skip)")
	_ask_single "Default harness for unassigned roles:" "${_DH_VALS[@]}"
	[[ "$REPLY_VAL" != "(skip)" ]] && TEAM_DEFAULT="$REPLY_VAL"
	# Guided per-role assignments: role -> harness -> model (catalog picker).
	while _ask_yesno "Add a role assignment? [y/N] "; do
		_ask_single "  Role:" conductor investigator architect orchestration-planner engineer debugger qa-engineer skeptic security-auditor
		_ROLE="$REPLY_VAL"
		_H_VALS=(${DISPATCHABLE[@]+"${DISPATCHABLE[@]}"} "(other...)")
		_ask_single "  Harness for $_ROLE:" "${_H_VALS[@]}"
		_HARNESS="$REPLY_VAL"
		if [[ "$_HARNESS" == "(other...)" ]]; then
			_ask_text "  harness name: "; _HARNESS="$(team_harness_for_label "$REPLY_VAL")"
			[[ -n "$REPLY_VAL" && -z "$_HARNESS" ]] && echo "  ! '$REPLY_VAL' is not a dispatchable harness (installable adapter only); skipped" >&2
		fi
		if [[ -z "$_HARNESS" ]]; then echo "  ! skipped (no harness)"; continue; fi
		_pick_model "$_ROLE"
		_MODEL="$PICKED_MODEL"
		if [[ -n "$_MODEL" ]]; then TEAM_ASSIGNS+=("$_ROLE=$_HARNESS:$_MODEL")
		else TEAM_ASSIGNS+=("$_ROLE=$_HARNESS"); fi
	done
fi
# Scripted-only parsing of the free-text answer (interactive sets vars above).
if [[ -n "$team_ans" && "$team_ans" != "skip" ]]; then
	IFS=';' read -r _seg1 _seg2 <<<"$team_ans"
	for seg in "$_seg1" "$_seg2"; do
		[[ -z "$seg" ]] && continue
		case "$seg" in
		default=*) TEAM_DEFAULT="${seg#default=}" ;;
		*)
			# one-or-more role=harness[:model], comma-separated
			for pair in ${seg//,/ }; do
				[[ -n "$pair" ]] && TEAM_ASSIGNS+=("$pair")
			done
			;;
		esac
	done
fi

# --- Screen 4: profiles (optional) ---------------------------------------
TENANTS=()
prof_ans=""
if $SCRIPTED; then
	next_answer; prof_ans="$ANSWER"
elif _ask_yesno "Install into per-tenant profile dirs? [y/N] "; then
	_ask_text "  tenant names (space/comma separated): "; prof_ans="$REPLY_VAL"
fi
if [[ -n "$prof_ans" && "$prof_ans" != "skip" ]]; then
	for t in ${prof_ans//,/ }; do
		[[ "$t" =~ ^[a-zA-Z0-9_-]+$ ]] && TENANTS+=("$t")
	done
fi

# profile config dir per install-profiles.sh: ~/.<h>-<tenant>; omp -> /agent.
profile_config_dir() {
	local harness="$1" tenant="$2"
	case "$harness" in
	omp) printf '%s/.omp-%s/agent' "$HOME" "$tenant" ;;
	*) printf '%s/.%s-%s' "$HOME" "$harness" "$tenant" ;;
	esac
}

# --- Screen 5: recommended CLI tools (claude adapter only) ------------------
# skip (default) or a space/comma subset of: gh agent-browser lc jira rclone.
TOOLS=()
tools_ans=""
if $SCRIPTED; then
	next_answer; tools_ans="$ANSWER"
	# Legacy 6-line answer-file shim: files written for the pre-tools format
	# (harnesses mode tier team profiles confirm) put their confirm answer on
	# line 6 - exactly where the tools answer now lives. Discriminate on BOTH
	# signals: the popped answer is a yes/no token AND the queue drained right
	# after this pop (a current 9-line file still has mcps/permissions/confirm
	# queued here, so it can never trip this). bash 3.2: tr, not ${var,,}.
	_tools_lc="$(printf '%s' "$tools_ans" | tr 'A-Z' 'a-z')"
	if [[ "$ANSWER_IDX" -ge "${#ANSWERS[@]}" ]]; then
		case "$_tools_lc" in
		yes|y|no|n)
			LEGACY_CONFIRM="$tools_ans"
			tools_ans="skip"
			echo "install-tui: deprecated 6-line answer file; line 6 treated as confirm, tools/mcps/permissions default to skip" >&2
			;;
		esac
	fi
elif _ask_yesno "Install recommended CLI tools (gh/agent-browser/lc/jira/rclone)? [y/N] "; then
	_ask_multiselect "  Select tools to install:" \
		"gh" "" 0 "agent-browser" "" 0 "lc" "" 0 "jira" "" 0 "rclone" "" 0
	tools_ans="${SELECTED[*]-}"
fi
if [[ -n "$tools_ans" && "$tools_ans" != "skip" ]]; then
	for t in ${tools_ans//,/ }; do
		case "$t" in
		gh|agent-browser|lc|jira|rclone) TOOLS+=("$t") ;;
		esac
	done
fi

# --- Screen 6: Claude MCP servers (claude adapter only) ---------------------
# skip (default) or a space/comma subset of: chrome-devtools mcp-atlassian.
MCPS=()
mcps_ans=""
if $SCRIPTED; then
	next_answer; mcps_ans="$ANSWER"
elif _ask_yesno "Configure Claude MCP servers (chrome-devtools/mcp-atlassian)? [y/N] "; then
	_ask_multiselect "  Select MCP servers to configure:" \
		"chrome-devtools" "" 0 "mcp-atlassian" "" 0
	mcps_ans="${SELECTED[*]-}"
fi
if [[ -n "$mcps_ans" && "$mcps_ans" != "skip" ]]; then
	for m in ${mcps_ans//,/ }; do
		case "$m" in
		chrome-devtools|mcp-atlassian) MCPS+=("$m") ;;
		esac
	done
fi

# --- Screen 7: permissions (claude adapter only) ----------------------------
# skip (default) leaves settings.json untouched; bypass applies the recommended
# bypassPermissions mode with the destructive-command deny list.
PERMS="skip"
if $SCRIPTED; then
	next_answer; perm_ans="$ANSWER"
	case "$perm_ans" in
	bypass) PERMS="bypass" ;;
	*) PERMS="skip" ;;
	esac
else
	if _ask_yesno "Apply recommended bypassPermissions + deny-list to Claude settings? [y/N] "; then
		PERMS="bypass"
	fi
fi

# --- Optional: apply team config (once, before adapter installs) ----------
if [[ -n "$TEAM_DEFAULT" || "${#TEAM_ASSIGNS[@]}" -gt 0 ]]; then
	team_cmd=("$REPO_DIR/bin/agentic-team" configure --non-interactive)
	[[ -n "$TEAM_DEFAULT" ]] && team_cmd+=(--default-harness "$TEAM_DEFAULT")
	for a in ${TEAM_ASSIGNS[@]+"${TEAM_ASSIGNS[@]}"}; do team_cmd+=(--assign "$a"); done
	if [[ "${DRY_RUN:-0}" == "1" ]]; then
		printf 'TEAM: %s\n' "${team_cmd[*]}"
	else
		"${team_cmd[@]}" || echo "  ! team configure failed (continuing)" >&2
	fi
fi

# --- Compose one adapter command -----------------------------------------
# Echoes the full command line (for DRY_RUN print and execution via eval-free
# array). $1 label; $2 config-dir (optional "").
compose_cmd_into() {
	# Fills global COMPOSED=(...) array.
	local label="$1" cfgdir="$2" script; script="$(adapter_script "$label")"
	COMPOSED=(bash "$script")
	# tier - only where advertised (currently .claude).
	if script_supports "$script" "--tier"; then
		COMPOSED+=("--tier=$TIER")
	fi
	# mode: every adapter parses --mode=opt-in|opt-out; passing it suppresses
	# the per-adapter "Choice [1]" prompt. dormant == opt-in, resident == opt-out.
	local mode_flag="opt-out"; [[ "$MODE" == "dormant" ]] && mode_flag="opt-in"
	if script_supports "$script" "--mode"; then
		COMPOSED+=("--mode=$mode_flag")
	fi
	# dormant/resident stub behaviour - only where advertised (may be none).
	if [[ "$MODE" == "dormant" ]] && script_supports "$script" "--dormant"; then
		COMPOSED+=("--dormant")
	elif [[ "$MODE" == "resident" ]] && script_supports "$script" "--resident"; then
		COMPOSED+=("--resident")
	fi
	# config-dir - only where advertised AND a profile was requested.
	if [[ -n "$cfgdir" ]] && script_supports "$script" "--config-dir"; then
		COMPOSED+=("--config-dir=$cfgdir")
	fi
	# Prompt-free run (claude advertises --non-interactive; others probe false).
	if script_supports "$script" "--non-interactive"; then
		COMPOSED+=("--non-interactive")
	fi
	# Claude-only feature flags - grep-probed, so only claude receives them.
	if script_supports "$script" "--with-tools"; then
		if [[ "${#TOOLS[@]}" -gt 0 ]]; then
			local csv; csv="$(IFS=,; echo "${TOOLS[*]}")"
			COMPOSED+=("--with-tools=$csv")
		else
			COMPOSED+=("--no-tools")
		fi
	fi
	if script_supports "$script" "--with-mcp"; then
		if [[ "${#MCPS[@]}" -gt 0 ]]; then
			local csv; csv="$(IFS=,; echo "${MCPS[*]}")"
			COMPOSED+=("--with-mcp=$csv")
		else
			COMPOSED+=("--no-mcp")
		fi
	fi
	if script_supports "$script" "--permissions"; then
		COMPOSED+=("--permissions=$PERMS")
	fi
}

# --- Build the full install plan (label + config-dir pairs) --------------
PLAN_LABELS=()
PLAN_CFGDIRS=()
if [[ "${#TENANTS[@]}" -gt 0 ]]; then
	for label in ${CHOSEN[@]+"${CHOSEN[@]}"}; do
		if script_supports "$(adapter_script "$label")" "--config-dir"; then
			for t in "${TENANTS[@]}"; do
				PLAN_LABELS+=("$label"); PLAN_CFGDIRS+=("$(profile_config_dir "$label" "$t")")
			done
		else
			# no per-profile support: single default install
			PLAN_LABELS+=("$label"); PLAN_CFGDIRS+=("")
		fi
	done
else
	for label in ${CHOSEN[@]+"${CHOSEN[@]}"}; do
		PLAN_LABELS+=("$label"); PLAN_CFGDIRS+=("")
	done
fi

# --- Screen 5: summary + confirm -----------------------------------------
{
	printf 'Install plan:\n'
	printf '  mode=%s  tier=%s\n' "$MODE" "$TIER"
	[[ -n "$TEAM_DEFAULT" ]] && printf '  team default=%s\n' "$TEAM_DEFAULT"
	[[ "${#TEAM_ASSIGNS[@]}" -gt 0 ]] && printf '  team assigns=%s\n' "${TEAM_ASSIGNS[*]}"
	[[ "${#TENANTS[@]}" -gt 0 ]] && printf '  profiles=%s\n' "${TENANTS[*]}"
	if [[ "${#TOOLS[@]}" -gt 0 ]]; then printf '  tools=%s\n' "${TOOLS[*]}"; else printf '  tools=skip\n'; fi
	if [[ "${#MCPS[@]}" -gt 0 ]]; then printf '  mcps=%s\n' "${MCPS[*]}"; else printf '  mcps=skip\n'; fi
	printf '  permissions=%s\n' "$PERMS"
	for ((i = 0; i < ${#PLAN_LABELS[@]}; i++)); do
		if [[ -n "${PLAN_CFGDIRS[$i]}" ]]; then
			printf '  - %s -> %s\n' "${PLAN_LABELS[$i]}" "${PLAN_CFGDIRS[$i]}"
		else
			printf '  - %s\n' "${PLAN_LABELS[$i]}"
		fi
	done
} | if $SCRIPTED || [[ "${DRY_RUN:-0}" == "1" ]]; then cat; else tee /dev/tty; fi

if [[ -n "$LEGACY_CONFIRM" ]]; then
	# Legacy 6-line file: line 6 was the confirm answer (see Screen 5 shim).
	_legacy_lc="$(printf '%s' "$LEGACY_CONFIRM" | tr 'A-Z' 'a-z')"
	if [[ "$_legacy_lc" != "yes" && "$_legacy_lc" != "y" ]]; then
		echo "install-tui: cancelled by user." >&2
		exit 75
	fi
elif ! _ask_yesno "Proceed with install? [y/N] "; then
	echo "install-tui: cancelled by user." >&2
	exit 75
fi

# --- Execute (or DRY_RUN print) ------------------------------------------
FAIL_LABELS=()
FAIL_REASONS=()
for ((i = 0; i < ${#PLAN_LABELS[@]}; i++)); do
	label="${PLAN_LABELS[$i]}"; cfgdir="${PLAN_CFGDIRS[$i]}"
	compose_cmd_into "$label" "$cfgdir"
	if [[ "${DRY_RUN:-0}" == "1" ]]; then
		printf 'DRY_RUN: %s\n' "${COMPOSED[*]}"
		continue
	fi
	printf '==> installing %s%s ...\n' "$label" "${cfgdir:+ ($cfgdir)}"
	rc=0
	"${COMPOSED[@]}" || rc=$?
	if [[ "$rc" -eq 0 ]]; then
		printf '    OK: %s\n' "$label"
	else
		printf '    FAIL: %s (install.sh exit %s)\n' "$label" "$rc"
		FAIL_LABELS+=("$label"); FAIL_REASONS+=("exit $rc")
	fi
done

# --- Final summary -------------------------------------------------------
echo ""
echo "Summary:"
if [[ "${#FAIL_LABELS[@]}" -eq 0 ]]; then
	echo "  all ${#PLAN_LABELS[@]} install(s) succeeded."
	# Harness-agnostic ask-once marker: written once per completed run so a
	# later re-invocation (from ANY harness) short-circuits at the gate above
	# instead of re-prompting. --reconfigure bypasses. Skipped under DRY_RUN.
	if [[ "${DRY_RUN:-0}" != "1" ]]; then
		mkdir -p "$(dirname "$AE_TUI_STATE")" 2>/dev/null \
			&& printf '{"completed_at":"%s","mode":"%s","tier":"%s","harnesses":"%s"}\n' \
			"$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$MODE" "$TIER" "${CHOSEN[*]}" \
			> "$AE_TUI_STATE" 2>/dev/null || true
	fi
	exit 0
fi
for ((i = 0; i < ${#FAIL_LABELS[@]}; i++)); do
	printf '  FAILED: %s (%s)\n' "${FAIL_LABELS[$i]}" "${FAIL_REASONS[$i]}"
done
exit 1
