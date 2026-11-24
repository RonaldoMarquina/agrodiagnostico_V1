"""Unit tests for FakeAssistantAdapter, GeminiAdapter (httpx.MockTransport), and provider factory."""
import json
import unittest
import uuid

import httpx

from app.config import AssistantSettings
from app.domain.policy import ProviderOutputInvalidError
from app.providers.base import (
    ProviderConfigurationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SafeContext,
)
from app.providers.factory import build_provider, set_provider_override
from app.providers.fake import FakeAssistantAdapter
from app.providers.gemini import GeminiAdapter


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SafeContext(role="USER", correlation_id=str(uuid.uuid4()))

    def tearDown(self):
        set_provider_override(None)

    def test_fake_adapter_maps_spanish_requests_deterministically(self):
        adapter = FakeAssistantAdapter()
        cases = [
            ("Llévame a mi historial", "INTENT", "OPEN_HISTORY", {}),
            ("Quiero hacer un nuevo diagnóstico", "INTENT", "OPEN_NEW_DIAGNOSIS", {}),
            ("¿Qué significa no concluyente?", "INTENT", "EXPLAIN_DIAGNOSIS_STATUS", {"status": "NO_CONCLUYENTE"}),
            ("¿Qué significa la confianza?", "INTENT", "EXPLAIN_CONFIDENCE", {}),
            ("¿Cómo tomo una buena fotografía?", "INTENT", "EXPLAIN_PHOTO_GUIDELINES", {}),
            ("Quiero modificar mi perfil", "INTENT", "OPEN_PROFILE", {}),
            ("Abrir gestión de usuarios", "INTENT", "OPEN_USER_MANAGEMENT", {}),
            ("Abrir catálogo fitosanitario", "INTENT", "OPEN_PHYTOSANITARY_CATALOG", {}),
            ("Abrir módulo de recomendaciones", "INTENT", "OPEN_RECOMMENDATIONS", {}),
            ("Abrir supervisión de diagnósticos", "INTENT", "OPEN_DIAGNOSIS_SUPERVISION", {}),
            ("Abrir auditoría", "INTENT", "OPEN_AUDIT", {}),
            ("Abrir monitoreo", "INTENT", "OPEN_MONITORING", {}),
            ("Ver notificaciones", "INTENT", "OPEN_NOTIFICATIONS", {}),
            ("Ver mis resultados", "INTENT", "OPEN_RESULTS", {}),
            ("Necesito ayuda", "INTENT", "OPEN_HELP", {}),
            ("¿Cómo funciona la aplicación?", "INTENT", "EXPLAIN_APP_USAGE", {}),
            ("¿Qué enfermedad tiene mi hoja y qué dosis aplico?", "OUT_OF_SCOPE", None, {}),
            ("Hola, necesito algo", "CLARIFICATION_REQUIRED", None, {}),
        ]
        for msg, disp, intent, params in cases:
            with self.subTest(msg=msg):
                res = adapter.interpret(msg, self.ctx)
                self.assertEqual(res["disposition"], disp)
                self.assertEqual(res["intent"], intent)
                self.assertEqual(res["parameters"], params)

    def test_factory_never_falls_back_silently_from_gemini_to_fake(self):
        with self.assertRaises(ProviderUnavailableError):
            build_provider(AssistantSettings(enabled=False, provider="fake"))

        with self.assertRaises(ProviderConfigurationError):
            build_provider(AssistantSettings(enabled=True, provider="gemini", gemini_api_key=None))

        with self.assertRaises(ProviderConfigurationError):
            build_provider(AssistantSettings(enabled=True, provider="unknown"))

        fake = build_provider(AssistantSettings(enabled=True, provider="fake"))
        self.assertIsInstance(fake, FakeAssistantAdapter)

        real = build_provider(
            AssistantSettings(
                enabled=True,
                provider="gemini",
                gemini_api_key="AIzaSyFakeKeyForFactoryTest123456789",
                gemini_model="gemini-2.5-flash",
            )
        )
        self.assertIsInstance(real, GeminiAdapter)

    def test_gemini_adapter_structured_success_uses_header_not_query_string(self):
        captured = {}
        api_key = "AIzaSyFakeHeaderOnlyKey1234567890"

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            candidate_json = json.dumps(
                {
                    "disposition": "INTENT",
                    "intent": "OPEN_HISTORY",
                    "parameters": {"status": None},
                    "message": "Te llevo a tu historial.",
                }
            )
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": candidate_json}]}}]},
            )

        adapter = GeminiAdapter(
            api_key=api_key,
            model="gemini-2.5-flash",
            timeout_seconds=5.0,
            max_retries=0,
            transport=httpx.MockTransport(handler),
        )
        result = adapter.interpret("Llévame a mi historial", self.ctx)
        self.assertEqual(result["disposition"], "INTENT")
        self.assertEqual(result["intent"], "OPEN_HISTORY")
        self.assertEqual(result["parameters"], {})

        # API key ONLY in header, never in URL
        self.assertEqual(captured["headers"].get("x-goog-api-key"), api_key)
        self.assertNotIn(api_key, captured["url"])
        self.assertNotIn("key=", captured["url"])
        # Closed schema requested, no tools/JWT/email sent
        self.assertEqual(captured["body"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("responseSchema", captured["body"]["generationConfig"])
        self.assertNotIn("tools", captured["body"])

    def test_gemini_adapter_retries_transient_503_then_succeeds(self):
        attempts = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            attempts[0] += 1
            if attempts[0] == 1:
                return httpx.Response(503, json={"error": {"message": "overloaded"}})
            candidate_json = json.dumps(
                {"disposition": "CLARIFICATION_REQUIRED", "intent": None, "message": ""}
            )
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": candidate_json}]}}]},
            )

        adapter = GeminiAdapter(
            api_key="AIzaSyRetryKeyTest12345678901234",
            model="gemini-2.5-flash",
            timeout_seconds=5.0,
            max_retries=1,
            transport=httpx.MockTransport(handler),
            sleep_fn=lambda _: None,
        )
        result = adapter.interpret("Hola", self.ctx)
        self.assertEqual(attempts[0], 2)
        self.assertEqual(result["disposition"], "CLARIFICATION_REQUIRED")

    def test_gemini_adapter_timeout_malformed_and_error_never_leak_key(self):
        api_key = "AIzaSyNeverLeakThisKey1234567890"

        def timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        timeout_adapter = GeminiAdapter(
            api_key=api_key,
            model="gemini-2.5-flash",
            timeout_seconds=1.0,
            max_retries=0,
            transport=httpx.MockTransport(timeout_handler),
        )
        with self.assertRaises(ProviderTimeoutError) as ctx_timeout:
            timeout_adapter.interpret("Llévame a mi historial", self.ctx)
        self.assertNotIn(api_key, str(ctx_timeout.exception))

        def malformed_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "not valid json {"}]}}]},
            )

        malformed_adapter = GeminiAdapter(
            api_key=api_key,
            model="gemini-2.5-flash",
            timeout_seconds=2.0,
            max_retries=0,
            transport=httpx.MockTransport(malformed_handler),
        )
        with self.assertRaises(ProviderOutputInvalidError):
            malformed_adapter.interpret("Llévame a mi historial", self.ctx)

        def error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text=f"upstream denied key={api_key}")

        error_adapter = GeminiAdapter(
            api_key=api_key,
            model="gemini-2.5-flash",
            timeout_seconds=2.0,
            max_retries=0,
            transport=httpx.MockTransport(error_handler),
        )
        with self.assertRaises(ProviderUnavailableError) as ctx_err:
            error_adapter.interpret("Llévame a mi historial", self.ctx)
        self.assertNotIn(api_key, str(ctx_err.exception))


if __name__ == "__main__":
    unittest.main()
