"""The temporary public-install fallback must match the trust-core implementation."""

import unittest

from bio_sfm_designer.trust._split_ltt_compat import split_ltt_threshold as compat
from bio_sfm_trust import split_ltt_threshold as core


class SplitLTTCompatTests(unittest.TestCase):
    def test_compatibility_report_matches_trust_core(self):
        args = (
            [0.1] * 80 + [0.9] * 80,
            [0] * 80 + [1] * 80,
            [0.1] * 40 + [0.9] * 40,
            [0] * 40 + [1] * 40,
            0.2,
            0.1,
        )
        self.assertEqual(compat(*args), core(*args))

    def test_compatibility_refusal_matches_trust_core(self):
        args = (
            [0.1] * 20 + [0.9] * 20,
            [0] * 20 + [1] * 20,
            [0.1] * 10 + [0.9] * 10,
            [1] * 10 + [0] * 10,
            0.2,
            0.1,
        )
        self.assertEqual(compat(*args), core(*args))

    def test_exact_compatibility_report_matches_trust_core(self):
        args = (
            [0.1] * 30 + [0.9] * 30,
            [0] * 30 + [1] * 30,
            [0.1] * 22 + [0.9] * 8,
            [0] * 22 + [1] * 8,
            0.2,
            0.0125,
            "clopper_pearson",
        )
        self.assertEqual(compat(*args), core(*args))


if __name__ == "__main__":
    unittest.main()
