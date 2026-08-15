import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Card,
  Group,
  Loader,
  MultiSelect,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { RadarChart } from "@mantine/charts";
import { IconTrophy } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api, type ScorecardEntry } from "../../api/client";
import { asModelColor, ModelHeading } from "../models/ModelColor";
import { CapacityPlate, formatContextWindow, formatVramGb } from "./CapacityPlate";
import { SpeedPlate } from "./SpeedPlate";

export const QUALITY_AXES = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "tool_calling",
  "instruction",
  "structured",
  "long_context",
] as const;

const AXIS_LABELS: Record<string, string> = {
  knowledge: "Knowledge",
  reasoning: "Reasoning",
  math: "Math",
  coding: "Coding",
  tool_calling: "Tool calling",
  instruction: "Instruction",
  structured: "Structured",
  long_context: "Long context",
};

const DASH_PATTERNS = ["0", "6 3", "2 2", "8 3 2 3", "1 3", "10 2"];
const COMPARE_SELECTION_KEY = "benchbase.compare.selectedModels";
const COMPARE_ACTIVE_ONLY_KEY = "benchbase.compare.activeOnly";
const COMPARE_SHOW_SMOKE_KEY = "benchbase.compare.showSmoke";
const COMPARE_SHOW_UNBENCHMARKED_KEY = "benchbase.compare.showUnbenchmarked";
const EMPTY_ENTRIES: ScorecardEntry[] = [];

function readLocalFlag(key: string, defaultValue = false): boolean {
  try {
    const v = localStorage.getItem(key);
    if (v === null) return defaultValue;
    return v === "1";
  } catch {
    return defaultValue;
  }
}

function writeLocalFlag(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // ignore
  }
}

function sameNames(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((n, i) => n === b[i]);
}

function rankBadge(rank: number | null, tied = false, competitors?: number) {
  if (rank === null) return <Text c="dimmed" size="sm">—</Text>;
  const color = rank === 1 ? "yellow" : rank === 2 ? "gray" : rank === 3 ? "orange" : "blue";
  const ordinal =
    rank === 1 ? "1st" : rank === 2 ? "2nd" : rank === 3 ? "3rd" : `${rank}th`;
  return (
    <Badge
      variant="light"
      color={color}
      size="sm"
      leftSection={rank === 1 && !tied ? <IconTrophy size={12} /> : undefined}
    >
      {`${ordinal}${tied ? " tie" : ""}${competitors ? ` of ${competitors}` : ""}`}
    </Badge>
  );
}

function formatAxisCell(d: ScorecardEntry["dimensions"][string] | undefined) {
  if (!d || d.primary == null) {
    if (d?.scorer_status === "invalid") return { score: "invalid", ci: null as string | null };
    if (d?.version_mismatch) return { score: "stale", ci: null as string | null };
    return { score: "—", ci: null as string | null };
  }
  const ci =
    d.ci_low != null && d.ci_high != null
      ? `± ${Math.max(0, Math.round((d.ci_high - d.ci_low) / 2))}`
      : d.n_items != null && d.n_items < 5
        ? "n too small"
        : null;
  return { score: d.primary.toFixed(1), ci };
}

function overallLabel(entry: ScorecardEntry): string {
  if (entry.overall_rank == null && entry.borda_score <= 0) return "no overall score";
  const ordinal =
    entry.overall_rank === 1
      ? "1st"
      : entry.overall_rank === 2
        ? "2nd"
        : entry.overall_rank === 3
          ? "3rd"
          : entry.overall_rank != null
            ? `${entry.overall_rank}th`
            : "—";
  return `${ordinal}${entry.overall_rank_tied ? " tie" : ""} · ${entry.borda_score} pts`;
}

