# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared self-heal helper for real-directory skill-install adapters
#          (.kimi, .omp, .pi) to remove a stale pre-rename skill directory
#          left behind at skills/agentic-engineering after the skill was
#          renamed to skills/dinostack. Real-directory adapters mkdir + cp
#          real files alongside symlinked subdirs, so a directory-ownership
#          predicate is required before deletion: unlike a symlink-destination
#          prune (which can never traverse into a target it does not own),
#          removing a real directory can destroy operator content if that
#          directory was repurposed after install. Centralised here so the
#          predicate and its regression coverage exist in exactly one place
#          instead of three near-identical inline copies.
#
# Public API:
#   ae_prune_stale_skill_dir <dir> [allowed-real-file ...]
#     Removes <dir> ONLY when every entry inside it is either:
#       (a) a symlink whose realpath resolves inside a methodology checkout
#           (contains a /DinoStack/ or -DinoStack/ path component), or
#       (b) an exact-name match against one of the caller-supplied
#           allowed-real-file basenames (the adapter's own generated real
#           files, e.g. SKILL.md METHODOLOGY.md).
#     On ANY unrecognized entry (extra file, unexpected symlink target, a
#     directory, etc.), the function aborts and leaves <dir> untouched -
#     it never falls back to a forceful removal. Not a symlink, and not a
#     directory -> no-op (nothing to prune). Deletion never uses `rm -rf`
#     (harness-blocked in this repo); it uses `find -mindepth 1 -delete` on
#     the exact literal path, then `rmdir`.
#     Returns 0 whether it pruned or found nothing to prune; returns 1 when
#     it refused to prune due to an unrecognized entry (dir left in place).
#
# Upstream deps: bash 3.2+, python3 (realpath resolution), GNU/BSD `find`.
# Downstream consumers: .kimi/install.sh, .omp/install.sh, .pi/install.sh.
# Failure modes: prints a `! ... - leaving directory in place` line and
#                returns 1 on any unrecognized entry; never partially deletes.
# Side-effects: deletes files/directories under <dir> and <dir> itself, only
#               after every entry has passed the ownership predicate.
# Performance: O(entries in <dir>), single non-recursive listing.
# ---------------------------------------------------------------------------

ae_prune_stale_skill_dir() {
  local dir="$1"
  shift
  local -a allowed_real_files=("$@")

  # Not a real directory (absent, a symlink, or a regular file) -> nothing
  # for this predicate to own; the symlink case is handled by each adapter's
  # own dedicated symlink-prune logic, not this function.
  [[ -d "$dir" && ! -L "$dir" ]] || return 0

  local entry name target real_target allowed recognized
  while IFS= read -r entry; do
    [[ -n "$entry" ]] || continue
    name="$(basename "$entry")"
    if [[ -L "$entry" ]]; then
      target="$(readlink "$entry")"
      real_target="$(python3 -c "import os.path,sys; print(os.path.realpath(sys.argv[1]))" "$entry" 2>/dev/null)"
      if [[ "$real_target" == */DinoStack/* || "$real_target" == *-DinoStack/* ]]; then
        continue
      fi
      echo "  ! $dir: unrecognized symlink entry '$name' -> $target - leaving directory in place"
      return 1
    fi
    recognized=0
    for allowed in "${allowed_real_files[@]+"${allowed_real_files[@]}"}"; do
      if [[ "$name" == "$allowed" ]]; then
        recognized=1
        break
      fi
    done
    if [[ "$recognized" -eq 0 ]]; then
      echo "  ! $dir: unrecognized entry '$name' - leaving directory in place"
      return 1
    fi
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -print)

  find "$dir" -mindepth 1 -delete
  rmdir "$dir"
  echo "  - removed stale pre-rename skill directory: $dir"
  return 0
}
