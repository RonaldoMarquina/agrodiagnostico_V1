#!/usr/bin/env python3
import unittest

suite = unittest.defaultTestLoader.discover('tests/ci', pattern='test_*.py')
if suite.countTestCases() == 0:
    raise SystemExit('Empty CI test suite')
raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
