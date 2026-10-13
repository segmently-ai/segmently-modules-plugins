"""`segmently-modules ci`: one CI gate in three steps that ALWAYS all run, so one failing step never hides
another — lint (plain: config-level findings included), drift (`lint --changed` against the
base) and coverage. Settings: flag, else `[ci]`, else the default (fail_on "warning", base
"HEAD", no coverage threshold = report-only). Exit 1 when a step failed; exit 2 before any step
for a usage error (an unknown or option-like --base, a threshold outside 0–100, no git).

`--baseline FILE|-` (the `--json` output of an earlier run) tells a finding of lint or drift that
predates the change (`known`) from a new one; a step then fails only on the new ones."""
import json
import re
from dataclasses import asdict

from segmently_modules.changes import (branch_point, changed_files, commit_ref, commit_sha, diff_names,
                            is_shallow, repo_files, require_work_tree)
from segmently_modules.coverage_cmd import coverage_report, percent
from segmently_modules.lint import FAIL_ON, drift_report, failing, lint_registry, severity_counts
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.pipeline import read_input
from segmently_modules.workspace import Workspace

NOTHING_TO_COMPARE = ("nothing to compare: the working tree equals HEAD — in CI pass --base "
                      "<target branch>")


def register(sub, common) -> None:
    p = sub.add_parser("ci", parents=[common],
                       help="one CI gate: lint, drift since --base, coverage (all three run)",
                       description="Runs lint (plain), drift (lint --changed against --base) "
                                   "and coverage; exit 1 when any step failed. Each setting: "
                                   "the flag, else [ci] in the config, else the default.")
    p.add_argument("--base", help="drift: compare the working tree (+ untracked files) with this "
                                  "ref (default: [ci] base, else HEAD) — in CI the target "
                                  "branch, e.g. origin/main")
    p.add_argument("--fail-on", choices=sorted(FAIL_ON),
                   help="lint and drift fail at this severity (default: [ci] fail_on, else "
                        "warning)")
    p.add_argument("--fail-under", type=float, metavar="PCT",
                   help="coverage fails below PCT %% (default: [ci] coverage_fail_under, else "
                        "report-only)")
    p.add_argument("--baseline", metavar="FILE|-",
                   help="the --json output of an earlier ci run ('-' = stdin): a lint or drift "
                        "finding it already holds is known, and a step fails only on findings "
                        "that are not (MS050 / MS051 are never known)")
    p.set_defaults(func=run)


BASELINE_SCHEMA = "segmently-modules.ci/1"
NEVER_KNOWN = frozenset({"MS050", "MS051"})  # they describe the change since --base
_DIGITS = re.compile(r"[0-9]+")


def finding_key(f: dict) -> tuple:
    """What makes two findings the same: code, module, path and the message with every run of
    digits read as one `#` (a count in a message moves with an edit)."""
    return f["code"], f["module"], f["path"], _DIGITS.sub("#", f["message"])


def _not_ci(source: str):
    return UsageError(f"--baseline {source}: not the --json output of segmently-modules ci "
                      f"(schema {BASELINE_SCHEMA})")


def _valid_finding(f) -> bool:
    """A finding a baseline can hold: an object with string `code`, `module`, `message` and a
    `path` key that is a string or null."""
    return (isinstance(f, dict) and "path" in f
            and (f["path"] is None or isinstance(f["path"], str))
            and all(isinstance(f.get(k), str) for k in ("code", "module", "message")))


def read_baseline(source: str) -> set:
    """The set of finding keys of the `lint` and `drift` steps of a saved `ci --json` run, read
    as bytes by the shared `-` reader (`pipeline.read_input`) and decoded as strict UTF-8."""
    name = "<stdin>" if source == "-" else source
    try:
        text = read_input(source).decode("utf-8")
    except OSError as e:
        raise UsageError(f"cannot read {name}: {e.strerror or e}") from None
    except UnicodeDecodeError:
        raise UsageError(f"cannot read {name}: not valid UTF-8") from None
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):
        raise _not_ci(source) from None
    data = doc.get("data") if isinstance(doc, dict) and doc.get("schema") == BASELINE_SCHEMA \
        else None
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        raise _not_ci(source)
    keys = set()
    for step in steps:
        if not isinstance(step, dict) or step.get("name") not in ("lint", "drift"):
            continue
        found = step.get("findings")
        if not isinstance(found, list):
            raise _not_ci(source)
        for f in found:
            if not _valid_finding(f):
                raise _not_ci(source)
            keys.add(finding_key(f))
    return keys


def _marked(findings, known: set | None) -> tuple[list[dict], list]:
    """The findings as dicts (with `known` last under a baseline) and those that are not known."""
    rows = [asdict(f) for f in findings]
    if known is None:
        return rows, list(findings)
    flags = [f.code not in NEVER_KNOWN and finding_key(r) in known
             for f, r in zip(findings, rows)]
    for r, flag in zip(rows, flags):
        r["known"] = flag
    return rows, [f for f, flag in zip(findings, flags) if not flag]


def split_change(root, base: str, files: list[str]) -> tuple[int, int]:
    """(committed, uncommitted) of the files changed since `base`: those that differ between
    `base` and HEAD, and those that differ between HEAD and the working tree (untracked files
    included). A file changed in both counts in both; `files` stays their union."""
    if not files:
        return 0, 0
    wanted = set(files)
    committed = wanted & set(diff_names(root, f"{base}..HEAD"))
    uncommitted = wanted & set(changed_files(root, base="HEAD"))
    return len(committed), len(uncommitted)


