"""Approved local Spanish explanations and safe system messages (INV-08, INV-10, ADR-0015 D4).

Sensitive explanations always come from curated, verifiable platform texts rather than
unconstrained provider prose, avoiding invented percentages, clinical certainty, or treatments.
"""
from typing import Dict, Optional

STATUS_EXPLANATIONS: Dict[str, str] = {
    "PENDIENTE": (
        "PENDIENTE significa que tu solicitud y fotografía fueron recibidas y guardadas "
        "correctamente, y esperan turno para iniciar el análisis técnico. Mientras esté en "
        "PENDIENTE aún puedes cancelar la solicitud."
    ),
    "PROCESANDO": (
        "PROCESANDO indica que el trabajador técnico ya tomó la solicitud y el análisis está "
        "en curso. En este estado la solicitud ya no puede cancelarse."
    ),
    "COMPLETADO": (
        "COMPLETADO indica que el análisis técnico terminó y cumplió los criterios de publicación "
        "vigentes, mostrando una orientación de apoyo vinculada al catálogo revisado. No constituye "
        "certeza absoluta ni reemplaza a un profesional agronómico."
    ),
    "NO_CONCLUYENTE": (
        "NO_CONCLUYENTE es un estado técnico (no una enfermedad) que indica que la plataforma no "
        "pudo emitir un resultado publicable con suficiente respaldo técnico, por ejemplo por baja "
        "confianza (LOW_CONFIDENCE), cultivo no soportado (UNSUPPORTED_CROP), imagen deficiente "
        "(BAD_IMAGE) o modelo/catálogo no habilitado para publicación. Puedes tomar una nueva "
        "fotografía siguiendo la guía o consultar a un especialista."
    ),
    "FALLIDO": (
        "FALLIDO indica que ocurrió un error técnico durante el procesamiento que impidió concluir "
        "el análisis (por ejemplo tiempo agotado o error de inferencia). Puedes intentar cargar una "
        "nueva solicitud más adelante."
    ),
    "CANCELADO": (
        "CANCELADO significa que detuviste la solicitud antes de que comenzara su procesamiento. "
        "Las solicitudes canceladas no se procesan ni generan avisos de finalización."
    ),
}

EXPLANATION_TEMPLATES: Dict[str, str] = {
    "EXPLAIN_CONFIDENCE": (
        "La confianza representa el grado de respaldo técnico del análisis automático frente a los "
        "umbrales de publicación configurados en AgroDiagnóstico. No garantiza certeza clínica ni "
        "sustituye la evaluación de un ingeniero agrónomo; cuando el respaldo es insuficiente o la "
        "política vigente no autoriza publicación, el diagnóstico se marca como NO_CONCLUYENTE."
    ),
    "EXPLAIN_DIAGNOSIS_STATUS": (
        "Los estados oficiales de un diagnóstico en AgroDiagnóstico son: PENDIENTE (en espera), "
        "PROCESANDO (análisis en curso), COMPLETADO (orientación publicada del catálogo revisado), "
        "NO_CONCLUYENTE (sin respaldo técnico suficiente para publicar, no es una clase de enfermedad), "
        "FALLIDO (error técnico) y CANCELADO (detenido por ti antes del procesamiento)."
    ),
    "EXPLAIN_PHOTO_GUIDELINES": (
        "Para tomar una buena fotografía agrícola: usa luz natural pareja evitando sombras fuertes "
        "o contraluz, enfoca con nitidez la hoja de papa o maíz mostrando claramente la zona de "
        "interés, evita movimiento o fondos saturados y sube un archivo JPEG, PNG o WebP de hasta "
        "10 MiB. Esta guía ayuda a mejorar la captura y no constituye un diagnóstico."
    ),
    "EXPLAIN_APP_USAGE": (
        "En AgroDiagnóstico puedes cargar fotografías de papa o maíz desde Nuevo diagnóstico, "
        "consultar el estado y detalle de tus solicitudes en Historial, revisar tus avisos y "
        "preferencias en Notificaciones y actualizar tu nombre visible en Perfil. El asistente "
        "te orienta y facilita la navegación, pero no realiza diagnósticos ni modifica tus datos."
    ),
}

DEFERRED_ADMIN_MESSAGES: Dict[str, str] = {
    "OPEN_AUDIT": (
        "El módulo administrativo de auditoría todavía está diferido y no se encuentra publicado "
        "en esta versión de AgroDiagnóstico, por lo que no es posible navegar hacia él."
    ),
    "OPEN_MONITORING": (
        "El módulo administrativo de monitoreo y métricas todavía está diferido y no se encuentra "
        "publicado en esta versión de AgroDiagnóstico, por lo que no es posible navegar hacia él."
    ),
}

CLARIFICATION_MESSAGE = (
    "No pude identificar con precisión qué necesitas. Indícame si deseas ir a una sección "
    "(por ejemplo historial, nuevo diagnóstico, perfil o notificaciones) o si quieres una "
    "explicación sobre estados, confianza, fotografía o uso de la aplicación."
)

OUT_OF_SCOPE_MESSAGE = (
    "Esa solicitud está fuera del alcance del asistente. No realizo diagnósticos fitosanitarios, "
    "no recomiendo dosis ni tratamientos y no modifico resultados, cuentas ni configuraciones. "
    "Utiliza el flujo oficial de diagnóstico o consulta a un profesional agronómico."
)


def get_approved_explanation(intent: str, status_code: Optional[str] = None) -> str:
    """Return curated Spanish explanation text for an EXPLAIN_* intent."""
    if intent == "EXPLAIN_DIAGNOSIS_STATUS" and status_code:
        return STATUS_EXPLANATIONS[status_code]
    return EXPLANATION_TEMPLATES[intent]


def get_deferred_message(intent: str) -> str:
    """Return safe non-actionable explanation for a deferred administrative intent."""
    return DEFERRED_ADMIN_MESSAGES.get(
        intent,
        "La sección solicitada aún no se encuentra disponible en esta versión de AgroDiagnóstico.",
    )
