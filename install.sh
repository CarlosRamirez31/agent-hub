#!/bin/sh
# Local install only. No curl, package managers, downloads, or sudo.
set -eu
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
command -v python3 >/dev/null 2>&1 || { echo 'Se necesita Python 3.' >&2; exit 1; }
python3 -c 'import curses, sqlite3' || exit 1
target_dir="${HOME}/.local/bin"
target="$target_dir/agent-hub"
source_path="$project_dir/bin/agent-hub"
if [ -e "$target" ] || [ -L "$target" ]; then
    if [ ! -L "$target" ] || [ "$(readlink "$target")" != "$source_path" ]; then
        echo "Ya existe $target; no se reemplazó." >&2
        exit 1
    fi
else
    mkdir -p -- "$target_dir"
    ln -s -- "$source_path" "$target"
fi
legacy="$target_dir/codex-hub"
if [ -L "$legacy" ] && [ "$(readlink "$legacy")" = "$project_dir/bin/codex-hub" ]; then
    rm -- "$legacy"
fi
printf 'Instalado: %s\nEjecuta: agent-hub\n' "$target"
case ":$PATH:" in
    *":$target_dir:"*) ;;
    *) printf 'Añade a tu shell: export PATH="$HOME/.local/bin:$PATH"\n' ;;
esac
