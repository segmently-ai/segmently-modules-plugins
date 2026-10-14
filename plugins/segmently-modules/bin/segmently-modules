#!/bin/sh
# The segmently-modules plugin's bin/segmently-modules (tools/build_plugins.py installs this file there, mode 0755):
# runs the engine shipped in <plugin>/runtime with the first Python 3.9 or newer it finds —
# $SEGMENTLY_MODULES_PYTHON; else python3.14 … python3.9, python3 on PATH (macOS: the Command Line
# Tools' python3, 3.9, the package that brings git); else the same names in the directories
# below, one directory at a time (outside $HOME: a sandbox that denies $HOME breaks pyenv and
# asdf shims); else `uv run`. Each candidate is run once to check its version; a name that is
# not there starts no process. The engine runs through $RUN, which drops the working directory
# from that one process's sys.path (what `-P` does on 3.11+) — the working directory never
# shadows the plugin's engine, and what the engine starts (an executor, a hook) imports as it
# would anywhere.
# POSIX sh (dash too); every message is one stderr line and exit 127.
DIRS="/opt/homebrew/bin /usr/local/bin /usr/bin"
NAMES="python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3"
PROBE='import sys; sys.exit(sys.version_info < (3, 9))'
RUN='import runpy, sys; sys.path[:1] == [""] and sys.path.pop(0); runpy.run_module("segmently_modules", run_name="__main__", alter_sys=True)'

me=$0
while [ -h "$me" ]; do  # follow a symlink to this file: the plugin is where the file lives
    link=$(readlink "$me" 2>/dev/null) || {
        printf 'segmently-modules: cannot follow the symlink %s (readlink)\n' "$me" >&2; exit 127; }
    case $link in
        /*) me=$link ;;
        *) case $me in */*) me=${me%/*}/$link ;; *) me=./$link ;; esac ;;
    esac
done
case $me in */*) bin=${me%/*} ;; *) bin=. ;; esac
root=$(CDPATH= cd -P -- "$bin/.." >/dev/null && pwd -P) || {
    printf 'segmently-modules: cannot enter the plugin directory %s/..\n' "$bin" >&2; exit 127; }
[ -f "$root/runtime/segmently_modules/__main__.py" ] || {  # never another segmently-modules from PYTHONPATH
    printf 'segmently-modules: %s has no runtime/segmently_modules — reinstall the plugin\n' "$root" >&2; exit 127; }
case $root in *:*)  # it would split PYTHONPATH
    printf 'segmently-modules: %s holds a ":" — install the plugin elsewhere\n' "$root" >&2; exit 127 ;;
esac
PYTHONPATH="$root/runtime${PYTHONPATH:+:$PYTHONPATH}"  # the plugin's engine comes first
PYTHONDONTWRITEBYTECODE=1  # never write __pycache__ into the installed plugin
export PYTHONPATH PYTHONDONTWRITEBYTECODE

if [ -n "${SEGMENTLY_MODULES_PYTHON:-}" ]; then  # an explicit choice: used, or a loud refusal
    if ! command -v "$SEGMENTLY_MODULES_PYTHON" >/dev/null 2>&1; then
        printf 'segmently-modules: SEGMENTLY_MODULES_PYTHON=%s: not found — %s\n' "$SEGMENTLY_MODULES_PYTHON" \
            "unset it, or point it at Python 3.9 or newer" >&2
        exit 127
    fi
    "$SEGMENTLY_MODULES_PYTHON" -c "$PROBE" </dev/null >/dev/null 2>&1
    rc=$?
    [ "$rc" -eq 0 ] && exec "$SEGMENTLY_MODULES_PYTHON" -c "$RUN" "$@"
    if [ "$rc" -eq 1 ]; then why="is older than Python 3.9"; else why="does not run (exit $rc)"; fi
    printf 'segmently-modules: SEGMENTLY_MODULES_PYTHON=%s %s — unset it, or point it at Python 3.9 or newer\n' \
        "$SEGMENTLY_MODULES_PYTHON" "$why" >&2
    exit 127
fi
for name in $NAMES; do
    py=$(command -v "$name" 2>/dev/null) || continue
    "$py" -c "$PROBE" </dev/null >/dev/null 2>&1 && exec "$py" -c "$RUN" "$@"
done
for dir in $DIRS; do
    for name in $NAMES; do
        [ -x "$dir/$name" ] || continue
        "$dir/$name" -c "$PROBE" </dev/null >/dev/null 2>&1 &&
            exec "$dir/$name" -c "$RUN" "$@"
    done
done
if command -v uv >/dev/null 2>&1 && uv --version </dev/null >/dev/null 2>&1; then
    exec uv run --no-project --python '>=3.9' python -c "$RUN" "$@"
fi
echo "segmently-modules: no Python 3.9 or newer found — install Python 3.9 or newer, set SEGMENTLY_MODULES_PYTHON" \
     "to one, or install uv (it fetches a Python)" >&2
exit 127
