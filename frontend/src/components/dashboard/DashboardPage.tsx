import {
  Card,
  Grid,
  Group,
  Loader,
  Stack,
  Text,
  Title,
  Badge,
  Button,
  Table,
} from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api, type RunRecord } from "../../api/client";

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "green";
    case "running":
      return "blue";
    case "failed":
      return "red";
    case "pending":
      return "gray";
    default:
      return "gray";
  }
}

export function DashboardPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.benchmarks.runs });
  const suites = useQuery({ queryKey: ["suites"], queryFn: api.benchmarks.suites });

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Dashboard</Title>
        <Button
          variant="light"
          leftSection={<IconRefresh size={16} />}
          onClick={() => {
            models.refetch();
            runs.refetch();
          }}
        >
          Refresh
        </Button>
      </Group>

      <Grid>
        <Grid.Col span={{ base: 12, sm: 4 }}>
          <Card withBorder shadow="sm" padding="lg">
            <Text size="sm" c="dimmed">Models</Text>
            <Title order={2}>{models.data?.length ?? "—"}</Title>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 4 }}>
          <Card withBorder shadow="sm" padding="lg">
            <Text size="sm" c="dimmed">Benchmark Suites</Text>
            <Title order={2}>{suites.data?.length ?? "—"}</Title>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 4 }}>
          <Card withBorder shadow="sm" padding="lg">
            <Text size="sm" c="dimmed">Total Runs</Text>
            <Title order={2}>{runs.data?.length ?? "—"}</Title>
          </Card>
        </Grid.Col>
      </Grid>

      <Card withBorder shadow="sm">
        <Title order={4} mb="sm">Recent Runs</Title>
        {runs.isLoading ? (
          <Loader />
        ) : runs.data && runs.data.length > 0 ? (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ID</Table.Th>
                <Table.Th>Model</Table.Th>
                <Table.Th>Suite</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Started</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runs.data.map((run: RunRecord) => (
                <Table.Tr key={run.id}>
                  <Table.Td>{run.id}</Table.Td>
                  <Table.Td>{run.model_id}</Table.Td>
                  <Table.Td>{run.suite_id}</Table.Td>
                  <Table.Td>
                    <Badge color={statusColor(run.status)} variant="light">
                      {run.status}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{run.started_at ?? "—"}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text c="dimmed">No runs yet. Discover models and launch a benchmark to get started.</Text>
        )}
      </Card>
    </Stack>
  );
}
