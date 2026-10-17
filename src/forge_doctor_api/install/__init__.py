"""Portable install lifecycle for Forge Doctor API.

Implements the shared ``forge/*`` installation contract v1 over the vendored
installkit (``forge_doctor_api._installkit``): scoped targets, approval
gating, managed ledger, receipts, drift repair and uninstall.

This package is the sanctioned host-integration boundary — it owns the only
``os``/``subprocess`` surface in ``src/`` (allowlisted in
``tests/test_boundary.py``) and is reachable solely through
``forge_doctor_api.cli.install_cmd``; the scan/engine path never imports it.

The checkout-level adapter (``scripts/forge_install.py``) remains for
bare-check-out installs before the wheel exists; both entrypoints drive the
same vendored engine and emit identical receipts.
"""

from __future__ import annotations

__all__ = ["service"]
