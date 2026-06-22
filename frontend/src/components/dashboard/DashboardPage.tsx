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
import { api, type ModelRecord, type RunRecord } from "../../api/client";
import {
  buildModelMaps,
  modelColor,
  ModelTag,
} from "../models/ModelColor";

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
  const modelMaps = buildModelMaps(models.data ?? []);

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
        <Title order={4} mb="sm">Models</Title>
        {models.isLoading ? (
          <Loader />
        ) : models.data && models.data.length > 0 ? (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Endpoint</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {models.data.map((m: ModelRecord) => (
                <Table.Tr key={m.id}>
                  <Table.Td>
                    <ModelTag
                      name={m.name}
                      color={modelColor(modelMaps, { id: m.id })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Badge color={m.is_active ? "green" : "red"} variant="light">
                      {m.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">{m.endpoint_url}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text c="dimmed">No models discovered yet. Go to Settings to connect your LiteLLM endpoint.</Text>
        )}
      </Card>

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
              {runs.data.map((run: RunRecord) => {
                const modelName = models.data?.find((m) => m.id === run.model_id)?.name ?? `#${run.model_id}`;
                return (
                  <Table.Tr key={run.id}>
                    <Table.Td>{run.id}</Table.Td>
                    <Table.Td>
                      <ModelTag
                        name={modelName}
                        color={modelColor(modelMaps, { id: run.model_id })}
                        size="sm"
                      />
                    </Table.Td>
                    <Table.Td>{run.suite_id}</Table.Td>
                    <Table.Td>
                      <Badge color={statusColor(run.status)} variant="light">
                        {run.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{run.started_at ?? "—"}</Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        ) : (
          <Text c="dimmed">No runs yet. Discover models and launch a benchmark to get started.</Text>
        )}
      </Card>
    </Stack>
  );
}
