# install-tools.sh: step 2 of install.sh, sourced so tests can build the exact installed layout.
#
#   neva_install_tools REPO PREFIX BIN
#
# Copies the tools and every resource bin/neva reads (plugins, the marketplace manifest,
# adapters) from the checkout at REPO into PREFIX and links each tool into BIN. Never uses
# sudo, never writes outside PREFIX and BIN, and returns non-zero, naming the path and the fix,
# the moment a check or a copy fails.

_neva_tools_refuse() {
  printf 'install-tools: %s\n' "$*" >&2
  return 1
}

# PATH must sit under $HOME, and no component from $HOME down to PATH may be a symlink: a link
# anywhere on that chain would steer every copy below it somewhere else.
_neva_tools_safe_dir() {
  local path="$1" rest cur part
  local -a parts
  [ -n "${HOME:-}" ] || { _neva_tools_refuse "HOME is not set. fix: export HOME, then re-run install.sh"; return 1; }
  case "$path" in
    "$HOME"/*) : ;;
    *) _neva_tools_refuse "$path is not inside HOME ($HOME). fix: install under your home directory"; return 1 ;;
  esac
  rest="${path#"$HOME"/}"
  IFS=/ read -r -a parts <<< "$rest"
  cur="$HOME"
  for part in "${parts[@]}"; do
    [ -n "$part" ] || continue
    if [ "$part" = ".." ]; then
      _neva_tools_refuse "$path contains '..'. fix: write the install path out in full"
      return 1
    fi
    cur="$cur/$part"
    if [ -L "$cur" ]; then
      _neva_tools_refuse "$cur is a symlink (to $(readlink "$cur")). fix: replace it with a real directory, then re-run install.sh"
      return 1
    fi
  done
}

# A tree install.sh copies over must hold no symlink at all: cp follows a link it finds at a
# destination, so one planted link inside the prefix would redirect a copy out of it.
_neva_tools_no_links() {
  local tree="$1" found
  if [ -L "$tree" ]; then
    _neva_tools_refuse "$tree is a symlink (to $(readlink "$tree")). fix: remove that link, then re-run install.sh"
    return 1
  fi
  [ -e "$tree" ] || return 0
  found="$(find "$tree" -type l -print 2>/dev/null | head -n 1)"
  if [ -n "$found" ]; then
    _neva_tools_refuse "$found is a symlink inside $tree, which install.sh replaces. fix: remove that link, then re-run install.sh"
    return 1
  fi
}

neva_install_tools() {
  local repo="$1" prefix="$2" bin="$3" f name child d
  _neva_tools_safe_dir "$prefix" || return 1
  _neva_tools_safe_dir "$bin" || return 1
  for child in bin lib plugins .claude-plugin adapters services VERSION; do
    _neva_tools_no_links "$prefix/$child" || return 1
  done
  for f in "$repo/bin/"*; do
    name="$(basename "$f")"
    if [ -d "$bin/$name" ] && [ ! -L "$bin/$name" ]; then
      _neva_tools_refuse "$bin/$name is a directory where install.sh links the $name tool. fix: move it aside, then re-run install.sh"
      return 1
    fi
  done
  mkdir -p "$prefix" "$bin" || return 1
  cp -R "$repo/bin" "$repo/lib" "$prefix/" || return 1
  # VERSION travels with the install. Without it `report` looks for ../VERSION relative to bin/,
  # finds nothing, and every bug report a user sends back says "Neva " with the version blank:
  # the single most useful field in the report, always empty. Found 2026-08-14 by running report
  # in a fresh install rather than from the repo.
  if [ -f "$repo/VERSION" ]; then cp "$repo/VERSION" "$prefix/VERSION" || return 1; fi
  # tools resolve lib relative to the repo; installed copies use the fixed prefix instead. The
  # path is written as one shell-quoted word (shlex.quote), never spliced into shell or sed
  # text, so quotes, $( ), backticks, & or | in it stay literal characters.
  python3 - "$prefix" "$prefix/bin/"* <<'PYEOF' || return 1
import os, shlex, sys
prefix = sys.argv[1]
old = '. "$(cd "$(dirname "$0")/.." && pwd)/lib/config.sh"'
new = ". " + shlex.quote(prefix + "/lib/config.sh")
for path in sys.argv[2:]:
    if not os.path.isfile(path) or os.path.islink(path):
        continue
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        continue
    lines = text.split("\n")
    changed = [new + line[len(old):] if line.startswith(old) else line for line in lines]
    if changed != lines:
        mode = os.stat(path).st_mode & 0o777
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(changed))
        os.chmod(path, mode)
PYEOF
  for f in "$prefix/bin/"*; do
    [ -f "$f" ] || continue
    chmod +x "$f" || return 1
    ln -sfn "$f" "$bin/$(basename "$f")" || return 1
  done
  # The installed neva resolves every resource relative to this prefix, never to the checkout,
  # so it keeps working once the checkout is deleted or moved: the plugins (rules, hooks and
  # the nightly instinct job), the marketplace manifest Claude Code is pointed at, and any
  # adapter contracts. The instinct job runs from here too, not from the plugin cache (whose
  # path Claude Code owns), so the timer survives a moved checkout.
  cp -R "$repo/plugins" "$prefix/" || return 1
  if [ -d "$repo/.claude-plugin" ]; then cp -R "$repo/.claude-plugin" "$prefix/" || return 1; fi
  if [ -d "$repo/adapters" ]; then cp -R "$repo/adapters" "$prefix/" || return 1; fi
  # A checkout that ever ran its tests carries bytecode and test caches in every tree, not only
  # plugins; none of it belongs in the prefix, and bytecode embeds the checkout's absolute paths.
  for d in bin lib plugins adapters; do
    [ -d "$prefix/$d" ] || continue
    find "$prefix/$d" \( -name __pycache__ -o -name .pytest_cache \) -type d -prune -exec rm -rf {} + || return 1
  done
}
