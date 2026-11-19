import type { DiagnosisDetail } from '../types/diagnosis';

export interface ApiClientOptions {
  baseUrl?: string;
  token?: string;
}

export class DiagnosisApiClient {
  private readonly baseUrl: string;
  private readonly token?: string;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? '';
    this.token = options.token;
  }

  async getDiagnosis(id: string, correlationId?: string): Promise<DiagnosisDetail> {
    const headers: Record<string, string> = {
      Accept: 'application/json',
    };
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }
    if (correlationId) {
      headers['X-Correlation-ID'] = correlationId;
    }

    const response = await fetch(`${this.baseUrl}/api/v1/diagnoses/${encodeURIComponent(id)}`, {
      method: 'GET',
      headers,
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(
        errorBody?.message ?? `Error al consultar diagnóstico: HTTP ${response.status}`,
      );
    }

    return (await response.json()) as DiagnosisDetail;
  }
}
