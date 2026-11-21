import { ScrollArea, Table, Text, Tooltip } from "@mantine/core";
import { useMemo, useState } from "react";
import type { ScorecardEntry } from "../../api/client";

const AXES = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "tool_calling",
  "instruction",
] as const;

type HeatmapMode = "absolute" | "relative" | "delta";

/** Red → yellow → green in sRGB (even two-segment blend). */
const RYG_STOPS: [number, number, number][] = [
  [220, 38, 38],
  [250, 176, 5],
  [43, 168, 74],
];

function lerpChannel(a: number, b: number, t: number) {
  return Math.round(a + (b - a) * t);
}

function lerpRgb(from: [number, number, number], to: [number, number, number], t: number): string {
  const u = Math.max(0, Math.min(1, t));
  return `rgb(${lerpChannel(from[0], to[0], u)}, ${lerpChannel(from[1], to[1], u)}, ${lerpChannel(
    from[2],
    to[2],
    u,
  )})`;
}

/** t ∈ [0, 1]: 0 = bad (red), 0.5 = mid (yellow), 1 = good (green). */
function rygColor(t: number): string {
  const x = Math.max(0, Math.min(1, t));
  if (x <= 0.5) {
    return lerpRgb(RYG_STOPS[0], RYG_STOPS[1], x * 2);
  }
  return lerpRgb(RYG_STOPS[1], RYG_STOPS[2], (x - 0.5) * 2);
}

function scoreToGoodness(
  value: number,
  mode: HeatmapMode,
): number {
  if (mode === "delta") {
    // ±40 pts from baseline ≈ full red ↔ full green; 0 ≈ yellow.
    return 0.5 + Math.max(-0.5, Math.min(0.5, value / 80));
  }
  return Math.max(0, Math.min(100, value)) / 100;
}

function cellColor(value: number | null | undefined, mode: HeatmapMode) {
  if (value == null) {
    return "var(--mantine-color-gray-3)";
  }
  return rygColor(scoreToGoodness(value, mode));
}

export function HeatmapTab({
  entries,
  mode,
  baselineName,
}: {
  entries: ScorecardEntry[];
  mode: HeatmapMode;
  baselineName?: string;
}) {
  const [sortAxis, setSortAxis] = useState<string>("knowledge");

  const sorted = useMemo(() => {
    return [...entries].sort((a, b) => {
      const av = a.dimensions[sortAxis]?.primary ?? -1;
      const bv = b.dimensions[sortAxis]?.primary ?? -1;
      return (bv as number) - (av as number);
    });
  }, [entries, sortAxis]);

  const baseline = baselineName
    ? entries.find((e) => e.model_name === baselineName)
    : undefined;

  const columnMax: Record<string, number> = {};
  for (const axis of AXES) {
    columnMax[axis] = Math.max(
      0,
      ...entries.map((e) => e.dimensions[axis]?.primary ?? 0),
    );
  }

  return (
    <ScrollArea h={560} type="auto">
      <Table highlightOnHover withTableBorder withColumnBorders fz="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Model</Table.Th>
            {AXES.map((axis) => (
              <Table.Th key={axis}>
                <Text
                  component="button"
                  style={{ background: "none", border: 0, cursor: "pointer", color: "inherit" }}
                  onClick={() => setSortAxis(axis)}
                >
                  {axis}
                </Text>
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sorted.map((e) => (
            <Table.Tr key={e.model_name}>
              <Table.Td>{e.model_name}</Table.Td>
              {AXES.map((axis) => {
                const d = e.dimensions[axis];
                let val = d?.primary as number | null | undefined;
                if (mode === "delta" && baseline) {
                  const b = baseline.dimensions[axis]?.primary;
                  if (val != null && b != null) val = val - b;
                } else if (mode === "relative" && val != null) {
                  const max = columnMax[axis] || 1;
                  val = (val / max) * 100;
                }
                const bg = cellColor(val, mode);
                return (
                  <Table.Td
                    key={axis}
                    style={{
                      background: bg,
                      textAlign: "center",
                      color: "var(--mantine-color-dark-9)",
                      fontWeight: 600,
                    }}
                  >
                    <Tooltip
                      label={`${d?.compatibility_class ?? "?"} · n=${d?.n_items ?? "—"}`}
                    >
                      <span>{val != null ? val.toFixed(1) : "—"}</span>
                    </Tooltip>
                  </Table.Td>
                );
              })}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}