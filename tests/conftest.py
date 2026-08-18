"""
Shared pytest setup for the repo-level test tree (currently: fetcher/
parser tests - see tests/fetcher/).

Every module in fetcher/ imports its shared helpers with a bare
`from common import ...`, the same way it's invoked when run directly as a
script (`python fetcher/ark.py`), rather than as a package
(`fetcher/` has no __init__.py). Importing those modules under pytest
therefore requires fetcher/ itself on sys.path, exactly like running them
as scripts would - not just the repo root.
"""

import sys
from pathlib import Path

FETCHER_DIR = Path(__file__).resolve().parent.parent / "fetcher"
sys.path.insert(0, str(FETCHER_DIR))
