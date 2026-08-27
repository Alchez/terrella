"""Instrumentation for a running pass, and the one sub-package that is not a step in one.

Nothing here produces a deliverable. It sizes the memory cap a pass runs under from the body being
processed, samples the pass's cgroup while it runs, and decides when a run has done something worth
interrupting a human for.
"""
