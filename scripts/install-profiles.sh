#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Module Manifest
#
# Purpose: Install agentic-engineering into per-tenant PROFILE config dirs
#          (e.g. ~/.claude-<tenant>, ~/.codex-<tenant>) across the claude/codex/
#          omp/pi harnesses, plus the single global Cursor install. Each
#          harness install.sh is invoked with --config-dir pointed at the
#          tenant profile dir, so shared user state (~/.agentic, ~/.local/bin,
#          ~/.claude.json) is NOT relocated -- only the per-harness config dir
#          moves. This is the profile-aware counterpart to install-all.sh,
#          which only ever targets the default base dirs.
#
# Public API:
#   ./scripts/install-profiles.sh
#       [--tenants="a b c"]        (explicit override; if omitted, discover
#                                   tenants from existing ~/.<harness>-* dirs)
#       [--discover]               (optional, same as omitting --tenants)
#       [--create-profile=<tenant>] (opt-in: create a NEW profile for all
#                                   harnesses before installing; gated by a
#                                   pre-flight safety check)
#       [--check-only]             (run the pre-flight check for
#                                   --create-profile, report creatability, and
#                                   exit WITHOUT creating anything)
#       [--harnesses="a b c"]      (default: "claude codex omp pi")
#       [--no-cursor]              (skip the global ~/.cursor install)
#       [--dry-run]                (forwarded to installers that support it)
#       [-h|--help]
#   Any other flags (e.g. --mode=opt-out --profile=default --no-identity) are
#   forwarded verbatim to each harness install.sh.
#
# Profile dir convention: ~/.<harness>-<tenant> for claude/codex/pi;
#   ~/.omp-<tenant>/agent for omp (its config root is <base>/agent). By default
#   a profile dir is installed into only if it already exists on disk. The
#   optional --create-profile gate creates a fresh profile for all harnesses.
#
# Upstream deps: bash 3.2+, the per-harness <adapter>/install.sh scripts.
#
# Failure modes: continue-on-error; failures collected and reported in a final
#   summary; exit non-zero if any install failed. Missing profile dirs are
#   skipped with a note (not a failure). Profile creation is refused unless
#   both the --create-profile flag is present and the pre-flight check passes.
# =============================================================================

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HARNESSES="claude codex omp pi"
DO_CURSOR=true
PASSTHROUGH=()
TENANTS=""
TENANTS_SOURCE="discover" # 'discover' or 'explicit'
CREATE_PROFILE=""
CHECK_ONLY=false

print_help() { sed -n '3,52p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
	case "$arg" in
	-h | --help)
		print_help
		exit 0
		;;
	--tenants=*)
		TENANTS="${arg#--tenants=}"
		TENANTS_SOURCE="explicit"
		;;
	--discover)
		TENANTS=""
		TENANTS_SOURCE="discover"
		;;
	--create-profile=*)
		CREATE_PROFILE="${arg#--create-profile=}"
		TENANTS_SOURCE="explicit"
		;;
	--check-only) CHECK_ONLY=true ;;
	--harnesses=*) HARNESSES="${arg#--harnesses=}" ;;
	--no-cursor) DO_CURSOR=false ;;
	*) PASSTHROUGH+=("$arg") ;; # --mode, --profile, --dry-run, etc.
	esac
done

# Map a harness label to the profile config dir for a tenant.
# omp's config root is <base>/agent; the others are the base dir itself.
profile_config_dir() {
	local harness="$1" tenant="$2"
	case "$harness" in
	omp) printf '%s/.omp-%s/agent' "$HOME" "$tenant" ;;
	*) printf '%s/.%s-%s' "$HOME" "$harness" "$tenant" ;;
	esac
}

# The on-disk profile base dir, independent of omp's /agent suffix.
profile_base_dir() { printf '%s/.%s-%s' "$HOME" "$1" "$2"; }

is_valid_tenant_name() {
	local name="$1"
	[[ -n "$name" && "$name" =~ ^[a-zA-Z0-9_-]+$ ]]
}

