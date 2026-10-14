"""Third-party code the engine carries, unchanged, so that it needs nothing installed:

- `tomli/` — tomli 2.3.2 (MIT, `tomli/LICENSE`), the TOML 1.0 reader that became Python's own
  `tomllib` in 3.11; used only on Python 3.9 and 3.10 (`segmently_modules._toml`).
  From the PyPI sdist `tomli-2.3.2.tar.gz`, sha256
  ba6f699836c403252ae4a41ddaae9a30333bdac3fbb57b6ea28a50fffbb14d77, files `src/tomli/*.py`.
"""
