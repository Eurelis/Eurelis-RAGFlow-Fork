// Eurelis — Fonctions de service pour la supervision admin des modèles par tenant.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import eurelisApi from '@/utils/eurelis-api';
import { request } from './admin-service';

type ResponseData<D = NonNullable<unknown>> = {
  code: number;
  message: string;
  data: D;
};

const { adminTenantModels, adminCompareTenantModels, adminCopyTenantModels } =
  eurelisApi;

// --- Shapes returned by the admin backend (admin_model_supervision.py) ---

export interface ModelInstance {
  provider_name: string;
  instance_name: string;
  status: string;
  has_api_key: boolean;
  api_key_hint: string | null;
  base_url: string;
}

export interface AddedModel {
  model_type: string[];
  name: string;
  provider_id: string;
  provider_name: string;
  instance_id: string;
  instance_name: string;
}

export interface ResolvedDefaultModel {
  model_provider: string;
  model_instance: string;
  model_name: string;
  model_type: string;
  enable: boolean;
}

export interface RawDefault {
  model_type: string;
  value: string;
  resolvable: boolean;
}

export interface TenantModelConfig {
  tenant_id: string;
  owner_email: string;
  instances: ModelInstance[];
  added_models: AddedModel[];
  default_models: ResolvedDefaultModel[];
  raw_defaults: RawDefault[];
}

export interface CompareTenantRef {
  tenant_id: string;
  owner_email: string;
}

export interface CompareInstanceRow {
  provider_name: string;
  instance_name: string;
  by_tenant: Record<
    string,
    {
      present: boolean;
      has_api_key: boolean;
      api_key_hint: string | null;
      base_url: string;
      status: string;
    }
  >;
}

export interface CompareModelRow {
  provider_name: string;
  instance_name: string;
  model_name: string;
  by_tenant: Record<string, { present: boolean; model_type: string[] }>;
}

export interface CompareDefaultRow {
  model_type: string;
  by_tenant: Record<string, { value: string; resolvable: boolean }>;
}

export interface CompareResult {
  tenants: CompareTenantRef[];
  instances: CompareInstanceRow[];
  models: CompareModelRow[];
  defaults: CompareDefaultRow[];
}

export interface CopySummary {
  providers_added: number;
  providers_existing: number;
  instances_added: number;
  instances_overwritten: number;
  models_copied: number;
  defaults_copied: { model_type: string; value: string }[];
}

// --- Service calls ---

export const getTenantModels = (tenantId: string) =>
  request.get<ResponseData<TenantModelConfig>>(adminTenantModels(tenantId));

export const compareTenantModels = (tenantIds: string[]) =>
  request.get<ResponseData<CompareResult>>(adminCompareTenantModels, {
    params: { tenant_ids: tenantIds.join(',') },
  });

export const copyTenantModels = (targetId: string, sourceTenantId: string) =>
  request.post<ResponseData<CopySummary>>(adminCopyTenantModels(targetId), {
    source_tenant_id: sourceTenantId,
  });