# Fixed whitelist of installable harnesses. A harness name is used to build a
# filesystem path ($REPO_DIR/.<harness>/install.sh) that is then executed, so
# it MUST be validated against this enum before any path construction to
# prevent path traversal / arbitrary-script execution (CWE-22).
KNOWN_INSTALL_HARNESSES="claude codex omp pi"

is_known_harness() {
	local h="$1" known
	for known in $KNOWN_INSTALL_HARNESSES; do
		[[ "$h" == "$known" ]] && return 0
	done
	return 1
}

# Discover tenant names from existing profile base dirs on disk.
# Scans every harness prefix and returns the sorted union of suffixes.
discover_tenants() {
	local h d tenant seen=""
	local shopt_nullglob=false
	[[ "$(shopt -p nullglob 2>/dev/null)" == "shopt -s nullglob" ]] || {
		shopt -s nullglob
		shopt_nullglob=true
	}
	for h in $HARNESSES; do
		for d in "$HOME/.$h-"*; do
			[[ -d "$d" ]] || continue
			# Tenant = the suffix of the profile dir basename after ".<harness>-".
			# Strip only that prefix (NOT the last-hyphen ${d##*-}, which would
			# mangle multi-hyphen tenant names like "foo-bar"). For omp, the profile
			# dir ends in "/agent", so strip that first to expose the parent dir.
			local tenant_dir
			if [[ "$h" == "omp" ]]; then
				tenant_dir="${d%/agent}"
			else
				tenant_dir="$d"
			fi
			local tenant="${tenant_dir##*/.${h}-}"
			[[ "$tenant" == "$h" ]] && continue # malformed, no suffix
			is_valid_tenant_name "$tenant" || continue
			if [[ " $seen " != *" $tenant "* ]]; then
				seen+=" $tenant"
			fi
		done
	done
	[[ "$shopt_nullglob" == true ]] && shopt -u nullglob
	echo "${seen# }" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/ $//'
}

# Pre-flight check for profile creation. Reports per-harness creatability and
# returns 0 only if ALL harnesses can safely create the profile.
check_profile_creatable() {
	local tenant="$1" h base parent issues=0
	echo "Pre-flight check: profile '$tenant'"
	for h in $HARNESSES; do
		is_known_harness "$h" || { echo "  $h: skipped (unknown harness)"; continue; }
		base="$(profile_base_dir "$h" "$tenant")"
		parent="$(dirname "$base")"
		if [[ -e "$base" ]]; then
			echo "  $h: NOT creatable - already exists ($base)"
			issues=$((issues + 1))
		elif [[ ! -d "$parent" ]]; then
			echo "  $h: NOT creatable - parent directory missing ($parent)"
			issues=$((issues + 1))
		elif [[ ! -w "$parent" ]]; then
			echo "  $h: NOT creatable - parent directory not writable ($parent)"
			issues=$((issues + 1))
		else
			echo "  $h: creatable ($base)"
		fi
	done
	if [[ "$issues" -eq 0 ]]; then
		echo "Result: creatable (yes)"
		return 0
	else
		echo "Result: NOT creatable (no) - $issues issue(s)"
		return 1
	fi
}

create_profile_dirs() {
	local tenant="$1" h base
	for h in $HARNESSES; do
		is_known_harness "$h" || continue
		base="$(profile_base_dir "$h" "$tenant")"
		mkdir -p "$base"
		if [[ "$h" == "omp" ]]; then
			mkdir -p "$(profile_config_dir "$h" "$tenant")"
		fi
	done
}

# Resolve the tenant list.
if [[ "$TENANTS_SOURCE" == "discover" ]]; then
	TENANTS="$(discover_tenants)"
else
	# explicit --tenants or --create-profile
	: # TENANTS already set
fi

