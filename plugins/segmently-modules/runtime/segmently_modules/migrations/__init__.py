"""Registry migrations. Each `mNNN_<name>.py` module defines `ID`, `DESCRIPTION`,
`applies(raw) -> bool` (content-based: does this registry still have the old shape?) and
`apply(raw) -> list[str]` (mutates in place, returns human-readable notes). They run in ID
order; a migration that no longer applies is skipped, so re-running is a no-op."""
import importlib
import pkgutil


def entries(raw: dict):
    """(label, entry) for every module and child entry that is an object."""
    for name, entry in raw.get("modules", {}).items():
        if isinstance(entry, dict):
            yield name, entry
            subs = entry.get("submodules")
            for child, sub in (subs.items() if isinstance(subs, dict) else []):
                if isinstance(sub, dict):
                    yield f"{name}/{child}", sub


def all_migrations() -> list:
    names = sorted(m.name for m in pkgutil.iter_modules(__path__) if m.name[:1] == "m"
                   and m.name[1:4].isdigit())
    return [importlib.import_module(f"{__name__}.{n}") for n in names]
