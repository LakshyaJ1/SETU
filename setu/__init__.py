"""SETU - Seamless Egomotion Tracking under Unavailable-GNSS.

Reference implementation of the estimation core described in ``docs/03-approach.md``.
This is the Python twin called for in ``docs/06-tech-stack.md`` 6.3: it exists to
make the physics falsifiable and the C++ port checkable, not to ship on a phone.

The one idea, from ``docs/03-approach.md`` 3.1:

    Stop integrating time. Start registering space.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
