"""Treating everything from outside this lane as data.

`untrusted` is the structural layer: third-party strings are rendered so they
cannot escape the cell they are in. `detect` notices when one of them tried.

Neither is the security boundary. `agent/model/validation.py` and the three
allowlists behind it are, and `agent/README.md` says so in as many words —
a prompt-injection filter *treated* as the boundary is itself the vulnerability.
"""

from .detect import Finding, InjectionDetector, InjectionReport, scan
from .untrusted import UNTRUSTED_PREAMBLE, flagged, sanitize

__all__ = [
    "Finding",
    "InjectionDetector",
    "InjectionReport",
    "UNTRUSTED_PREAMBLE",
    "flagged",
    "sanitize",
    "scan",
]
