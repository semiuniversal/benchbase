import { Badge, ScrollArea, Table, Text, Tooltip } from "@mantine/core";
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

function cellColor(value: number | null | undefined, mode: HeatmapMode, cohortMax: number) {
  if (value == null) return "var(--mantine-color-dark-6)";
  if (mode === "absolute") {
    const t = Math.max(0, Math.min(100, value)) / 100;
    const g = Math.round(40 + t * 140);
    return `rgb(30, ${g}, 80)`;
  }
  const rel = cohortMax > 0 ? value / cohortMax : 0;
  const g = Math.round(40 + rel * 140);
  return `rgb(80, ${g}, 120)`;
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
      <Table striped highlightOnHover withTableBorder withColumnBorders fz="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Model</Table.Th>
            <Table.Th>Cohort</Table.Th>
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
              <Table.Td>
                {e.cohort_eligible === false ? (
                  <Badge size="xs" color="gray">
                    excluded
                  </Badge>
                ) : (
                  <Badge size="xs" color="teal">
                    standard
                  </Badge>
                )}
              </Table.Td>
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
                return (
                  <Table.Td
                    key={axis}
                    style={{
                      background: cellColor(val, mode, columnMax[axis]),
                      textAlign: "center",
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