// Eurelis — Service pour les statistiques de consommation de l'utilisateur courant.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import eurelisApi from '@/utils/eurelis-api';
import request from '@/utils/next-request';

export interface UserStatsTotals {
  sessions: number;
  tokens: number;
  avg_duration_ms: number;
}

export interface UserStatsByDay {
  date: string;
  sessions: number;
  tokens: number;
}

export interface UserStatsByUsage {
  resource_id: string;
  label: string;
  sessions: number;
  tokens: number;
  avg_duration_ms: number;
  pct_tokens: number;
  pct_sessions: number;
}

export interface UserStatsData {
  user_id: string;
  email: string;
  period: { from: string; to: string };
  totals: UserStatsTotals;
  by_day: UserStatsByDay[];
  by_usage: UserStatsByUsage[];
}

export interface SessionTurn {
  turn: number;
  tokens: number;
  duration_ms: number;
  model: string;
  provider: string;
  at: string;
}

export interface SessionTotals {
  turns: number;
  tokens: number;
  total_duration_ms: number;
  avg_duration_ms: number;
}

export interface UserStatsSession {
  object_id: string;
  resource_id: string;
  dialog_name: string;
  source: string;
  first_turn_at: string;
  last_turn_at: string;
  totals: SessionTotals;
  by_turn: SessionTurn[];
}

export interface IngestionByKb {
  kb_id: string;
  kb_name: string;
  tasks: number;
  tokens: number;
  pct_tokens: number;
}

export interface IngestionTotals {
  tasks: number;
  tokens: number;
  total_duration_ms: number;
}

export interface IngestionStats {
  period: { from: string; to: string };
  totals: IngestionTotals;
  by_kb: IngestionByKb[];
}

export interface StatsBreakdownItem {
  label: string;
  tokens: number;
  sessions: number;
  token_type?: string;
}

export interface StatsBreakdown {
  group_by: string;
  items: StatsBreakdownItem[];
}

export interface UserStatsTimeseriesBySourcePoint {
  period: string;
  source: string;
  tokens: number;
}

export interface UserStatsTimeseriesByTypePoint {
  period: string;
  token_type: string;
  tokens: number;
}

function serializeCsv(value?: string | string[]): string | undefined {
  if (!value) return undefined;
  return Array.isArray(value) ? value.join(',') : value;
}

// Backwards-compatible alias.
const serializeSource = serializeCsv;

export const getUserStatsMeSources = () =>
  request.get<{ data: { sources: string[]; types: string[] } }>(
    eurelisApi.userStatsMeSources,
  );

export const getUserStatsMeTimeseries = (
  params: {
    fromDate?: string;
    toDate?: string;
    granularity?: string;
    source?: string | string[];
    type?: string | string[];
    bySource?: boolean;
    byType?: boolean;
  } = {},
) =>
  request.get<{
    data: {
      granularity: string;
      series: (
        | UserStatsTimeseriesBySourcePoint
        | UserStatsTimeseriesByTypePoint
      )[];
    };
  }>(eurelisApi.userStatsMeTimeseries, {
    params: {
      from_date: params.fromDate,
      to_date: params.toDate,
      granularity: params.granularity,
      source: serializeCsv(params.source),
      type: serializeCsv(params.type),
      by_source: params.bySource ? 'true' : undefined,
      by_type: params.byType ? 'true' : undefined,
    },
  });

export const getUserStatsMeBreakdown = (
  params: {
    fromDate?: string;
    toDate?: string;
    groupBy?: string;
    source?: string | string[];
    type?: string | string[];
  } = {},
) =>
  request.get<{ data: StatsBreakdown }>(eurelisApi.userStatsMeBreakdown, {
    params: {
      from_date: params.fromDate,
      to_date: params.toDate,
      group_by: params.groupBy ?? 'model',
      source: serializeCsv(params.source),
      type: serializeCsv(params.type),
    },
  });

export const getUserStatsMeIngestion = (
  params: { fromDate?: string; toDate?: string } = {},
) =>
  request.get<{ data: IngestionStats }>(eurelisApi.userStatsMeIngestion, {
    params: { from_date: params.fromDate, to_date: params.toDate },
  });

export const getUserStatsMeSession = (sessionId: string) =>
  request.get<{ data: UserStatsSession }>(
    eurelisApi.userStatsMeSession(sessionId),
  );

export const getUserStatsMe = (
  params: {
    fromDate?: string;
    toDate?: string;
    source?: string | string[];
    type?: string | string[];
  } = {},
) =>
  request.get<{ data: UserStatsData }>(eurelisApi.userStatsMe, {
    params: {
      from_date: params.fromDate,
      to_date: params.toDate,
      source: serializeSource(params.source),
      type: serializeCsv(params.type),
    },
  });
