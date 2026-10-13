from segmently_modules.migrations import entries

ID = "002"
DESCRIPTION = "depends_on_modules (flat names) -> related_modules depends-on edges"


def applies(raw: dict) -> bool:
    return any(isinstance(e.get("depends_on_modules"), list) for _, e in entries(raw))


def apply(raw: dict) -> list[str]:
    notes = []
    for label, entry in entries(raw):
        names = entry.get("depends_on_modules")
        if not isinstance(names, list):
            continue
        edges = entry.setdefault("related_modules", [])
        if not isinstance(edges, list):
            notes.append(f"{label}: kept depends_on_modules — related_modules is not an array")
            continue
        have = {(e.get("module"), e.get("relation")) for e in edges if isinstance(e, dict)}
        for name in names:
            if isinstance(name, str) and (name, "depends-on") not in have:
                edges.append({"module": name, "relation": "depends-on",
                              "description": "Migrated from depends_on_modules"})
                have.add((name, "depends-on"))
        del entry["depends_on_modules"]
        notes.append(f"{label}: depends_on_modules -> {len(names)} related_modules edge(s)")
    return notes
