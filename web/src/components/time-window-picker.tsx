// Eurelis — Sélecteur de fenêtre temporelle (granularité + navigation ◀▶ + plage personnalisée) pour les stats.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import dayjs, { type Dayjs } from 'dayjs';
import { CalendarIcon, ChevronLeft, ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DateRange } from 'react-day-picker';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

export type StatsGranularity = 'week' | 'month' | 'year' | 'custom';

export type StatsDateRange = { fromDate: string; toDate: string };

/**
 * Serialisable picker UI state — persist this (not just the derived range) to
 * restore the exact granularity/anchor/custom-range across mounts.
 */
export type TimeWindowState = {
  granularity: StatsGranularity;
  anchor: string; // ISO day (YYYY-MM-DD)
  customRange?: { from: string; to: string };
};

export function defaultTimeWindowState(): TimeWindowState {
  return { granularity: 'month', anchor: dayjs().format('YYYY-MM-DD') };
}

/**
 * Renders a timeseries "period" bucket for a chart axis/tooltip.
 * Week buckets arrive as "YYYY-WW" (MySQL %u) → "YYYY - Sww";
 * day ("YYYY-MM-DD") and month ("YYYY-MM") buckets are returned unchanged.
 */
export function formatPeriodLabel(period: string, granularity?: string): string {
  if (granularity === 'week') {
    const [year, week] = period.split('-');
    if (year && week) return `${year} - S${week}`;
  }
  return period;
}

const DAY = 'YYYY-MM-DD';

const GRANULARITY_OPTIONS: { value: StatsGranularity; labelKey: string }[] = [
  { value: 'week', labelKey: 'stats.week' },
  { value: 'month', labelKey: 'stats.month' },
  { value: 'year', labelKey: 'stats.year' },
  { value: 'custom', labelKey: 'stats.custom' },
];

/** dayjs unit for a steppable granularity. */
function unitOf(granularity: Exclude<StatsGranularity, 'custom'>) {
  return granularity;
}

/** Start/end of the calendar period containing `anchor`. */
function windowFor(
  granularity: Exclude<StatsGranularity, 'custom'>,
  anchor: Dayjs,
): { start: Dayjs; end: Dayjs } {
  const unit = unitOf(granularity);
  return { start: anchor.startOf(unit), end: anchor.endOf(unit) };
}

/**
 * Derive the {fromDate, toDate} query range from a picker state.
 * A steppable window is capped at today; a custom state without a full
 * range falls back to the current month.
 */
export function deriveRange(state: TimeWindowState): StatsDateRange {
  const today = dayjs();
  if (state.granularity === 'custom') {
    if (state.customRange?.from && state.customRange?.to) {
      return {
        fromDate: dayjs(state.customRange.from).format(DAY),
        toDate: dayjs(state.customRange.to).format(DAY),
      };
    }
    return {
      fromDate: today.startOf('month').format(DAY),
      toDate: today.format(DAY),
    };
  }
  const { start, end } = windowFor(state.granularity, dayjs(state.anchor));
  const cappedEnd = end.isAfter(today) ? today : end;
  return { fromDate: start.format(DAY), toDate: cappedEnd.format(DAY) };
}

/** Localised, human-readable label for the active period. */
function formatWindowLabel(
  granularity: Exclude<StatsGranularity, 'custom'>,
  anchor: Dayjs,
  lang: string,
): string {
  if (granularity === 'year') {
    return new Intl.DateTimeFormat(lang, { year: 'numeric' }).format(
      anchor.toDate(),
    );
  }
  if (granularity === 'month') {
    const label = new Intl.DateTimeFormat(lang, {
      month: 'long',
      year: 'numeric',
    }).format(anchor.toDate());
    return label.charAt(0).toUpperCase() + label.slice(1);
  }
  const { start, end } = windowFor('week', anchor);
  const fmt = new Intl.DateTimeFormat(lang, { day: 'numeric', month: 'short' });
  return `${fmt.format(start.toDate())} – ${fmt.format(end.toDate())}`;
}

