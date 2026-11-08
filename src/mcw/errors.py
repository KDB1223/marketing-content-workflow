"""Project errors. The CLI prints these and exits 2."""

from __future__ import annotations


class MCWError(Exception):
    """Expected failure: invalid brief, missing run, or model contract breach."""
