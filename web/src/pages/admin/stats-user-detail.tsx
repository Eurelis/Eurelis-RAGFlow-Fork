// Eurelis — Page de détail des statistiques par utilisateur (admin).
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import dayjs from 'dayjs';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import { keepPreviousData, useQuery } from '@tanstack/react-query';

import type { StatsTimeseriesBySourcePoint } from '@/services/admin-stats-service';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import Spotlight from '@/components/spotlight';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Routes } from '@/routes';
import {
  getStatsBreakdown,
  getStatsSources,
  getStatsTimeseries,
  getStatsUserDetail,
} from '@/services/admin-stats-service';

const PRESET_OPTIONS = [
  { labelKey: 'stats.thisWeek', value: 'week' },
  { labelKey: 'stats.thisMonth', value: 'month' },
  { labelKey: 'stats.last12Months', value: '12months' },
] as const;

type Preset = (typeof PRESET_OPTIONS)[number]['value'];

function presetToDates(preset: Preset): { fromDate: string; toDate: string } {
  const today = dayjs().format('YYYY-MM-DD');
  if (preset === 'week') {
    return {
      fromDate: dayjs().startOf('week').format('YYYY-MM-DD'),
      toDate: today,
    };
  }
  if (preset === 'month') {
    return {
      fromDate: dayjs().startOf('month').format('YYYY-MM-DD'),
      toDate: today,
    };
  }
  return {
    fromDate: dayjs().subtract(12, 'month').format('YYYY-MM-DD'),
    toDate: today,
  };
}