def run(args) -> int:
    ws = Workspace.from_args(args)
    cfg = ws.config["ci"]
    fail_on = args.fail_on or cfg["fail_on"]
    base = args.base if args.base is not None else cfg["base"]
    threshold = args.fail_under if args.fail_under is not None else cfg.get("coverage_fail_under")
    if threshold is not None and not 0 <= threshold <= 100:
        raise UsageError("--fail-under must be between 0 and 100")
    known = read_baseline(args.baseline) if args.baseline is not None else None
    require_work_tree(ws.root, "ci")
    base = commit_ref(ws.root, base, origin="flag" if args.base is not None else "config")
    base_commit = commit_sha(ws.root, base)

    findings = lint_registry(ws)
    rows, fresh = _marked(findings, known)
    summary = severity_counts(findings)
    if known is not None:
        summary["known"] = len(findings) - len(fresh)
    steps = [{"name": "lint", "status": "failed" if failing(fresh, fail_on) else "passed",
              "summary": summary, "findings": rows}]
    drift, changed = drift_report(ws, base, findings)
    rows, fresh = _marked(drift, known)
    status = ("no-changes" if not changed["files"] else
              "failed" if failing(fresh, fail_on) else "passed")
    committed, uncommitted = split_change(ws.root, base, changed["files"])
    summary = {"base": base, "files": len(changed["files"]),
               "committed": committed, "uncommitted": uncommitted,
               "modules": changed["modules"], **severity_counts(drift)}
    if known is not None:
        summary["known"] = len(drift) - len(fresh)
    steps.append({"name": "drift", "status": status, "summary": summary, "findings": rows})
    report = coverage_report(ws, repo_files(ws.root))
    status = ("report-only" if threshold is None else
              "failed" if percent(report["share"]) < threshold else "passed")
    steps.append({"name": "coverage", "status": status,
                  "summary": {"share": report["share"], "mapped": report["mapped"],
                              "total": report["total"], "unmapped": len(report["unmapped"]),
                              "fail_under": threshold}})
    notes = [NOTHING_TO_COMPARE] if not changed["files"] and base == "HEAD" else []
    notes += base_notes(ws.root, base, base_commit)
    failed = any(s["status"] == "failed" for s in steps)
    data = {"base": base, "base_commit": base_commit, "fail_on": fail_on, "steps": steps,
            "failed": failed, "notes": notes}
    if known is not None:
        data["baseline"] = args.baseline
    emit("ci", data, args.json, lambda d: _render(d, report["unmapped"]))
    return EXIT_FINDINGS if failed else EXIT_OK


SHORT = 12  # the hash prefix the text prints


def base_notes(root, base: str, commit: str) -> list[str]:
    """A note when the commit `base` names is not HEAD or one of its ancestors: drift since it
    also counts what `base` changed that HEAD lacks (a target branch that moved on) — on a
    branch the base is the merge base, which the note names."""
    point = branch_point(root, base)
    if point is None:
        return []
    fix = (f"on a branch, pass its merge base: git merge-base {base} HEAD ({point[:SHORT]})"
           if point else "this clone is shallow: fetch the history first (git fetch "
           "--unshallow; in CI a full checkout) to find the merge base" if is_shallow(root)
           else f"{base} and HEAD share no history")
    return [f"--base {base} ({commit[:SHORT]}) is not an ancestor of HEAD: the drift also "
            f"counts what {base} changed that HEAD lacks — {fix}"]


def _summary(step: dict, d: dict) -> str:
    s = step["summary"]
    counts = f"{s.get('error')} error(s), {s.get('warning')} warning(s), {s.get('info')} info"
    if step["status"] == "failed" and step["name"] in ("lint", "drift"):
        counts += f" — fails at {d['fail_on']}"
    if step["name"] == "lint":
        return counts
    if step["name"] == "drift":
        since = s["base"] if d["base_commit"].startswith(s["base"]) else \
            f"{s['base']} at {d['base_commit'][:SHORT]}"  # a hash base is not repeated
        if step["status"] == "no-changes":
            return f"no changed files since {since}"
        return (f"{s['files']} file(s) changed since {since} ({s['committed']} committed, "
                f"{s['uncommitted']} uncommitted): {counts}")
    gate = "" if s["fail_under"] is None else f", fail-under {s['fail_under']:g} %"
    return f"share {s['share']} ({percent(s['share'])} %), {s['unmapped']} unmapped{gate}"


UNMAPPED_SHOWN = 5


def _render(d, unmapped: list[str]) -> None:
    for step in d["steps"]:
        n_known = step["summary"].get("known", 0) if step["name"] != "coverage" else 0
        mark = f" ({n_known} known from the baseline)" if n_known else ""
        print(f"{step['name']:<9} {step['status']:<12} {_summary(step, d)}{mark}")
        if step["status"] == "failed":
            if step["name"] == "coverage":
                for f in unmapped[:UNMAPPED_SHOWN]:
                    print(f"  {f}")
                print("  run segmently-modules coverage for the full list")
            else:
                for f in step.get("findings", []):
                    where = f"  ({f['path']})" if f["path"] else ""
                    tag = " (known)" if f.get("known") else ""
                    print(f"  {f['severity'].upper():<7} {f['code']} {f['module']}: "
                          f"{f['message']}{where}{tag}")
    for note in d["notes"]:
        print(f"note: {note}")
    print(f"ci: {'failed' if d['failed'] else 'passed'}")
