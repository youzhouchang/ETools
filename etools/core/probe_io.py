"""One lock for every pyOCD call.

pyOCD sessions are not thread-safe. Flash jobs, Lua scripts, RTT, SWV, the
variable monitor, and diagnosis all share the same probe, so each probe call
must hold this lock.
"""

from __future__ import annotations

import threading

PROBE_LOCK = threading.RLock()
