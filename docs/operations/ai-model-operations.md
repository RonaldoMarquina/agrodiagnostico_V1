# Operación ML — no habilitada para usuarios

Estado 2026-10-15: G0/G1/G2/G3 pendientes. No activar ml-real: el worker rechaza ese modo hasta implementar el runtime real. No hay fallback al simulador.

El CLI de políticas permite dry-run/importación/activación/retiro auditados, pero las referencias textuales no son prueba de revisión humana. No importar políticas para fixtures en bases reales. Retirar una política histórica inactiva conserva el soporte de la activa. Las pruebas usan bases aisladas; esta corrección no ha modificado datos reales.

El catálogo no incluye un paquete aprobado de semillas. Las recomendaciones deben ser revisadas y publicadas por la API administrativa existente. La corrección no elimina recomendaciones que pudieran existir en bases de desarrollo: si se cargaron las semillas no acreditadas, requieren revisión y desactivación mediante el flujo administrativo.

La aceptación con mocks es solo técnica. No utilizarla para G3 ni citar sus tiempos como latencia de MobileNet/ResNet. La implementación de promoción de releases reales, entrenamiento y rollback integrado siguen pendientes en el cambio OpenSpec.
