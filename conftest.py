"""Pytest session setup.

The unit tests exercise pure logic, but importing most modules pulls in
``db.runtime``, whose connect helpers call ``require_activation()``. Without
these flags a bare checkout fails collection with ``ActivationRequired`` rather
than running the tests, which is why the suite could not run in CI.

Set before any test module is imported; the activation gate reads the
environment lazily, so this is enough to keep the product gate itself intact.
"""

import os

os.environ.setdefault("NCM_SKIP_ACTIVATION", "1")
os.environ.setdefault("NCM_BOOTSTRAP_ON_IMPORT", "0")
os.environ.setdefault("NCM_DISABLE_SCHEDULER", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "pytest-fixed-secret")
