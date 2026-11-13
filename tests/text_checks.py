import os
import unittest

text_test = unittest.skipUnless(
    os.environ.get("HARNESS_TEXT_TESTS") == "1",
    "wording check; set HARNESS_TEXT_TESTS=1 to run",
)
