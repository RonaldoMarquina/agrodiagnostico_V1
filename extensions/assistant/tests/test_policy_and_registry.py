"""Unit tests for closed intent registry, curated explanations, and independent RBAC policy (AT-01..AT-12, AT-17, AT-18)."""
import unittest
import uuid

from app.domain.policy import (
    AssistantForbiddenError,
    ProviderOutputInvalidError,
    validate_and_authorize_candidate,
)
from app.domain.registry import INTENT_REGISTRY, OFFICIAL_DIAGNOSIS_STATUSES
from app.infrastructure.tokens import Principal


class PolicyAndRegistryTests(unittest.TestCase):
    def setUp(self):
        self.user = Principal(id=uuid.uuid4(), role="USER", token_id=str(uuid.uuid4()))
        self.admin = Principal(id=uuid.uuid4(), role="ADMIN", token_id=str(uuid.uuid4()))
        self.req_id = str(uuid.uuid4())

    def test_registry_has_all_16_intents_available(self):
        self.assertEqual(len(INTENT_REGISTRY), 16)
        available = {k for k, v in INTENT_REGISTRY.items() if v.available}
        self.assertEqual(len(available), 16)
        self.assertTrue(INTENT_REGISTRY["OPEN_AUDIT"].available)
        self.assertTrue(INTENT_REGISTRY["OPEN_MONITORING"].available)

    def test_user_navigation_intents_succeed_without_mutation(self):
        # AT-01, AT-02, AT-06 + RESULTS, NOTIFICATIONS, HELP
        expected_targets = {
            "OPEN_NEW_DIAGNOSIS": "NEW_DIAGNOSIS",
            "OPEN_HISTORY": "HISTORY",
            "OPEN_RESULTS": "RESULTS",
            "OPEN_NOTIFICATIONS": "NOTIFICATIONS",
            "OPEN_PROFILE": "PROFILE",
            "OPEN_HELP": "HELP",
        }
        for intent, target in expected_targets.items():
            with self.subTest(intent=intent):
                resp = validate_and_authorize_candidate(
                    {"disposition": "INTENT", "intent": intent, "parameters": {}, "message": "untrusted"},
                    principal=self.user,
                    request_id=self.req_id,
                )
                self.assertEqual(resp.status, "SUCCESS")
                self.assertEqual(resp.intent, intent)
                self.assertIsNotNone(resp.action)
                self.assertEqual(resp.action.type, "NAVIGATE")
                self.assertEqual(resp.action.target, target)
                # Curated platform message replaces untrusted provider prose
                self.assertNotEqual(resp.message, "untrusted")

    def test_curated_explanations_have_no_action_and_no_clinical_certainty(self):
        # AT-03: NO_CONCLUYENTE
        resp_status = validate_and_authorize_candidate(
            {
                "disposition": "INTENT",
                "intent": "EXPLAIN_DIAGNOSIS_STATUS",
                "parameters": {"status": "NO_CONCLUYENTE"},
                "message": "100% seguro que es tizón",
            },
            principal=self.user,
            request_id=self.req_id,
        )
        self.assertEqual(resp_status.status, "SUCCESS")
        self.assertIsNone(resp_status.action)
        self.assertIn("NO_CONCLUYENTE", resp_status.message)
        self.assertNotIn("100%", resp_status.message)

        # All official statuses accepted
        for status_code in OFFICIAL_DIAGNOSIS_STATUSES:
            resp = validate_and_authorize_candidate(
                {"disposition": "INTENT", "intent": "EXPLAIN_DIAGNOSIS_STATUS", "parameters": {"status": status_code}},
                principal=self.user,
                request_id=self.req_id,
            )
            self.assertEqual(resp.status, "SUCCESS")
            self.assertIsNone(resp.action)
            self.assertIn(status_code, resp.message)

        # AT-04: Confidence explanation
        resp_conf = validate_and_authorize_candidate(
            {"disposition": "INTENT", "intent": "EXPLAIN_CONFIDENCE", "parameters": {}},
            principal=self.user,
            request_id=self.req_id,
        )
        self.assertEqual(resp_conf.status, "SUCCESS")
        self.assertIsNone(resp_conf.action)
        self.assertIn("No garantiza certeza", resp_conf.message)

        # AT-05: Photo guidelines
        resp_photo = validate_and_authorize_candidate(
            {"disposition": "INTENT", "intent": "EXPLAIN_PHOTO_GUIDELINES", "parameters": {}},
            principal=self.user,
            request_id=self.req_id,
        )
        self.assertEqual(resp_photo.status, "SUCCESS")
        self.assertIsNone(resp_photo.action)
        self.assertIn("JPEG, PNG o WebP", resp_photo.message)

        # App usage
        resp_usage = validate_and_authorize_candidate(
            {"disposition": "INTENT", "intent": "EXPLAIN_APP_USAGE", "parameters": {}},
            principal=self.user,
            request_id=self.req_id,
        )
        self.assertEqual(resp_usage.status, "SUCCESS")
        self.assertIsNone(resp_usage.action)

    def test_user_denied_all_admin_intents_even_when_provider_proposes_them(self):
        # AT-07, AT-10, AT-11
        admin_intents = [
            "OPEN_USER_MANAGEMENT",
            "OPEN_PHYTOSANITARY_CATALOG",
            "OPEN_RECOMMENDATIONS",
            "OPEN_DIAGNOSIS_SUPERVISION",
            "OPEN_AUDIT",
            "OPEN_MONITORING",
        ]
        for intent in admin_intents:
            with self.subTest(intent=intent), self.assertRaises(AssistantForbiddenError):
                validate_and_authorize_candidate(
                    {"disposition": "INTENT", "intent": intent, "parameters": {}},
                    principal=self.user,
                    request_id=self.req_id,
                )

    def test_admin_allowed_all_admin_intents_and_unavailable_target_returns_no_action(self):
        from unittest.mock import patch
        from app.domain.registry import IntentSpec

        # AT-08 + ADR-0016: All 6 admin navigation intents enabled for ADMIN
        for intent, target in [
            ("OPEN_USER_MANAGEMENT", "USER_MANAGEMENT"),
            ("OPEN_PHYTOSANITARY_CATALOG", "PHYTOSANITARY_CATALOG"),
            ("OPEN_RECOMMENDATIONS", "RECOMMENDATIONS"),
            ("OPEN_DIAGNOSIS_SUPERVISION", "DIAGNOSIS_SUPERVISION"),
            ("OPEN_AUDIT", "AUDIT"),
            ("OPEN_MONITORING", "MONITORING"),
        ]:
            resp = validate_and_authorize_candidate(
                {"disposition": "INTENT", "intent": intent, "parameters": {}},
                principal=self.admin,
                request_id=self.req_id,
            )
            self.assertEqual(resp.status, "SUCCESS")
            self.assertEqual(resp.action.target, target)

        # Regression: any intent marked available=False in registry never emits NAVIGATE
        unavailable_spec = IntentSpec(
            intent="OPEN_MONITORING",
            tool_name="open_monitoring",
            kind="NAVIGATE",
            target="MONITORING",
            allowed_roles=frozenset({"ADMIN"}),
            available=False,
            deferred_reason="monitoring_deferred",
        )
        patched_registry = dict(INTENT_REGISTRY)
        patched_registry["OPEN_MONITORING"] = unavailable_spec
        with patch("app.domain.policy.INTENT_REGISTRY", patched_registry):
            resp = validate_and_authorize_candidate(
                {"disposition": "INTENT", "intent": "OPEN_MONITORING", "parameters": {}},
                principal=self.admin,
                request_id=self.req_id,
            )
            self.assertEqual(resp.status, "OUT_OF_SCOPE")
            self.assertEqual(resp.intent, "OPEN_MONITORING")
            self.assertIsNone(resp.action)

    def test_clarification_and_out_of_scope_never_emit_action(self):
        # AT-17
        clarify = validate_and_authorize_candidate(
            {"disposition": "CLARIFICATION_REQUIRED", "intent": None, "parameters": {}, "message": ""},
            principal=self.user,
            request_id=self.req_id,
        )
        self.assertEqual(clarify.status, "CLARIFICATION_REQUIRED")
        self.assertIsNone(clarify.intent)
        self.assertIsNone(clarify.action)

        # AT-18
        oos = validate_and_authorize_candidate(
            {"disposition": "OUT_OF_SCOPE", "intent": None, "parameters": {}, "message": ""},
            principal=self.user,
            request_id=self.req_id,
        )
        self.assertEqual(oos.status, "OUT_OF_SCOPE")
        self.assertIsNone(oos.intent)
        self.assertIsNone(oos.action)

    def test_invalid_or_malicious_provider_outputs_are_rejected(self):
        # AT-12: Unknown intent, external URL, SQL, arbitrary diagnosis_id, extra fields, bad status
        bad_candidates = [
            "not-a-dict",
            {"disposition": "INTENT", "intent": "DELETE_ALL_USERS", "parameters": {}},
            {"disposition": "INTENT", "intent": "https://evil.example/phish", "parameters": {}},
            {"disposition": "INTENT", "intent": "OPEN_HISTORY", "parameters": {"url": "https://evil.example"}},
            {"disposition": "INTENT", "intent": "OPEN_RESULTS", "parameters": {"diagnosis_id": "11111111-1111-4111-8111-111111111111"}},
            {"disposition": "INTENT", "intent": "OPEN_HISTORY", "parameters": {"sql": "SELECT * FROM users"}},
            {"disposition": "INTENT", "intent": "OPEN_HISTORY", "parameters": {}, "role": "ADMIN"},
            {"disposition": "INTENT", "intent": "OPEN_HISTORY", "parameters": {}, "action": {"type": "NAVIGATE", "target": "USER_MANAGEMENT"}},
            {"disposition": "INTENT", "intent": "EXPLAIN_DIAGNOSIS_STATUS", "parameters": {"status": "TIZON_CONFIRMADO"}},
            {"disposition": "INTENT", "intent": "EXPLAIN_CONFIDENCE", "parameters": {"percent": 99}},
            {"disposition": "OUT_OF_SCOPE", "intent": "OPEN_HISTORY", "parameters": {}},
            {"disposition": "CLARIFICATION_REQUIRED", "intent": "OPEN_HELP", "parameters": {}},
        ]
        for raw in bad_candidates:
            with self.subTest(raw=raw), self.assertRaises(ProviderOutputInvalidError):
                validate_and_authorize_candidate(raw, principal=self.admin, request_id=self.req_id)


if __name__ == "__main__":
    unittest.main()
