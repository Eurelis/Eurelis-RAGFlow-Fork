// Eurelis — URLs des endpoints spécifiques au fork Eurelis.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import { restAPIv1 } from './api';

const eurelisApi = {
  adminStatsUsers: `${restAPIv1}/admin/stats/users`,
  adminStatsUserDetail: (userEmail: string) =>
    `${restAPIv1}/admin/stats/users/${userEmail}`,
  adminStatsTimeseries: `${restAPIv1}/admin/stats/timeseries`,
  adminStatsBreakdown: `${restAPIv1}/admin/stats/breakdown`,
  adminStatsSources: `${restAPIv1}/admin/stats/sources`,
  userStatsMe: `${restAPIv1}/usage-stats/me`,
  userStatsMeSession: (sessionId: string) =>
    `${restAPIv1}/usage-stats/me/session/${sessionId}`,
  userStatsMeIngestion: `${restAPIv1}/usage-stats/me/ingestion`,
  userStatsMeBreakdown: `${restAPIv1}/usage-stats/me/breakdown`,
  userStatsMeTimeseries: `${restAPIv1}/usage-stats/me/timeseries`,
  userStatsMeSources: `${restAPIv1}/usage-stats/me/sources`,
  adminTenantModels: (tenantId: string) =>
    `${restAPIv1}/admin/tenants/${tenantId}/models`,
  adminCompareTenantModels: `${restAPIv1}/admin/tenants/models/compare`,
  adminCopyTenantModels: (targetId: string) =>
    `${restAPIv1}/admin/tenants/${targetId}/models/copy`,
};

export default eurelisApi;
