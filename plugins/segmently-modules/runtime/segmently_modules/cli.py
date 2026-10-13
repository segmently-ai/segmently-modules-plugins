import argparse
import os
import sys
from pathlib import Path

from segmently_modules import __version__
from segmently_modules import (adopt_cmd, agents_md_cmd, catalog_cmd, choose_cmd, ci_cmd, code_map_cmd, coverage_cmd, create_cmd,
                    eject_cmd, eval_cmd, hooks_cmd, index_cmd, init_cmd, lint, match,
                    migrate_cmd, next_cmd, packs_cmd, pipeline, proposals_cmd, query,
                    registry_cmd, roles_cmd, schema_cmd, setup_cmd, sync_cmd,
                    sync_instructions_cmd, templates_cmd)
from segmently_modules.output import EXIT_INTERRUPTED, EXIT_OK, EXIT_USAGE, UsageError, clear_notes, flush_notes, quiet_streams

COMMANDS: list = [init_cmd, schema_cmd, match, query, lint, registry_cmd, index_cmd,
                  proposals_cmd, hooks_cmd, sync_cmd, create_cmd, migrate_cmd, pipeline,
                  coverage_cmd, code_map_cmd, ci_cmd, templates_cmd, packs_cmd,
                  eject_cmd, agents_md_cmd, sync_instructions_cmd, adopt_cmd, eval_cmd,
                  roles_cmd, next_cmd, setup_cmd, catalog_cmd, choose_cmd]


def common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, help="repository root (default: auto-detect)")
    common.add_argument("--config-dir", type=Path, help="config dir (default: <root>/.segmently-modules)")
    common.add_argument("--json", action="store_true", help="JSON envelope on stdout")
    return common


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="segmently-modules", description="Module-system engine")
    p.add_argument("--version", action="version", version=f"segmently-modules {__version__}")
    sub = p.add_subparsers(dest="verb", required=True)
    common = common_parser()
    for command in COMMANDS:
        command.register(sub, common)
    return p


def main(argv: list[str] | None = None) -> int:
    with quiet_streams():  # a closed reader of stdout (or stderr) ends the output, not the run
        return _main(argv)


def _main(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    clear_notes()
    try:
        code = args.func(args)
        if code == EXIT_OK:  # deferred notes (D6) only for a run that succeeded, after stdout
            flush_notes()
        return code
    except UsageError as e:
        print(f"segmently-modules: error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:  # Ctrl-C (lock wait, `create` prompt): no traceback either
        print("segmently-modules: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as e:  # headless contract: exit 2, never a traceback
        if os.environ.get("SEGMENTLY_MODULES_DEBUG"):
            raise
        print(f"segmently-modules: internal error: {type(e).__name__}: {e} "
              f"(set SEGMENTLY_MODULES_DEBUG=1 for a traceback)", file=sys.stderr)
        return EXIT_USAGE
