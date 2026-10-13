"""Layered config merge (BMAD-style semantics).

scalars: override wins · tables: deep merge · arrays of tables that all carry "id":
merge by id (matching ids deep-merge in place, new ids append) · other arrays: append +
dedupe, base order first. An override can never delete a base item; disable instead.
"""


def _all_keyed(items) -> bool:
    return bool(items) and all(isinstance(i, dict) and "id" in i for i in items)


def merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = merge(base[key], value) if key in base else value
        return out
    if isinstance(base, list) and isinstance(override, list):
        if _all_keyed(base) and _all_keyed(override):
            out = [dict(i) for i in base]
            index = {item["id"]: n for n, item in enumerate(out)}
            for item in override:
                if item["id"] in index:
                    out[index[item["id"]]] = merge(out[index[item["id"]]], item)
                else:
                    index[item["id"]] = len(out)
                    out.append(item)
            return out
        out = list(base)
        for item in override:
            if item not in out:
                out.append(item)
        return out
    return override


def merge_layers(layers: list[dict]) -> dict:
    result: dict = {}
    for layer in layers:
        result = merge(result, layer)
    return result
