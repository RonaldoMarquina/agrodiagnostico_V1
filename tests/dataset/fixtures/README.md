# Fixtures sintéticos

`valid.csv` contiene siete filas de prueba, sin fotografías ni etiquetas revisadas. Cada sha256 corresponde al texto UTF-8 `synthetic-N` (N de 0 a 6), no a una imagen. Grupos e IDs son artificiales. `LicenseRef-Synthetic-Test-Only` identifica material de prueba propio, no permiso para datos de terceros.

`sources.json` solo se carga desde pruebas que activan explícitamente el modo sintético de la función; el CLI de manifiestos reales no permite esa excepción. Estas filas nunca se cuentan como dataset disponible, métrica ni consentimiento. Las variantes negativas se construyen en directorios temporales y se comprueba que el validador no las modifica.
