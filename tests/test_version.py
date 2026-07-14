import unittest

import sophyane
from sophyane.version import __version__


class VersionTests(unittest.TestCase):
    def test_version_single_source(self):
        self.assertEqual(sophyane.__version__, __version__)
        self.assertEqual(__version__, "16.0.2")


if __name__ == "__main__":
    unittest.main()
