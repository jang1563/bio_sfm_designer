import unittest

from bio_sfm_designer.safety import check_label_integrity, parse_verdict


class ParseVerdictTests(unittest.TestCase):
    def test_leading_token_wins(self):
        self.assertEqual(parse_verdict("MATCH"), "MATCH")
        self.assertEqual(parse_verdict("MISMATCH — the sequence is a kinase, not a toxin"), "MISMATCH")
        self.assertEqual(parse_verdict("**Mismatch**"), "MISMATCH")  # markdown-stripped, case-insensitive

    def test_content_not_stop_reason(self):
        # leading MATCH wins even when MISMATCH appears later (we read the content verdict)
        self.assertEqual(parse_verdict("MATCH. (It is not a MISMATCH.)"), "MATCH")

    def test_fallback_search(self):
        self.assertEqual(parse_verdict("I judge this UNCERTAIN given the short sequence"), "UNCERTAIN")

    def test_unparseable(self):
        self.assertEqual(parse_verdict("the sequence looks fine to me"), "UNPARSEABLE")


class CheckLabelIntegrityTests(unittest.TestCase):
    def test_match_allows(self):
        v = check_label_integrity("ACDEFGHIK", "green fluorescent protein", provider=lambda p: "MATCH")
        self.assertTrue(v.allowed)
        self.assertEqual(v.source, "label_integrity")

    def test_mismatch_routes_to_expert(self):
        v = check_label_integrity("ACDEFGHIK", "benign reporter", provider=lambda p: "MISMATCH, this is a toxin")
        self.assertFalse(v.allowed)
        self.assertEqual(v.decision_class, "route_expert")

    def test_toxin_labeled_always_human_review(self):
        # even a MATCH provider cannot clear a toxin-labeled record
        v = check_label_integrity("ACDEFGHIK", "ricin", provider=lambda p: "MATCH", toxin_labeled=True)
        self.assertFalse(v.allowed)
        self.assertEqual(v.decision_class, "route_expert")

    def test_no_provider_routes_to_expert(self):
        v = check_label_integrity("ACDEFGHIK", "GFP", provider=None)
        self.assertFalse(v.allowed)

    def test_provider_error_routes_to_expert(self):
        def boom(p):
            raise RuntimeError("api down")
        v = check_label_integrity("ACDEFGHIK", "GFP", provider=boom)
        self.assertFalse(v.allowed)  # UNPARSEABLE -> human review


if __name__ == "__main__":
    unittest.main()
