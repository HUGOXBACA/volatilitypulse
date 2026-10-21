"""VolPulse quantitative analytics engine.

The service consumes normalised quotes from the broker and turns them into
the products the desk cares about:

* implied volatility surfaces (see :mod:`volpulse_analytics.surfaces`),
* portfolio Greeks (see :mod:`volpulse_analytics.greeks`),
* mispricing signals (see :mod:`volpulse_analytics.signals`),
* and the persistence of all of the above (see
  :mod:`volpulse_analytics.persistence`).

The shared domain types and provider clients live in the ``volpulse_core``
package, which is a separate distribution so that the ingestion tooling can
reuse them without pulling in the analytics stack.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
