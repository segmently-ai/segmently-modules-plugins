"""The TOML reader: Python's own `tomllib` (Python 3.11 and newer), else the vendored
tomli 2.3.2 it came from (Python 3.9 and 3.10) — the same `load`, `loads` and `TOMLDecodeError`."""
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9, 3.10
    from segmently_modules._vendor import tomli as tomllib

__all__ = ["tomllib"]
