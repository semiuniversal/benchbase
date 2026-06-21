import {
  Button,
  Card,
  Group,
  Loader,
  MultiSelect,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconScale } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";

export function ComparePage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.benchmarks.runs });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<unknown[] | null>(null);
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
      const data = await api.results.compare(selectedIds.map(Number));
      setComparison(data);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Stack>
      <Title order={2}>Head-to-Head Comparison</Title>
      <Text c="dimmed">
        Select two or more completed runs to compare their scores side by side.
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

      {comparison && comparison.length > 0 && (
        <Card withBorder shadow="sm">
          <Title order={4} mb="sm">Results</Title>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Model</Table.Th>
                <Table.Th>Suite</Table.Th>
                <Table.Th>Category</Table.Th>
                <Table.Th>Scores</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(comparison as Array<{
                model_name: string;
                suite_name: string;
                category: string;
                scores: Record<string, { score: number | null }>;
              }>).map((entry, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{entry.model_name}</Table.Td>
                  <Table.Td>{entry.suite_name}</Table.Td>
                  <Table.Td>{entry.category}</Table.Td>
                  <Table.Td>
                    {Object.entries(entry.scores).map(([task, val]) => (
                      <Text key={task} size="xs">
                        {task}: {val.score ?? "—"}
                      </Text>
                    ))}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      {comparison && comparison.length === 0 && (
        <Text c="dimmed">No results found for the selected runs.</Text>
      )}
    </Stack>
  );
}
