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
#   ./scripts/install-tui.sh [--no-tui]
#     Interactive mode (default) when: /dev/tty readable AND stdout is a TTY
#     AND --no-tui absent AND INSTALL_TUI_SCRIPT unset.
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
#   1. harnesses : space/comma list of labels, or the word `detected`
#   2. mode      : dormant | resident
#   3. tier      : minimal | medium | full
#   4. team      : `skip`, or `default=<h>` and/or `role=harness[:model],...`
#                  e.g. `default=claude;engineer=codex,skeptic=gemini:pro`
#   5. profiles  : `skip`, or space/comma tenant names
#   6. confirm   : yes | no
#   Blank lines and lines beginning with `#` are ignored.
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
for arg in "$@"; do
	[[ "$arg" == "--no-tui" ]] && NO_TUI=true
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

# ===========================================================================
# MAIN
# ===========================================================================
should_run || exit 75

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
CHOSEN=("${SELECTED[@]}")

# --- Screen 2: mode + tier -----------------------------------------------
_ask_single "Activation mode:" dormant resident; MODE="$REPLY_VAL"
_ask_single "Methodology tier:" minimal medium full; TIER="$REPLY_VAL"

# --- Screen 3: team/model config (optional) ------------------------------
# Delegates to `bin/agentic-team configure --non-interactive` - no yml writing
# here. Answer syntax: default=<h>;role=harness[:model],role=harness...
TEAM_DEFAULT=""
TEAM_ASSIGNS=()
team_ans=""
if $SCRIPTED; then
	next_answer; team_ans="$ANSWER"
elif _ask_yesno "Configure per-role harness/model assignments now? [y/N] "; then
	_ask_text "  default harness (blank to skip): "; team_ans="$REPLY_VAL"
	[[ -n "$team_ans" ]] && team_ans="default=$team_ans"
	_ask_text "  assignments role=harness[:model], comma-separated (blank ok): "; assigns="$REPLY_VAL"
	[[ -n "$assigns" ]] && team_ans="${team_ans:+$team_ans;}$assigns"
fi
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

# --- Optional: apply team config (once, before adapter installs) ----------
if [[ -n "$TEAM_DEFAULT" || "${#TEAM_ASSIGNS[@]}" -gt 0 ]]; then
	team_cmd=("$REPO_DIR/bin/agentic-team" configure --non-interactive)
	[[ -n "$TEAM_DEFAULT" ]] && team_cmd+=(--default-harness "$TEAM_DEFAULT")
	for a in "${TEAM_ASSIGNS[@]}"; do team_cmd+=(--assign "$a"); done
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
	# dormant/resident - only where advertised (grep at runtime; may be none yet).
	if [[ "$MODE" == "dormant" ]] && script_supports "$script" "--dormant"; then
		COMPOSED+=("--dormant")
	elif [[ "$MODE" == "resident" ]] && script_supports "$script" "--resident"; then
		COMPOSED+=("--resident")
	fi
	# config-dir - only where advertised AND a profile was requested.
	if [[ -n "$cfgdir" ]] && script_supports "$script" "--config-dir"; then
		COMPOSED+=("--config-dir=$cfgdir")
	fi
}

# --- Build the full install plan (label + config-dir pairs) --------------
PLAN_LABELS=()
PLAN_CFGDIRS=()
if [[ "${#TENANTS[@]}" -gt 0 ]]; then
	for label in "${CHOSEN[@]}"; do
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
	for label in "${CHOSEN[@]}"; do
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
	for ((i = 0; i < ${#PLAN_LABELS[@]}; i++)); do
		if [[ -n "${PLAN_CFGDIRS[$i]}" ]]; then
			printf '  - %s -> %s\n' "${PLAN_LABELS[$i]}" "${PLAN_CFGDIRS[$i]}"
		else
			printf '  - %s\n' "${PLAN_LABELS[$i]}"
		fi
	done
} | if $SCRIPTED || [[ "${DRY_RUN:-0}" == "1" ]]; then cat; else tee /dev/tty; fi

if ! _ask_yesno "Proceed with install? [y/N] "; then
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
	exit 0
fi
for ((i = 0; i < ${#FAIL_LABELS[@]}; i++)); do
	printf '  FAILED: %s (%s)\n' "${FAIL_LABELS[$i]}" "${FAIL_REASONS[$i]}"
done
exit 1