if [[ -n "$CREATE_PROFILE" ]]; then
	if ! is_valid_tenant_name "$CREATE_PROFILE"; then
		echo " ! invalid profile name: '$CREATE_PROFILE' (use a-z, A-Z, 0-9, _, -)" >&2
		exit 1
	fi
	TENANTS="$CREATE_PROFILE"

	if ! check_profile_creatable "$CREATE_PROFILE"; then
		echo " ! refusing to create profile '$CREATE_PROFILE' (pre-flight check failed)" >&2
		exit 1
	fi

	if [[ "$CHECK_ONLY" == true ]]; then
		echo " --check-only: no directories created."
		exit 0
	fi

	echo "Creating profile directories for '$CREATE_PROFILE'..."
	create_profile_dirs "$CREATE_PROFILE"
fi

if [[ "$CHECK_ONLY" == true && -z "$CREATE_PROFILE" ]]; then
	echo " ! --check-only requires --create-profile=<tenant>" >&2
	exit 1
fi

SUCCEEDED=()
FAILED=()
SKIPPED=()

if [[ -z "$TENANTS" ]]; then
	echo "No tenant profile directories found; nothing to install."
	echo "Use --tenants=<names> or --create-profile=<tenant> to proceed."
	DO_CURSOR=false
fi

for tenant in $TENANTS; do
	if ! is_valid_tenant_name "$tenant"; then
		echo " ! skip tenant '$tenant': invalid name (use a-z, A-Z, 0-9, _, -)" >&2
		continue
	fi
	for harness in $HARNESSES; do
		if ! is_known_harness "$harness"; then
			echo "  ! skip harness '$harness': unknown (allowed: $KNOWN_INSTALL_HARNESSES)" >&2
			continue
		fi
		base="$(profile_base_dir "$harness" "$tenant")"
		label="$harness-$tenant"
		# Symlink guard (CWE-59): a symlinked profile dir would let the harness
		# installer silently follow and clobber outside the intended per-tenant
		# tree. Refuse with a clear error instead of installing through it.
		if [[ -L "$base" ]]; then
			echo "  ! refusing $label: profile dir is a symlink ($base)" >&2
			FAILED+=("$label")
			continue
		elif [[ ! -d "$base" ]]; then
			echo "  ~ skip $label: profile dir $base does not exist"
			SKIPPED+=("$label")
			continue
		fi
		installer="$REPO_DIR/.$harness/install.sh"
		if [[ ! -f "$installer" ]]; then
			echo "  ! skip $label: no installer at $installer"
			SKIPPED+=("$label")
			continue
		fi
		cfg="$(profile_config_dir "$harness" "$tenant")"
		echo ""
		echo "==> $label  (--config-dir=$cfg)"
		rc=0
		bash "$installer" --config-dir="$cfg" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}" || rc=$?
		if [[ "$rc" -eq 0 ]]; then SUCCEEDED+=("$label"); else
			echo "  ! $label failed (exit $rc)" >&2
			FAILED+=("$label")
		fi
	done
done

# Global Cursor (single ~/.cursor, no per-tenant variants).
if [[ "$DO_CURSOR" == true && -f "$REPO_DIR/.cursor/install.sh" ]]; then
	echo ""
	echo "==> cursor (global ~/.cursor)"
	rc=0
	bash "$REPO_DIR/.cursor/install.sh" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}" || rc=$?
	if [[ "$rc" -eq 0 ]]; then SUCCEEDED+=("cursor"); else
		echo "  ! cursor failed (exit $rc)" >&2
		FAILED+=("cursor")
	fi
fi

echo ""
echo "================================================================"
echo "install-profiles summary"
echo "================================================================"
echo "Succeeded (${#SUCCEEDED[@]}): ${SUCCEEDED[*]:-none}"
[[ ${#SKIPPED[@]} -gt 0 ]] && echo "Skipped   (${#SKIPPED[@]}): ${SKIPPED[*]}"
if [[ ${#FAILED[@]} -gt 0 ]]; then
	echo "Failed    (${#FAILED[@]}): ${FAILED[*]}"
	exit 1
fi
echo ""
echo "All ${#SUCCEEDED[@]} install(s) succeeded."
