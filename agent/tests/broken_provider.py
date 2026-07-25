"""A module that raises on import.

Stands in for a neighbouring lane that is mid-edit when the harness happens to
look at it — a normal state during a 24-hour build with five instances pushing
concurrently. `test_providers.py` uses it to prove that such a lane degrades this
one to fixtures instead of taking the API down.
"""

raise RuntimeError("this lane is mid-edit and does not import cleanly")
