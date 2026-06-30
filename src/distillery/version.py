"""Single source of truth for the package version.

The version string is read by Hatchling at build time (see ``pyproject.toml``
``[tool.hatch.version]``) and re-exported from :mod:`distillery`.
"""

from __future__ import annotations

__version__ = "1.0.0"
