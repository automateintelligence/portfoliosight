"""The first module a build's fork server imports, before NumPy (`engine/parallel.py`).

A process with threads must not fork, and two libraries start threads as soon as they are
loaded: a BLAS library its pool, and the jemalloc inside pyarrow (which pandas loads) a
background thread. With these settings the fork server loads both without them, so it forks its
workers from a single-threaded process. The workers inherit the settings: one BLAS thread is
what a build wants anyway, and jemalloc works the same without its background thread. Nothing
else imports this module: it changes the environment of the process that does.
"""

from __future__ import annotations

import os

SETTINGS = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "JE_ARROW_MALLOC_CONF": "background_thread:false",
}

os.environ.update(SETTINGS)
