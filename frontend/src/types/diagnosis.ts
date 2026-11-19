/**
 * Tipos contractuales para el recurso Diagnosis según OpenAPI y common.schema.json.
 */

export type DiagnosisStatus =
  | 'PENDIENTE'
  | 'PROCESANDO'
  | 'COMPLETADO'
  | 'NO_CONCLUYENTE'
  | 'FALLIDO'
  | 'CANCELADO';

export type CropCode = 'POTATO' | 'MAIZE';

export type ClassCode =
  | 'POTATO_HEALTHY'
  | 'POTATO_EARLY_BLIGHT'
  | 'POTATO_LATE_BLIGHT'
  | 'MAIZE_HEALTHY'
  | 'MAIZE_COMMON_RUST'
  | 'MAIZE_LEAF_BLIGHT'
  | 'MAIZE_GRAY_LEAF_SPOT';

export interface ModelMetadata {
  model_id: string;
  model_version: string;
  dataset_version: string;
}

export interface RecommendationSnapshot {
  catalog_version: string;
  recommendation_id?: string | null;
  text?: string | null;
}

export interface PolicySnapshot {
  policy_id: string;
  policy_version: string;
  policy_digest: string;
}

export interface DiagnosisResult {
  crop_code: CropCode;
  class_code: ClassCode;
  raw_score: number;
  /**
   * Confianza estimada calibrada por clase según la política activa.
   * Null o undefined en diagnósticos históricos previos al Incremento 4.
   */
  estimated_confidence?: number | null;
  model: ModelMetadata;
  /**
   * Snapshot inmutable de la política de publicación activa.
   * Null o undefined en diagnósticos históricos previos al Incremento 4.
   */
  policy_snapshot?: PolicySnapshot | null;
  recommendation: RecommendationSnapshot;
}

export interface DiagnosisDetail {
  id: string;
  status: DiagnosisStatus;
  created_at: string;
  updated_at: string;
  reason_code?: string | null;
  result?: DiagnosisResult;
}
