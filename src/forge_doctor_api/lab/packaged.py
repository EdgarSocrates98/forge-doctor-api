"""Packaged `_data/labs` corpus resolution for wheel/zipimport installs.

`as_file` materializes the corpus at a real path — `Path(__file__)` would
give a pseudo-path inside the zip under zipimport. The module-level
ExitStack keeps the path alive until process exit (no-op on an unpacked
wheel).
"""

from __future__ import annotations

import atexit
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

_RESOURCES = ExitStack()
atexit.register(_RESOURCES.close)


def packaged_labs_dir() -> Path | None:
    """Real path of the bundled `_data/labs` corpus, or None when the
    distribution carries none (e.g. an editable install without the
    force-included layer)."""
    traversable = files("forge_doctor_api").joinpath("_data", "labs")
    if not traversable.is_dir():
        return None
    return _RESOURCES.enter_context(as_file(traversable))
