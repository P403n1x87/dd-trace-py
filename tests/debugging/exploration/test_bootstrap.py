import os
from os.path import dirname

import pytest

from ddtrace.internal.compat import PY2


if PY2:
    OUT = """Enabling debugging exploration testing
========================== LineCoverage: probes stats ==========================

Installed probes: 0/0

================================ Line coverage =================================

Source                                                       Lines Covered
==========================================================================
No lines found
===================== DeterministicProfiler: probes stats ======================

Installed probes: 0/0

============================== Function coverage ===============================

No functions called
"""
else:
    OUT = """Enabling debugging exploration testing
===================== DeterministicProfiler: probes stats ======================

Installed probes: 0/0

============================== Function coverage ===============================

No functions called
========================== LineCoverage: probes stats ==========================

Installed probes: 0/0

================================ Line coverage =================================

Source                                                       Lines Covered
==========================================================================
No lines found
"""

if "PYTHONPATH" in os.environ:
    pythonpath = os.pathsep.join([dirname(__file__), os.environ["PYTHONPATH"]])
else:
    pythonpath = dirname(__file__)


@pytest.mark.subprocess(env={"PYTHONPATH": pythonpath}, out=OUT)
def test_exploration_bootstrap():
    # We test that we get the expected output from the exploration debuggers
    # and no errors when running the sitecustomize.py script.
    pass
