// Eurelis — Fonctions de service pour les statistiques de consommation admin.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import eurelisApi from '@/utils/eurelis-api';
import { request } from './admin-service';

type ResponseData<D = NonNullable<unknown>> = {
  code: number;
  message: string;
  data: D;
};

const {
  adminStatsUsers,
  adminStatsUserDetail,
  adminStatsTimeseries,
  adminStatsBreakdown,
  adminStatsSources,
} = eurelisApi;

export interface StatsUsersParams {
  fromDate?: string;
  toDate?: string;
  sortBy?: 'tokens' | 'sessions' | 'avg_duration_ms';
  limit?: number;
  source?: string | string[];
  type?: string | string[];
}

export interface StatsUserItem {
  user_id: string;
  email: string;
  sessions: number;
  tokens: number;
  avg_duration_ms: number;
  sources: string[];
}

export interface StatsTimeseriesPoint {
  period: string;
  sessions: number;
  tokens: number;
}

export interface StatsTimeseriesBySourcePoint {
  period: string;
  source: string;
  tokens: number;
}

export interface StatsTimeseriesByTypePoint {
  period: string;
  token_type: string;
  tokens: number;
}

export interface StatsBreakdownItem {
  label: string;
  provider?: string;
  sessions: number;
  tokens: number;
  pct_tokens: number;
  token_type?: string;
}

export interface StatsTimeseriesParams {
  fromDate?: string;
  toDate?: string;
  granularity?: 'day' | 'week' | 'month';
  userId?: string;
  source?: string | string[];
  type?: string | string[];
  bySource?: boolean;
  byType?: boolean;
}

export interface StatsBreakdownParams {
  fromDate?: string;
  toDate?: string;
  groupBy?: 'source' | 'type' | 'model' | 'provider' | 'dialog';
  userId?: string;
  source?: string | string[];
  type?: string | string[];
}

function serializeCsv(value?: string | string[]): string | undefined {
  if (!value) return undefined;
  return Array.isArray(value) ? value.join(',') : value;
}

// Backwards-compatible alias.
const serializeSource = serializeCsv;

export const getStatsUsers = (params: StatsUsersParams = {}) =>
  request.get<ResponseData<{ active_users: number; users: StatsUserItem[] }>>(
    adminStatsUsers,
    {
      params: {
        from_date: params.fromDate,
        to_date: params.toDate,
        sort_by: params.sortBy,
        limit: params.limit,
        source: serializeSource(params.source),
        type: serializeCsv(params.type),
      },
    },
  );

export const getStatsUserDetail = (
  userEmail: string,
  params: {
    fromDate?: string;
    toDate?: string;
    source?: string | string[];
    type?: string | string[];
  } = {},
) =>
  request.get<
    ResponseData<{
      user_id: string;
      email: string;
      period: { from: string; to: string };
      totals: { sessions: number; tokens: number; avg_duration_ms: number };
      by_day: Array<{ date: string; sessions: number; tokens: number }>;
      by_usage: Array<{
        resource_id: string;
        label: string;
        sessions: number;
        tokens: number;
        avg_duration_ms: number;
        pct_tokens: number;
        pct_sessions: number;
      }>;
    }>
  >(adminStatsUserDetail(userEmail), {
    params: {
      from_date: params.fromDate,
      to_date: params.toDate,
      source: serializeSource(params.source),
      type: serializeCsv(params.type),
    },
  });

export const getStatsTimeseries = (params: StatsTimeseriesParams = {}) =>
  request.get<
    ResponseData<{
      granularity: string;
      series: StatsTimeseriesPoint[] | StatsTimeseriesBySourcePoint[];
    }>
  >(adminStatsTimeseries, {
    params: {
      from_date: params.fromDate,
      to_date: params.toDate,
      granularity: params.granularity,
      user_id: params.userId,
      source: serializeSource(params.source),
      type: serializeCsv(params.type),
      by_source: params.bySource ? 'true' : undefined,
      by_type: params.byType ? 'true' : undefined,
    },
  });

export const getStatsSources = () =>
  request.get<ResponseData<{ sources: string[]; types: string[] }>>(
    adminStatsSources,
  );

export const getStatsBreakdown = (params: StatsBreakdownParams = {}) =>
  request.get<ResponseData<{ group_by: string; items: StatsBreakdownItem[] }>>(
    adminStatsBreakdown,
    {
      params: {
        from_date: params.fromDate,
        to_date: params.toDate,
        group_by: params.groupBy,
        user_id: params.userId,
        source: serializeSource(params.source),
        type: serializeCsv(params.type),
      },
    },
  );
