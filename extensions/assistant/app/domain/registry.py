"""Closed, immutable registry of assistant intents, navigation targets, roles, and availability (ADR-0015 D4)."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import FrozenSet, Literal, Mapping, Optional

Role = Literal["USER", "ADMIN"]
IntentKind = Literal["NAVIGATE", "EXPLAIN"]

USER_AND_ADMIN: FrozenSet[Role] = frozenset({"USER", "ADMIN"})
ADMIN_ONLY: FrozenSet[Role] = frozenset({"ADMIN"})

OFFICIAL_DIAGNOSIS_STATUSES: FrozenSet[str] = frozenset(
    {
        "PENDIENTE",
        "PROCESANDO",
        "COMPLETADO",
        "NO_CONCLUYENTE",
        "FALLIDO",
        "CANCELADO",
    }
)


@dataclass(frozen=True)
class IntentSpec:
    """Closed specification for a single registered assistant intent."""

    intent: str
    tool_name: str
    kind: IntentKind
    target: Optional[str]
    allowed_roles: FrozenSet[Role]
    available: bool
    nav_message: Optional[str] = None
    deferred_reason: Optional[str] = None


_RAW_REGISTRY = {
    # USER + ADMIN navigation (available)
    "OPEN_NEW_DIAGNOSIS": IntentSpec(
        intent="OPEN_NEW_DIAGNOSIS",
        tool_name="open_new_diagnosis",
        kind="NAVIGATE",
        target="NEW_DIAGNOSIS",
        allowed_roles=USER_AND_ADMIN,
        available=True,
        nav_message="Te llevo al formulario para iniciar un nuevo diagnóstico. Desde allí podrás cargar tu imagen cuando decidas enviarla.",
    ),
    "OPEN_HISTORY": IntentSpec(
        intent="OPEN_HISTORY",
        tool_name="open_history",
        kind="NAVIGATE",
        target="HISTORY",
        allowed_roles=USER_AND_ADMIN,
        available=True,
        nav_message="Te llevo a tu historial de diagnósticos.",
    ),
    "OPEN_RESULTS": IntentSpec(
        intent="OPEN_RESULTS",
        tool_name="open_results",
        kind="NAVIGATE",
        target="RESULTS",
        allowed_roles=USER_AND_ADMIN,
        available=True,
        nav_message="Te llevo a tus resultados de diagnósticos para que revises los detalles autorizados de tu cuenta.",
    ),
    "OPEN_NOTIFICATIONS": IntentSpec(
        intent="OPEN_NOTIFICATIONS",
        tool_name="open_notifications",
        kind="NAVIGATE",
        target="NOTIFICATIONS",
        allowed_roles=USER_AND_ADMIN,
        available=True,
        nav_message="Te llevo a tus notificaciones y preferencias de aviso.",
    ),
    "OPEN_PROFILE": IntentSpec(
        intent="OPEN_PROFILE",
        tool_name="open_profile",
        kind="NAVIGATE",
        target="PROFILE",
        allowed_roles=USER_AND_ADMIN,
        available=True,
        nav_message="Te llevo a tu perfil de usuario. Ningún dato se modifica hasta que tú guardes los cambios.",
    ),
    "OPEN_HELP": IntentSpec(
        intent="OPEN_HELP",
        tool_name="open_help",
        kind="NAVIGATE",
        target="HELP",
        allowed_roles=USER_AND_ADMIN,
        available=True,
        nav_message="Te llevo a la sección de ayuda de AgroDiagnóstico.",
    ),
    # USER + ADMIN approved explanations (no navigation action)
    "EXPLAIN_CONFIDENCE": IntentSpec(
        intent="EXPLAIN_CONFIDENCE",
        tool_name="explain_confidence",
        kind="EXPLAIN",
        target=None,
        allowed_roles=USER_AND_ADMIN,
        available=True,
    ),
    "EXPLAIN_DIAGNOSIS_STATUS": IntentSpec(
        intent="EXPLAIN_DIAGNOSIS_STATUS",
        tool_name="explain_diagnosis_status",
        kind="EXPLAIN",
        target=None,
        allowed_roles=USER_AND_ADMIN,
        available=True,
    ),
    "EXPLAIN_PHOTO_GUIDELINES": IntentSpec(
        intent="EXPLAIN_PHOTO_GUIDELINES",
        tool_name="explain_photo_guidelines",
        kind="EXPLAIN",
        target=None,
        allowed_roles=USER_AND_ADMIN,
        available=True,
    ),
    "EXPLAIN_APP_USAGE": IntentSpec(
        intent="EXPLAIN_APP_USAGE",
        tool_name="explain_app_usage",
        kind="EXPLAIN",
        target=None,
        allowed_roles=USER_AND_ADMIN,
        available=True,
    ),
    # ADMIN-only navigation (available)
    "OPEN_USER_MANAGEMENT": IntentSpec(
        intent="OPEN_USER_MANAGEMENT",
        tool_name="open_user_management",
        kind="NAVIGATE",
        target="USER_MANAGEMENT",
        allowed_roles=ADMIN_ONLY,
        available=True,
        nav_message="Te llevo a la gestión administrativa de usuarios.",
    ),
    "OPEN_PHYTOSANITARY_CATALOG": IntentSpec(
        intent="OPEN_PHYTOSANITARY_CATALOG",
        tool_name="open_phytosanitary_catalog",
        kind="NAVIGATE",
        target="PHYTOSANITARY_CATALOG",
        allowed_roles=ADMIN_ONLY,
        available=True,
        nav_message="Te llevo al catálogo fitosanitario administrativo.",
    ),
    "OPEN_RECOMMENDATIONS": IntentSpec(
        intent="OPEN_RECOMMENDATIONS",
        tool_name="open_recommendations",
        kind="NAVIGATE",
        target="RECOMMENDATIONS",
        allowed_roles=ADMIN_ONLY,
        available=True,
        nav_message="Te llevo a la gestión administrativa de recomendaciones aprobadas.",
    ),
    "OPEN_DIAGNOSIS_SUPERVISION": IntentSpec(
        intent="OPEN_DIAGNOSIS_SUPERVISION",
        tool_name="open_diagnosis_supervision",
        kind="NAVIGATE",
        target="DIAGNOSIS_SUPERVISION",
        allowed_roles=ADMIN_ONLY,
        available=True,
        nav_message="Te llevo a la vista de supervisión administrativa de diagnósticos.",
    ),
    # ADMIN-only navigation (explicitly deferred in contracts/deferred-operations.json)
    "OPEN_AUDIT": IntentSpec(
        intent="OPEN_AUDIT",
        tool_name="open_audit",
        kind="NAVIGATE",
        target="AUDIT",
        allowed_roles=ADMIN_ONLY,
        available=False,
        deferred_reason="audit_deferred",
    ),
    "OPEN_MONITORING": IntentSpec(
        intent="OPEN_MONITORING",
        tool_name="open_monitoring",
        kind="NAVIGATE",
        target="MONITORING",
        allowed_roles=ADMIN_ONLY,
        available=False,
        deferred_reason="monitoring_deferred",
    ),
}

INTENT_REGISTRY: Mapping[str, IntentSpec] = MappingProxyType(_RAW_REGISTRY)

ALLOWED_TARGETS: FrozenSet[str] = frozenset(
    spec.target for spec in INTENT_REGISTRY.values() if spec.target is not None and spec.available
)
