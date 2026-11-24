"""Deterministic Spanish fake provider for automated tests and controlled demos (VERIFIED_FAKE)."""
import re
from typing import Any, Dict, Optional
import unicodedata

from app.providers.base import SafeContext


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


def _detect_status_param(norm: str) -> Optional[str]:
    status_keywords = (
        ("NO_CONCLUYENTE", ("no concluyente", "no_concluyente", "inconcluyente")),
        ("PENDIENTE", ("pendiente",)),
        ("PROCESANDO", ("procesando", "en proceso")),
        ("COMPLETADO", ("completado",)),
        ("FALLIDO", ("fallido",)),
        ("CANCELADO", ("cancelado",)),
    )
    for code, keywords in status_keywords:
        if any(kw in norm for kw in keywords):
            return code
    return None


class FakeAssistantAdapter:
    """Deterministic local interpreter for testing; never used as a silent fallback in gemini mode."""

    provider_name = "fake"

    def interpret(self, message: str, safe_context: SafeContext) -> Dict[str, Any]:
        norm = _normalize(message)

        # Explicitly out-of-scope: phytosanitary diagnosis, treatments/doses, result/data mutations, SQL/code
        out_of_scope_markers = (
            "que enfermedad tiene",
            "identifica la enfermedad",
            "identifica que enfermedad",
            "identificar enfermedad",
            "diagnostica esta",
            "dime si tiene tizon",
            "que plaga tiene",
            "que fungicida",
            "que dosis",
            "receta un tratamiento",
            "cambia el resultado",
            "cambiar el resultado",
            "modifica el resultado",
            "cambia mi diagnostico",
            "aprobame el modelo",
            "activa el modelo real",
            "borra todos los usuarios",
            "elimina todos los",
            "ejecuta sql",
            "select * from",
            "drop table",
        )
        if any(marker in norm for marker in out_of_scope_markers):
            return {
                "disposition": "OUT_OF_SCOPE",
                "intent": None,
                "parameters": {},
                "message": "",
            }

        # Admin intents (proposed regardless of caller role so local RBAC enforces 403 independently)
        if any(kw in norm for kw in ("gestion de usuarios", "administrar usuarios", "panel de usuarios", "bloquear usuario", "ver usuarios")):
            return {"disposition": "INTENT", "intent": "OPEN_USER_MANAGEMENT", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("catalogo fitosanitario", "gestionar catalogo", "administrar catalogo", "catalogo de cultivos", "abrir catalogo")):
            return {"disposition": "INTENT", "intent": "OPEN_PHYTOSANITARY_CATALOG", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("gestionar recomendaciones", "administrar recomendaciones", "abrir recomendaciones", "modulo de recomendaciones")):
            return {"disposition": "INTENT", "intent": "OPEN_RECOMMENDATIONS", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("supervision de diagnosticos", "supervisar diagnosticos", "panel de diagnosticos", "todos los diagnosticos")):
            return {"disposition": "INTENT", "intent": "OPEN_DIAGNOSIS_SUPERVISION", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("auditoria", "registro de auditoria", "abrir auditoria")):
            return {"disposition": "INTENT", "intent": "OPEN_AUDIT", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("monitoreo", "metricas del sistema", "panel de monitoreo", "estado del modelo")):
            return {"disposition": "INTENT", "intent": "OPEN_MONITORING", "parameters": {}, "message": ""}

        # Explanations
        status_code = _detect_status_param(norm)
        if status_code and any(kw in norm for kw in ("que significa", "explica", "significa", "estado", "quiere decir")):
            return {
                "disposition": "INTENT",
                "intent": "EXPLAIN_DIAGNOSIS_STATUS",
                "parameters": {"status": status_code},
                "message": "",
            }
        if any(kw in norm for kw in ("estados del diagnostico", "que estados existen", "significado de los estados", "explica los estados")):
            return {"disposition": "INTENT", "intent": "EXPLAIN_DIAGNOSIS_STATUS", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("confianza", "puntaje", "score", "certeza")):
            return {"disposition": "INTENT", "intent": "EXPLAIN_CONFIDENCE", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("buena foto", "buena fotografia", "como tomo una", "como tomar una foto", "guia de fotografia", "guia de captura", "consejos para la foto")):
            return {"disposition": "INTENT", "intent": "EXPLAIN_PHOTO_GUIDELINES", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("como funciona", "como usar", "como uso", "para que sirve")):
            return {"disposition": "INTENT", "intent": "EXPLAIN_APP_USAGE", "parameters": {}, "message": ""}

        # User navigation intents
        if any(kw in norm for kw in ("nuevo diagnostico", "hacer un diagnostico", "iniciar diagnostico", "subir una foto", "subir foto", "cargar foto", "cargar imagen")):
            return {"disposition": "INTENT", "intent": "OPEN_NEW_DIAGNOSIS", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("historial", "mis diagnosticos")):
            return {"disposition": "INTENT", "intent": "OPEN_HISTORY", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("mis resultados", "ver resultados", "abrir resultados", "resultados")):
            return {"disposition": "INTENT", "intent": "OPEN_RESULTS", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("notificaciones", "avisos", "preferencias de correo")):
            return {"disposition": "INTENT", "intent": "OPEN_NOTIFICATIONS", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("mi perfil", "modificar mi perfil", "editar perfil", "abrir perfil", "perfil", "mi cuenta")):
            return {"disposition": "INTENT", "intent": "OPEN_PROFILE", "parameters": {}, "message": ""}
        if any(kw in norm for kw in ("ayuda", "soporte", "centro de ayuda")):
            return {"disposition": "INTENT", "intent": "OPEN_HELP", "parameters": {}, "message": ""}

        # Prompt injection attempting privilege escalation without a valid allowed intent
        if any(kw in norm for kw in ("ignora las instrucciones", "ignore previous", "soy admin", "dame permisos de admin", "system prompt")):
            return {
                "disposition": "OUT_OF_SCOPE",
                "intent": None,
                "parameters": {},
                "message": "",
            }

        # Ambiguous request
        return {
            "disposition": "CLARIFICATION_REQUIRED",
            "intent": None,
            "parameters": {},
            "message": "",
        }