function formatDay(date: Date, lang: string): string {
  return new Intl.DateTimeFormat(lang, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

type TimeWindowPickerProps = {
  onChange: (range: StatsDateRange) => void;
  /** Hydrate the picker from a previously persisted state (e.g. a store). */
  initialState?: TimeWindowState;
  /** Called whenever the picker's UI state changes, for persistence. */
  onStateChange?: (state: TimeWindowState) => void;
};

export function TimeWindowPicker({
  onChange,
  initialState,
  onStateChange,
}: TimeWindowPickerProps) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;

  const [granularity, setGranularity] = useState<StatsGranularity>(
    () => initialState?.granularity ?? 'month',
  );
  const [anchor, setAnchor] = useState<Dayjs>(() =>
    initialState?.anchor ? dayjs(initialState.anchor) : dayjs(),
  );
  const [customRange, setCustomRange] = useState<DateRange | undefined>(() =>
    initialState?.customRange
      ? {
          from: dayjs(initialState.customRange.from).toDate(),
          to: dayjs(initialState.customRange.to).toDate(),
        }
      : undefined,
  );

  // Avoid re-emitting an identical range (would churn query cache keys).
  const lastEmitted = useRef<string>('');
  const emit = useCallback(
    (range: StatsDateRange) => {
      const key = `${range.fromDate}|${range.toDate}`;
      if (key === lastEmitted.current) return;
      lastEmitted.current = key;
      onChange(range);
    },
    [onChange],
  );

  const hasCustomRange = !!(customRange?.from && customRange?.to);

  // Current serialisable state, recomputed on any UI change.
  const currentState: TimeWindowState = useMemo(
    () => ({
      granularity,
      anchor: anchor.format(DAY),
      customRange: hasCustomRange
        ? {
            from: dayjs(customRange!.from).format(DAY),
            to: dayjs(customRange!.to).format(DAY),
          }
        : undefined,
    }),
    [granularity, anchor, hasCustomRange, customRange],
  );

  // Report UI-state changes upward so they can be persisted across mounts.
  useEffect(() => {
    onStateChange?.(currentState);
  }, [currentState, onStateChange]);

  // Emit the derived query range (skip custom mode until a full range is picked).
  useEffect(() => {
    if (granularity === 'custom' && !hasCustomRange) return;
    emit(deriveRange(currentState));
  }, [currentState, granularity, hasCustomRange, emit]);

  const selectGranularity = (next: StatsGranularity) => {
    if (next === granularity) return;
    if (next === 'custom') {
      if (!customRange?.from) {
        const base = granularity === 'custom' ? 'month' : granularity;
        const today = dayjs();
        const { start, end } = windowFor(base, anchor);
        setCustomRange({
          from: start.toDate(),
          to: (end.isAfter(today) ? today : end).toDate(),
        });
      }
    } else {
      setAnchor(dayjs());
    }
    setGranularity(next);
  };

  const step = (delta: 1 | -1) => {
    if (granularity === 'custom') return;
    setAnchor((prev) => prev.add(delta, unitOf(granularity)));
  };

  // Next is disabled once the active window already reaches today.
  const canGoNext =
    granularity !== 'custom' &&
    windowFor(granularity, anchor).end.isBefore(dayjs(), 'day');

  const label =
    granularity === 'custom'
      ? ''
      : formatWindowLabel(granularity, anchor, lang);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="flex gap-1">
        {GRANULARITY_OPTIONS.map((opt) => (
          <Button
            key={opt.value}
            size="sm"
            variant={granularity === opt.value ? 'default' : 'outline'}
            onClick={() => selectGranularity(opt.value)}
          >
            {t(opt.labelKey)}
          </Button>
        ))}
      </div>

      {granularity === 'custom' ? (
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-9 min-w-48 justify-start gap-2 font-normal"
            >
              <CalendarIcon className="size-4" />
              {customRange?.from && customRange?.to
                ? `${formatDay(customRange.from, lang)} – ${formatDay(customRange.to, lang)}`
                : t('stats.pickRange')}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="end">
            <Calendar
              mode="range"
              numberOfMonths={2}
              selected={customRange}
              onSelect={setCustomRange}
              defaultMonth={customRange?.from}
              disabled={{ after: new Date() }}
            />
          </PopoverContent>
        </Popover>
      ) : (
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            className="size-9 shrink-0"
            onClick={() => step(-1)}
            aria-label={t('stats.previousPeriod')}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="min-w-36 text-center text-sm font-medium">
            {label}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="size-9 shrink-0"
            onClick={() => step(1)}
            disabled={!canGoNext}
            aria-label={t('stats.nextPeriod')}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