function loadSavedSelection(available: string[]): string[] | null {
  try {
    const raw = localStorage.getItem(COMPARE_SELECTION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return null;
    const names = parsed.filter((x): x is string => typeof x === "string");
    const filtered = names.filter((n) => available.includes(n));
    return filtered.length > 0 ? filtered : null;
  } catch {
    return null;
  }
}

function mantineColorToken(color: string | null | undefined, index: number): string {
  const c = asModelColor(color) || "blue";
  return `${c}.${4 + (index % 4)}`;
}

export function ComparePage() {
  const scorecard = useQuery({
    queryKey: ["model-scorecard"],
    queryFn: api.results.modelScorecard,
  });

  const entries = scorecard.data ?? EMPTY_ENTRIES;
  const hasHistory = entries.some((e) => e.has_benchmark_history);

  const [activeOnly, setActiveOnly] = useState(() =>
    readLocalFlag(COMPARE_ACTIVE_ONLY_KEY, false),
  );
  const [showSmoke, setShowSmoke] = useState(() =>
    readLocalFlag(COMPARE_SHOW_SMOKE_KEY, false),
  );
  const [showUnbenchmarked, setShowUnbenchmarked] = useState(() =>
    readLocalFlag(COMPARE_SHOW_UNBENCHMARKED_KEY, false),
  );

  const catalogEntries = useMemo(
    // Archived models stay in the DB but are never in the Compare picker.
    () => entries.filter((e) => e.status !== "archived"),
    [entries],
  );
  const availableNames = useMemo(
    () => catalogEntries.map((e) => e.model_name),
    [catalogEntries],
  );
  const availableKey = availableNames.join("\0");

  const [selected, setSelected] = useState<string[]>([]);
  const [selectionReady, setSelectionReady] = useState(false);
  const [mode, setMode] = useState<"table" | "radar">("radar");
  const [stretch, setStretch] = useState(false);
  const [showBands, setShowBands] = useState(false);
  const [groupByFamily, setGroupByFamily] = useState(false);
  /** Temporarily hidden on the radar (click name again to restore). */
  const [mutedModels, setMutedModels] = useState<string[]>([]);
  const [hoveredLegend, setHoveredLegend] = useState<string | null>(null);

  useEffect(() => {
    if (availableNames.length === 0) return;
    const saved = loadSavedSelection(availableNames);
    const next = saved ?? availableNames.slice(0, 6);
    setSelected((prev) => (sameNames(prev, next) ? prev : next));
    setSelectionReady(true);
  }, [availableKey]); // eslint-disable-line react-hooks/exhaustive-deps -- keyed by name list

  useEffect(() => {
    if (!selectionReady) return;
    localStorage.setItem(COMPARE_SELECTION_KEY, JSON.stringify(selected));
  }, [selected, selectionReady]);

  useEffect(() => {
    writeLocalFlag(COMPARE_ACTIVE_ONLY_KEY, activeOnly);
    writeLocalFlag(COMPARE_SHOW_SMOKE_KEY, showSmoke);
    writeLocalFlag(COMPARE_SHOW_UNBENCHMARKED_KEY, showUnbenchmarked);
  }, [activeOnly, showSmoke, showUnbenchmarked]);

  // Drop selection only when a model leaves the catalog (archived/deleted), never on display toggles.
  useEffect(() => {
    setSelected((prev) => {
      const next = prev.filter((n) => availableNames.includes(n));
      return sameNames(prev, next) ? prev : next;
    });
  }, [availableKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedEntries = useMemo(() => {
    const set = new Set(selected);
    return catalogEntries.filter((e) => set.has(e.model_name));
  }, [catalogEntries, selected]);

  /** Selection ∩ display filters — what radar/table actually draw. */
  const displayedEntries = useMemo(() => {
    let list = selectedEntries;
    if (activeOnly) {
      list = list.filter((e) => e.is_active === true || e.status === "active");
    }
    if (!showUnbenchmarked) {
      list = list.filter((e) => e.has_benchmark_history);
    }
    if (!showSmoke) {
      list = list.filter((e) => e.best_tier !== "smoke");
    }
    return list;
  }, [selectedEntries, activeOnly, showSmoke, showUnbenchmarked]);

  const speedRankInView = useMemo(() => {
    const scored = displayedEntries.filter((e) => {
      const s = e.speed;
      return (
        s?.sec_per_correct != null &&
        s.work_clock_tier !== "smoke" &&
        !s.invalid_reason
      );
    });
    const map = new Map<string, { rank: number; tied: boolean }>();
    for (const e of scored) {
      const sec = e.speed!.sec_per_correct as number;
      const rank = 1 + scored.filter((p) => (p.speed!.sec_per_correct as number) < sec).length;
      const tied = scored.filter((p) => p.speed!.sec_per_correct === sec).length > 1;
      map.set(e.model_name, { rank, tied });
    }
    return map;
  }, [displayedEntries]);

  const peerSec = useMemo(
    () =>
      displayedEntries
        .map((e) => e.speed?.sec_per_correct)
        .filter((n): n is number => typeof n === "number"),
    [displayedEntries],
  );

  const speedIndexReference = displayedEntries.find((e) => e.speed?.work_clock_reference)
    ?.speed?.work_clock_reference;

  const radarModels = useMemo(() => {
    if (groupByFamily) {
      // One representative per base_model (highest quant_rank).
      const byBase = new Map<string, ScorecardEntry>();
      for (const e of displayedEntries) {
        const key = e.base_model || e.model_name;
        const prev = byBase.get(key);
        if (!prev || (e.quant_rank ?? 0) > (prev.quant_rank ?? 0)) {
          byBase.set(key, e);
        }
      }
      return [...byBase.values()];
    }
    return displayedEntries;
  }, [displayedEntries, groupByFamily]);

  const mutedSet = useMemo(() => new Set(mutedModels), [mutedModels]);

  useEffect(() => {
    const names = new Set(radarModels.map((e) => e.model_name));
    setMutedModels((prev) => {
      const next = prev.filter((n) => names.has(n));
      return next.length === prev.length && next.every((n, i) => n === prev[i])
        ? prev
        : next;
    });
    setHoveredLegend((h) => (h && names.has(h) ? h : null));
  }, [radarModels]);

  const plottedRadarModels = useMemo(
    () => radarModels.filter((e) => !mutedSet.has(e.model_name)),
    [radarModels, mutedSet],
  );

  const radarData = useMemo(() => {
    const mins: Record<string, number> = {};
    const maxs: Record<string, number> = {};
    if (stretch) {
      for (const axis of QUALITY_AXES) {
        const vals = plottedRadarModels
          .map((e) => e.dimensions[axis]?.primary)
          .filter((v): v is number => v != null);
        mins[axis] = vals.length ? Math.min(...vals) : 0;
        maxs[axis] = vals.length ? Math.max(...vals) : 100;
        if (mins[axis] === maxs[axis]) {
          mins[axis] = Math.max(0, mins[axis] - 1);
          maxs[axis] = Math.min(100, maxs[axis] + 1);
        }
      }
    }

    return QUALITY_AXES.map((axis) => {
      const row: Record<string, string | number | null> = {
        axis: stretch
          ? `${AXIS_LABELS[axis]} (${mins[axis]?.toFixed(0)}–${maxs[axis]?.toFixed(0)})`
          : AXIS_LABELS[axis],
        _axisKey: axis,
      };
      plottedRadarModels.forEach((entry) => {
        const raw = entry.dimensions[axis]?.primary;
        if (raw == null) {
          row[entry.model_name] = null;
          return;
        }
        if (!stretch) {
          row[entry.model_name] = raw;
          return;
        }
        const span = maxs[axis] - mins[axis] || 1;
        row[entry.model_name] = ((raw - mins[axis]) / span) * 100;
      });
      return row;
    });
  }, [plottedRadarModels, stretch]);

  const series = plottedRadarModels.map((entry, i) => {
    const origIdx = radarModels.findIndex((e) => e.model_name === entry.model_name);
    const idx = origIdx >= 0 ? origIdx : i;
    return {
      name: entry.model_name,
      color: mantineColorToken(entry.model_color, idx),
      strokeDasharray: DASH_PATTERNS[idx % DASH_PATTERNS.length],
      opacity: 0,
    };
  });

  const selectData = catalogEntries.map((entry) => ({
    value: entry.model_name,
    label: `${entry.model_name} — ${overallLabel(entry)}`,
  }));

  const bandsAllowed = plottedRadarModels.length <= 3;

  const radarByName = useMemo(() => {
    const m = new Map<string, ScorecardEntry>();
    for (const e of radarModels) m.set(e.model_name, e);
    return m;
  }, [radarModels]);

  function toggleMuted(name: string) {
    setMutedModels((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
    setHoveredLegend((h) => (h === name ? null : h));
  }

  function radarTooltipContent(props: {
    active?: boolean;
    // Recharts payload typing is readonly / loose across versions.
    payload?: readonly {
      name?: string;
      value?: number | null;
      payload?: Record<string, unknown>;
    }[];
  }) {
    const { active, payload } = props;
    if (!active || !payload?.length) return null;
    const axisKey = String(payload[0]?.payload?._axisKey ?? "");
    const axisLabel = AXIS_LABELS[axisKey] ?? axisKey;
    return (
      <Card withBorder shadow="md" padding="sm" style={{ maxWidth: 320 }}>
        <Stack gap={6}>
          <Text size="sm" fw={700}>{axisLabel}</Text>
          {payload.map((p) => {
            const name = String(p.name ?? "");
            const entry = radarByName.get(name);
            const dim = entry?.dimensions[axisKey];
            const cell = formatAxisCell(dim);
            return (
              <Stack key={name} gap={2}>
                <Group gap="xs">
                  <ModelHeading
                    name={name}
                    color={asModelColor(entry?.model_color)}
                    size="sm"
                  />
                </Group>
                <Text size="xs">
                  Score: <Text span fw={700}>{cell.score}</Text>
                  {cell.ci ? ` (${cell.ci})` : ""}
                  {dim?.n_items != null ? ` · n=${dim.n_items}` : ""}
                </Text>
                {dim?.rank != null && (
                  <Text size="xs" c="dimmed">
                    Rank {dim.rank}
                    {dim.rank_tied ? " (tie)" : ""}
                    {dim.borda_points != null ? ` · ${dim.borda_points} Borda` : ""}
                  </Text>
                )}
                {dim?.scorer_status === "invalid" && (
                  <Badge size="xs" color="red">invalid</Badge>
                )}
                {dim?.version_mismatch && (
                  <Badge size="xs" color="yellow">stale</Badge>
                )}
                {dim?.excluded_from_ranking && (
                  <Text size="xs" c="dimmed">Excluded from ranking</Text>
                )}
              </Stack>
            );
          })}
        </Stack>
      </Card>
    );
  }

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>Model Comparison</Title>
          <Text c="dimmed">
            Eight quality axes with Wilson CIs. Speed is a plate (index vs a Settings baseline, tok/s second) — never on the radar.
            Borda overall ranks quality axes only. Axes marked invalid failed scoring controls;
            stale axes are from an older suite version and are excluded until re-run.
            {speedIndexReference
              ? ` Speed index is 100 at ${speedIndexReference} (local work clock).`
              : " Set a Speed-index baseline on Settings to compare seats as a percentage."}
          </Text>
        </div>
        <SegmentedControl
          value={mode}
          onChange={(v) => setMode(v as "table" | "radar")}
          data={[
            { label: "Radar", value: "radar" },
            { label: "Table", value: "table" },
          ]}
        />
      </Group>

      {scorecard.isLoading && <Loader />}
      {!scorecard.isLoading && !hasHistory && (
        <Text c="dimmed">No completed v2 runs yet. Launch a Smoke or Standard tier from Benchmarks.</Text>
      )}

      {hasHistory && (
        <>
          <MultiSelect
            label="Models to compare"
            description="Full catalog for picking. Display toggles below only affect what the chart/table draw from your selection."
            data={selectData}
            value={selected}
            onChange={setSelected}
            searchable
            clearable
            maxDropdownHeight={320}
          />
          <Group gap="md" align="center">
            <Switch
              label="Active models only"
              checked={activeOnly}
              onChange={(e) => setActiveOnly(e.currentTarget.checked)}
            />
            <Switch
              label="Include smoke results"
              checked={showSmoke}
              onChange={(e) => setShowSmoke(e.currentTarget.checked)}
            />
            <Switch
              label="Include Unbenchmarked"
              checked={showUnbenchmarked}
              onChange={(e) => setShowUnbenchmarked(e.currentTarget.checked)}
            />
            <Text size="sm" c="blue" style={{ cursor: "pointer" }} onClick={() => setSelected(availableNames)}>
              Select all
            </Text>
            <Text size="sm" c="blue" style={{ cursor: "pointer" }} onClick={() => setSelected([])}>
              Clear
            </Text>
            <Text
              size="sm"
              c="blue"
              style={{ cursor: "pointer" }}
              onClick={() =>
                setSelected(
                  catalogEntries
                    .filter((e) => e.overall_rank != null && e.overall_rank <= 5)
                    .map((e) => e.model_name),
                )
              }
            >
              Top 5 overall
            </Text>
            {mode === "radar" && (
              <>
                <Switch
                  label={stretch ? "Stretched — differences amplified" : "Absolute 0–100"}
                  checked={stretch}
                  onChange={(e) => setStretch(e.currentTarget.checked)}
                />
                <Switch
                  label="Shade areas"
                  checked={showBands && bandsAllowed}
                  disabled={!bandsAllowed}
                  onChange={(e) => setShowBands(e.currentTarget.checked)}
                />
                <Switch
                  label="Best per family"
                  checked={groupByFamily}
                  onChange={(e) => setGroupByFamily(e.currentTarget.checked)}
                />
              </>
            )}
          </Group>

          {selected.length === 0 ? (
            <Text c="dimmed">Select at least one model.</Text>
          ) : displayedEntries.length === 0 ? (
            <Text c="dimmed">
              All selected models are hidden by the display filters
              {selected.length === 1 ? "" : ` (${selected.length} selected)`}.
            </Text>
          ) : mode === "table" ? (
            <Card withBorder shadow="sm" padding="md">
              <Table.ScrollContainer minWidth={1280}>
                <Table striped highlightOnHover withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Model</Table.Th>
                      <Table.Th>Overall</Table.Th>
                      {QUALITY_AXES.map((a) => (
                        <Table.Th key={a}>{AXIS_LABELS[a]}</Table.Th>
                      ))}
                      <Table.Th>Speed</Table.Th>
                      <Table.Th>TTFT</Table.Th>
                      <Table.Th>Context</Table.Th>
                      <Table.Th>VRAM</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {displayedEntries.map((entry) => (
                      <Table.Tr key={entry.model_name}>
                        <Table.Td>
                          <Group gap="xs">
                            <ModelHeading
                              name={entry.model_name}
                              color={asModelColor(entry.model_color)}
                              size="sm"
                            />
                            {entry.status && entry.status !== "active" && (
                              <Badge size="xs" color="gray" variant="light">
                                {entry.status}
                              </Badge>
                            )}
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          <Group gap="xs">
                            {rankBadge(
                              entry.overall_rank,
                              entry.overall_rank_tied,
                              entry.overall_competitors,
                            )}
                            <Text size="sm" c="dimmed">
                              {entry.borda_score > 0 ? `${entry.borda_score} pts` : "no data"}
                            </Text>
                          </Group>
                        </Table.Td>
                        {QUALITY_AXES.map((axis) => {
                          const d = entry.dimensions[axis];
                          const { score, ci } = formatAxisCell(d);
                          const warn =
                            d?.scorer_status === "invalid" || d?.version_mismatch;
                          return (
                            <Table.Td key={axis}>
                              <Group gap={4} wrap="nowrap">
                                {rankBadge(d?.rank ?? null, d?.rank_tied, d?.competitors)}
                                <Text size="sm" c={warn ? "orange" : undefined}>
                                  {score}
                                </Text>
                                {d?.scorer_status === "invalid" && (
                                  <Tooltip label="Scorer failed null/random/echo controls">
                                    <Badge size="xs" color="red" variant="light">
                                      scorer-invalid
                                    </Badge>
                                  </Tooltip>
                                )}
                                {d?.version_mismatch && (
                                  <Tooltip label="Suite version mismatch — re-run on current corpus">
                                    <Badge size="xs" color="yellow" variant="light">
                                      stale
                                    </Badge>
                                  </Tooltip>
                                )}
                              </Group>
                              {ci && (
                                <Text size="xs" c="dimmed">
                                  {ci}
                                </Text>
                              )}
                            </Table.Td>
                          );
                        })}
                        <Table.Td>
                          <SpeedPlate
                            speed={entry.speed}
                            rankInView={speedRankInView.get(entry.model_name)?.rank}
                            rankTied={speedRankInView.get(entry.model_name)?.tied}
                            peerSec={peerSec}
                          />
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">
                            {entry.speed?.ttft_ms != null
                              ? `${Math.round(entry.speed.ttft_ms)} ms`
                              : "—"}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatContextWindow(entry.context_window)}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{formatVramGb(entry.vram_gb)}</Text>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </Card>
          ) : (
            <Card withBorder shadow="sm" padding="md">
              <Title order={4} mb="sm">
                Radar ({radarModels.length} model{radarModels.length === 1 ? "" : "s"}
                {stretch ? " · stretched" : ""})
              </Title>
              <RadarChart
                h={420}
                data={radarData}
                dataKey="axis"
                withPolarRadiusAxis
                withLegend={false}
                withTooltip
                series={series.map((s) => ({
                  name: s.name,
                  color: s.color,
                  opacity: showBands && bandsAllowed ? 0.12 : 0,
                }))}
                radarChartProps={{ cx: "50%", cy: "50%" }}
                tooltipProps={{
                  content: ((props: Record<string, unknown>) =>
                    radarTooltipContent(props as never)) as never,
                }}
                radarProps={(s) => {
                  const idx = series.findIndex((x) => x.name === s.name);
                  const hovering =
                    hoveredLegend != null && !mutedSet.has(hoveredLegend);
                  const emphasized = !hovering || s.name === hoveredLegend;
                  return {
                    strokeDasharray: series[idx]?.strokeDasharray,
                    strokeWidth: hovering && emphasized ? 3.5 : 2.75,
                    strokeOpacity: emphasized ? 1 : 0.14,
                    fillOpacity:
                      showBands && bandsAllowed
                        ? emphasized
                          ? 0.14
                          : 0.03
                        : 0,
                    connectNulls: false,
                    isAnimationActive: false,
                    dot: {
                      r: hovering && emphasized ? 5 : 4,
                      strokeWidth: 1,
                      fillOpacity: emphasized ? 1 : 0.2,
                      strokeOpacity: emphasized ? 1 : 0.2,
                    },
                    activeDot: { r: 7, strokeWidth: 2 },
                  };
                }}
              />
              <Text size="xs" c="dimmed" mt="xs">
                Hover a model name to highlight its outline. Click the name to
                temporarily hide it (click again to restore).
              </Text>
              <Group mt="md" gap="lg" align="flex-start">
                {radarModels.map((entry) => {
                  const partial = QUALITY_AXES.some(
                    (a) => entry.dimensions[a]?.primary == null,
                  );
                  const muted = mutedSet.has(entry.model_name);
                  const color = asModelColor(entry.model_color);
                  return (
                    <Stack key={entry.model_name} gap={4} style={{ minWidth: 140 }}>
                      <Group gap="xs">
                        <UnstyledButton
                          onClick={() => toggleMuted(entry.model_name)}
                          onMouseEnter={() => {
                            if (!muted) setHoveredLegend(entry.model_name);
                          }}
                          onMouseLeave={() => setHoveredLegend(null)}
                          aria-pressed={muted}
                          aria-label={
                            muted
                              ? `Show ${entry.model_name} on radar`
                              : `Hide ${entry.model_name} on radar`
                          }
                          style={{
                            opacity: muted ? 0.45 : 1,
                            borderRadius: 4,
                          }}
                        >
                          <ModelHeading
                            name={entry.model_name}
                            color={muted ? "gray" : color}
                            size="sm"
                          />
                        </UnstyledButton>
                        {partial && (
                          <Tooltip label="Missing one or more axes — radar shows gaps">
                            <Badge size="xs" color="yellow" variant="light">
                              partial
                            </Badge>
                          </Tooltip>
                        )}
                        {muted && (
                          <Badge size="xs" color="gray" variant="outline">
                            hidden
                          </Badge>
                        )}
                      </Group>
                      <SpeedPlate
                        speed={entry.speed}
                        rankInView={speedRankInView.get(entry.model_name)?.rank}
                        rankTied={speedRankInView.get(entry.model_name)?.tied}
                        peerSec={peerSec}
                      />
                      <CapacityPlate
                        contextWindow={entry.context_window}
                        vramGb={entry.vram_gb}
                      />
                    </Stack>
                  );
                })}
              </Group>
            </Card>
          )}
        </>
      )}
    </Stack>
  );
}
