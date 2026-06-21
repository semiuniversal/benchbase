import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  MultiSelect,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconScale, IconTrophy } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ScorecardEntry } from "../../api/client";

const DIMENSION_LABELS: Record<string, string> = {
  speed: "Speed",
  coding: "Coding",
  tool_use: "Tool Use",
  reasoning: "Reasoning",
};

const DIMENSION_ORDER = ["speed", "coding", "tool_use", "reasoning"];

function rankBadge(rank: number | null) {
  if (rank === null) return <Text c="dimmed" size="sm">--</Text>;
  const color = rank === 1 ? "yellow" : rank === 2 ? "gray" : rank === 3 ? "orange" : "blue";
  const label = rank === 1 ? "1st" : rank === 2 ? "2nd" : rank === 3 ? "3rd" : `${rank}th`;
  return (
    <Badge
      variant="light"
      color={color}
      size="sm"
      leftSection={rank === 1 ? <IconTrophy size={12} /> : undefined}
    >
      {label}
    </Badge>
  );
}

function formatScore(value: number | null, unit: string) {
  if (value === null) return "--";
  return `${value.toFixed(1)} ${unit}`;
}

export function ComparePage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.benchmarks.runs });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [scorecard, setScorecard] = useState<ScorecardEntry[] | null>(null);
  const [loading, setLoading] = useState(false);

  const runOptions =
    runs.data?.map((r) => ({
      value: String(r.id),
      label: `Run #${r.id} (model ${r.model_id}, suite ${r.suite_id}) – ${r.status}`,
    })) ?? [];

  const handleCompare = async () => {
    if (selectedIds.length < 2) return;
    setLoading(true);
    try {
      const data = await api.results.scorecard(selectedIds.map(Number));
      setScorecard(data);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Stack>
      <Title order={2}>Head-to-Head Comparison</Title>
      <Text c="dimmed">
        Select two or more completed runs to compare models with a ranked scorecard.
      </Text>

      <MultiSelect
        label="Select runs to compare"
        placeholder="Choose runs"
        data={runOptions}
        value={selectedIds}
        onChange={setSelectedIds}
      />

      <Group>
        <Button
          leftSection={<IconScale size={16} />}
          onClick={handleCompare}
          disabled={selectedIds.length < 2}
          loading={loading}
        >
          Compare
        </Button>
      </Group>

      {loading && <Loader />}

      {scorecard && scorecard.length > 0 && (
        <Card withBorder shadow="sm" padding="md">
          <Title order={4} mb="sm">Scorecard</Title>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Dimension</Table.Th>
                {scorecard.map((entry) => (
                  <Table.Th key={entry.model_name}>{entry.model_name}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              <Table.Tr style={{ fontWeight: 700 }}>
                <Table.Td>Overall</Table.Td>
                {scorecard.map((entry) => (
                  <Table.Td key={entry.model_name}>
                    <Group gap="xs">
                      {rankBadge(
                        entry.composite_rank !== null
                          ? Math.round(entry.composite_rank)
                          : null
                      )}
                      <Text size="sm" c="dimmed">
                        avg rank {entry.composite_rank?.toFixed(1) ?? "--"}
                      </Text>
                    </Group>
                  </Table.Td>
                ))}
              </Table.Tr>

              {DIMENSION_ORDER.map((dim) => (
                <Table.Tr key={dim}>
                  <Table.Td>{DIMENSION_LABELS[dim] ?? dim}</Table.Td>
                  {scorecard.map((entry) => {
                    const d = entry.dimensions[dim];
                    if (!d) {
                      return <Table.Td key={entry.model_name}>--</Table.Td>;
                    }
                    const detailEntries = Object.entries(d.details || {});
                    return (
                      <Table.Td key={entry.model_name}>
                        <Group gap="xs" wrap="nowrap">
                          {rankBadge(d.rank)}
                          <Text size="sm">{formatScore(d.primary, d.unit)}</Text>
                        </Group>
                        {detailEntries.length > 0 && (
                          <Stack gap={2} mt={4}>
                            {detailEntries.slice(0, 4).map(([key, val]) => (
                              <Tooltip key={key} label={key}>
                                <Text size="xs" c="dimmed">
                                  {key.split(":").pop()}: {typeof val === "number" ? val.toFixed(1) : String(val)}
                                </Text>
                              </Tooltip>
                            ))}
                          </Stack>
                        )}
                      </Table.Td>
                    );
                  })}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      {scorecard && scorecard.length === 0 && (
        <Text c="dimmed">No results found for the selected runs.</Text>
      )}
    </Stack>
  );
}
