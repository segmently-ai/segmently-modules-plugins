from segmently_modules.migrations import entries

ID = "001"
DESCRIPTION = "legacy context_paths / contextPaths / files -> context_files"
LEGACY = ("context_paths", "contextPaths", "files")


def applies(raw: dict) -> bool:
    return any(k in e for _, e in entries(raw) for k in LEGACY)


def apply(raw: dict) -> list[str]:
    notes = []
    for label, entry in entries(raw):
        for key in LEGACY:
            if key not in entry:
                continue
            if "context_files" in entry:
                notes.append(f"{label}: kept '{key}' — context_files already exists; reconcile by hand")
                continue
            if not isinstance(entry[key], dict):
                notes.append(f"{label}: kept '{key}' — not an object; reconcile by hand")
                continue
            items = list(entry.items())
            entry.clear()  # rebuild to keep the new key where the old one was
            entry.update((("context_files" if k == key else k), v) for k, v in items)
            notes.append(f"{label}: {key} -> context_files")
    return notes