function formatSourceLabel(source: string): string {
  return source.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const SOURCE_COLORS: Record<string, string> = {
  chat: '#6366f1',
  search: '#ec4899',
  agent: '#06b6d4',
  ingestion: '#f59e0b',
};
const FALLBACK_COLORS = ['#10b981', '#a855f7', '#84cc16', '#ef4444'];
function sourceColor(source: string, idx: number): string {
  return SOURCE_COLORS[source] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
}

const TYPE_COLORS: Record<string, string> = {
  llm: '#3b82f6',
  embedding: '#14b8a6',
};
function typeColor(type: string): string {
  return TYPE_COLORS[type] ?? '#94a3b8';
}

function pivotBySource(rows: StatsTimeseriesBySourcePoint[]): {
  pivoted: Record<string, number | string>[];
  sources: string[];
} {
  const periodMap = new Map<string, Record<string, number | string>>();
  const sourcesSet = new Set<string>();
  for (const row of rows) {
    sourcesSet.add(row.source);
    if (!periodMap.has(row.period))
      periodMap.set(row.period, { period: row.period });
    periodMap.get(row.period)![row.source] = row.tokens;
  }
  return {
    pivoted: Array.from(periodMap.values()),
    sources: Array.from(sourcesSet).sort(),
  };
}

const UserDetailKeys = {
  detail: (
    userEmail: string,
    fromDate: string,
    toDate: string,
    source: string,
    type: string,
  ) =>
    ['admin/stats/users', userEmail, fromDate, toDate, source, type] as const,
  timeseries: (
    userId: string,
    fromDate: string,
    toDate: string,
    source: string,
    type: string,
  ) =>
    [
      'admin/stats/timeseries/by-source',
      userId,
      fromDate,
      toDate,
      source,
      type,
    ] as const,
  modelBreakdown: (
    userId: string,
    fromDate: string,
    toDate: string,
    source: string,
    type: string,
  ) =>
    [
      'admin/stats/breakdown/model',
      userId,
      fromDate,
      toDate,
      source,
      type,
    ] as const,
  sources: () => ['admin/stats/sources'] as const,
};

const TOOLTIP_STYLE = {
  background: 'rgb(var(--bg-base))',
  border: '1px solid rgb(var(--border-button))',
  borderRadius: 8,
};

const TICK_STYLE = { fontSize: 11, fill: 'rgb(var(--text-secondary))' };
const LABEL_STYLE = { fontSize: 11, fill: 'rgb(var(--text-secondary))' };

export default function AdminStatsUserDetail() {
  const { t } = useTranslation();
  const { userEmail = '' } = useParams<{ userEmail: string }>();
  const navigate = useNavigate();
  const [preset, setPreset] = useState<Preset>('month');
  const [sources, setSources] = useState<string[]>([]);
  const [types, setTypes] = useState<string[]>([]);

  const { fromDate, toDate } = useMemo(() => presetToDates(preset), [preset]);
  const sourceFilter = sources.length > 0 ? sources : undefined;
  const sourceKey = sources.join(',');
  const typeFilter = types.length > 0 ? types : undefined;
  const typeKey = types.join(',');

  const { data: dimensionsData } = useQuery({
    queryKey: UserDetailKeys.sources(),
    queryFn: async () => (await getStatsSources()).data.data,
    staleTime: Infinity,
    retry: false,
  });
  const sourcesData = dimensionsData?.sources;
  const typesData = dimensionsData?.types;

  const { data } = useQuery({
    queryKey: UserDetailKeys.detail(
      userEmail,
      fromDate,
      toDate,
      sourceKey,
      typeKey,
    ),
    queryFn: async () =>
      (
        await getStatsUserDetail(userEmail, {
          fromDate,
          toDate,
          source: sourceFilter,
          type: typeFilter,
        })
      ).data.data,
    placeholderData: keepPreviousData,
    retry: false,
    enabled: !!userEmail,
  });

  const userId = data?.user_id ?? '';

  const { data: timeseriesData } = useQuery({
    queryKey: UserDetailKeys.timeseries(
      userId,
      fromDate,
      toDate,
      sourceKey,
      typeKey,
    ),
    queryFn: async () =>
      (
        await getStatsTimeseries({
          fromDate,
          toDate,
          userId,
          source: sourceFilter,
          type: typeFilter,
          bySource: true,
        })
      ).data.data,
    placeholderData: keepPreviousData,
    retry: false,
    enabled: !!userId,
  });

  const { data: modelBreakdown } = useQuery({
    queryKey: UserDetailKeys.modelBreakdown(
      userId,
      fromDate,
      toDate,
      sourceKey,
      typeKey,
    ),
    queryFn: async () =>
      (
        await getStatsBreakdown({
          fromDate,
          toDate,
          groupBy: 'model',
          userId,
          source: sourceFilter,
          type: typeFilter,
        })
      ).data.data,
    placeholderData: keepPreviousData,
    retry: false,
    enabled: !!userId,
  });

  const [resourceQuery, setResourceQuery] = useState('');
  const totals = data?.totals ?? { sessions: 0, tokens: 0, avg_duration_ms: 0 };
  const byUsage = data?.by_usage ?? [];
  const filteredByUsage = useMemo(() => {
    const q = resourceQuery.trim().toLowerCase();
    return q
      ? byUsage.filter((u) => u.label.toLowerCase().includes(q))
      : byUsage;
  }, [byUsage, resourceQuery]);
  const modelItems = (modelBreakdown?.items ?? []).slice(0, 10);

  const rawSeries = (timeseriesData?.series ??
    []) as StatsTimeseriesBySourcePoint[];
  const { pivoted: series, sources: seriesSources } = useMemo(
    () => pivotBySource(rawSeries),
    [rawSeries],
  );

  return (
    <Card className="!shadow-none relative h-full border-0.5 border-border-button bg-transparent rounded-xl overflow-x-hidden overflow-y-auto">
      <Spotlight />

      <CardContent className="p-6 space-y-6">
        {/* Header + Controls */}
        <div className="flex items-center gap-4 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(Routes.AdminStats)}
          >
            {t('stats.back')}
          </Button>
          <h2 className="text-lg font-semibold">{data?.email ?? userEmail}</h2>
          <div className="ml-auto flex items-center gap-2 flex-wrap">
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 min-w-36 justify-start font-normal"
                >
                  {sources.length === 0
                    ? t('stats.allSources')
                    : sources.map(formatSourceLabel).join(', ')}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-52 p-2" align="end">
                <div className="space-y-1">
                  <button
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent"
                    onClick={() => setSources([])}
                  >
                    <Checkbox checked={sources.length === 0} />
                    {t('stats.allSources')}
                  </button>
                  {(sourcesData ?? []).map((s, idx) => (
                    <button
                      key={s}
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent"
                      onClick={() =>
                        setSources((prev) =>
                          prev.includes(s)
                            ? prev.filter((x) => x !== s)
                            : [...prev, s],
                        )
                      }
                    >
                      <Checkbox checked={sources.includes(s)} />
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ background: sourceColor(s, idx) }}
                      />
                      {formatSourceLabel(s)}
                    </button>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 min-w-36 justify-start font-normal"
                >
                  {types.length === 0
                    ? t('stats.allTypes')
                    : types.map(formatSourceLabel).join(', ')}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-52 p-2" align="end">
                <div className="space-y-1">
                  <button
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent"
                    onClick={() => setTypes([])}
                  >
                    <Checkbox checked={types.length === 0} />
                    {t('stats.allTypes')}
                  </button>
                  {(typesData ?? []).map((s) => (
                    <button
                      key={s}
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent"
                      onClick={() =>
                        setTypes((prev) =>
                          prev.includes(s)
                            ? prev.filter((x) => x !== s)
                            : [...prev, s],
                        )
                      }
                    >
                      <Checkbox checked={types.includes(s)} />
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ background: typeColor(s) }}
                      />
                      {formatSourceLabel(s)}
                    </button>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
            <div className="flex gap-1">
              {PRESET_OPTIONS.map((opt) => (
                <Button
                  key={opt.value}
                  size="sm"
                  variant={preset === opt.value ? 'default' : 'outline'}
                  onClick={() => setPreset(opt.value)}
                >
                  {t(opt.labelKey)}
                </Button>
              ))}
            </div>
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-text-secondary">
                {t('stats.sessions')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{totals.sessions}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-text-secondary">
                {t('stats.totalTokens')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">
                {(totals.tokens / 1000).toFixed(1)}k
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-text-secondary">
                {t('stats.avgDuration')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">
                {(totals.avg_duration_ms / 1000).toFixed(1)}s
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Token consumption (stacked by source) + Top models */}
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('stats.tokenConsumption')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={series}
                  margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="period" tick={TICK_STYLE} />
                  <YAxis
                    tick={TICK_STYLE}
                    tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                  />
                  <Tooltip
                    formatter={(v: number, name: string) => [
                      `${(v / 1000).toFixed(1)}k`,
                      formatSourceLabel(name),
                    ]}
                    contentStyle={TOOLTIP_STYLE}
                  />
                  <Legend
                    formatter={(value) => formatSourceLabel(value)}
                    wrapperStyle={{ fontSize: 11 }}
                  />
                  {seriesSources.map((src, idx) => (
                    <Bar
                      key={src}
                      dataKey={src}
                      stackId="tokens"
                      fill={sourceColor(src, idx)}
                      radius={
                        idx === seriesSources.length - 1
                          ? [3, 3, 0, 0]
                          : undefined
                      }
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('stats.topModels')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  layout="vertical"
                  data={modelItems}
                  margin={{ top: 0, right: 40, left: 0, bottom: 0 }}
                >
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={100}
                    tick={TICK_STYLE}
                  />
                  <Tooltip
                    formatter={(v: number) => [
                      `${(v / 1000).toFixed(1)}k`,
                      t('stats.tokens'),
                    ]}
                    contentStyle={TOOLTIP_STYLE}
                  />
                  <Bar dataKey="tokens" radius={[0, 3, 3, 0]}>
                    {modelItems.map((entry, i) => (
                      <Cell key={i} fill={typeColor(entry.token_type ?? '')} />
                    ))}
                    <LabelList
                      dataKey="tokens"
                      position="right"
                      formatter={(v: number) =>
                        v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
                      }
                      style={LABEL_STYLE}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        {/* By resource — sessions + tokens */}
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('stats.byDialogSessions')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer
                width="100%"
                height={Math.max(160, byUsage.length * 28)}
              >
                <BarChart
                  layout="vertical"
                  data={byUsage}
                  margin={{ top: 0, right: 40, left: 0, bottom: 0 }}
                >
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={160}
                    tick={TICK_STYLE}
                  />
                  <Tooltip
                    formatter={(v: number) => [v, t('stats.sessions')]}
                    contentStyle={TOOLTIP_STYLE}
                  />
                  <Bar dataKey="sessions" fill="#6366f1" radius={[0, 3, 3, 0]}>
                    <LabelList
                      dataKey="sessions"
                      position="right"
                      style={LABEL_STYLE}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('stats.byDialogTokens')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer
                width="100%"
                height={Math.max(160, byUsage.length * 28)}
              >
                <BarChart
                  layout="vertical"
                  data={byUsage}
                  margin={{ top: 0, right: 40, left: 0, bottom: 0 }}
                >
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={160}
                    tick={TICK_STYLE}
                  />
                  <Tooltip
                    formatter={(v: number) => [
                      `${(v / 1000).toFixed(1)}k`,
                      t('stats.tokens'),
                    ]}
                    contentStyle={TOOLTIP_STYLE}
                  />
                  <Bar dataKey="tokens" fill="#6366f1" radius={[0, 3, 3, 0]}>
                    <LabelList
                      dataKey="tokens"
                      position="right"
                      formatter={(v: number) =>
                        v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
                      }
                      style={LABEL_STYLE}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        {/* Resource detail table */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-4">
              <CardTitle className="text-base">
                {t('stats.consumptionByDialog', {
                  count: filteredByUsage.length,
                })}
              </CardTitle>
              <Input
                value={resourceQuery}
                onChange={(e) => setResourceQuery(e.target.value)}
                placeholder={t('stats.filterResource')}
                className="h-8 w-56"
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('stats.dialog')}</TableHead>
                  <TableHead className="text-right">
                    {t('stats.sessions')}
                  </TableHead>
                  <TableHead className="text-right">
                    {t('stats.tokens')}
                  </TableHead>
                  <TableHead className="text-right">
                    {t('stats.avgDuration')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredByUsage.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-center text-text-secondary py-8"
                    >
                      {t('stats.noActivity')}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredByUsage.map((u) => (
                    <TableRow key={u.resource_id}>
                      <TableCell className="font-medium">{u.label}</TableCell>
                      <TableCell className="text-right">{u.sessions}</TableCell>
                      <TableCell className="text-right">
                        {(u.tokens / 1000).toFixed(1)}k
                      </TableCell>
                      <TableCell className="text-right">
                        {(u.avg_duration_ms / 1000).toFixed(1)}s
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </CardContent>
    </Card>
  );
}
