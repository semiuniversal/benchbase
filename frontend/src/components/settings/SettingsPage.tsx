import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  PasswordInput,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Switch,
  MultiSelect,
  Slider,
  NumberInput,
  useMantineColorScheme,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDeviceFloppy, IconRefresh, IconHeartbeat, IconTrash } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type AppSettings } from "../../api/client";
import { buildModelMaps, modelColor, ModelColorPicker, ModelTag } from "../models/ModelColor";

const SUITE_OPTIONS = [
  { value: "speed", label: "Speed / Throughput" },
  { value: "coding", label: "Coding (HumanEval)" },
  { value: "tool_use", label: "Tool Use" },
  { value: "reasoning", label: "Reasoning (GSM8K/MMLU)" },
];

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const [form, setForm] = useState<Partial<AppSettings>>({});

  useEffect(() => {
    if (settingsQuery.data) {
      setForm(settingsQuery.data);
    }
  }, [settingsQuery.data]);

  const mutation = useMutation({
    mutationFn: api.settings.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      notifications.show({ title: "Saved", message: "Settings updated.", color: "green" });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Error", message: err.message, color: "red" });
    },
  });

  const discoverMutation = useMutation({
    mutationFn: async () => {
      await api.settings.update(form);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      return api.models.discover();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      const activeList = data.active.length > 0 ? data.active.join(", ") : "none";
      const inactiveList = data.inactive.length > 0 ? data.inactive.join(", ") : "none";
      notifications.show({
        title: "Discovery complete",
        message: `${data.discovered} models found. Active: ${activeList}. Inactive: ${inactiveList}. Pick colors in the table below if you like.`,
        color: data.inactive.length > 0 ? "yellow" : "green",
        autoClose: 8000,
      });
    },
    onError: (err: Error) => {
      notifications.show({
        title: "Discovery failed",
        message: err.message,
        color: "red",
        autoClose: 10000,
      });
    },
  });

  const recheckMutation = useMutation({
    mutationFn: api.models.recheck,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      notifications.show({
        title: "Health check complete",
        message: `${data.active.length} active, ${data.inactive.length} inactive.`,
        color: data.inactive.length > 0 ? "yellow" : "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Health check failed", message: err.message, color: "red" });
    },
  });

  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const modelMaps = buildModelMaps(modelsQuery.data ?? []);

  const deleteMutation = useMutation({
    mutationFn: api.models.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  });

  const colorMutation = useMutation({
    mutationFn: ({ id, color }: { id: number; color: string }) =>
      api.models.update(id, { color }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Could not update color", message: err.message, color: "red" });
    },
  });

  const hasBaseUrl = Boolean(form.litellm_base_url?.trim());

  if (settingsQuery.isLoading) return <Loader />;

  return (
    <Stack>
      <Title order={2}>Settings</Title>

      <Card withBorder shadow="sm">
        <Stack>
          <Title order={4}>Connection</Title>
          <TextInput
            label="LiteLLM Base URL"
            description="URL of your LiteLLM proxy or OpenAI-compatible endpoint"
            value={form.litellm_base_url ?? ""}
            onChange={(e) => setForm({ ...form, litellm_base_url: e.currentTarget.value })}
          />
          <PasswordInput
            label="API Key"
            description="Optional. Bearer token for authenticating with the endpoint."
            placeholder="Leave empty if not required"
            value={form.litellm_api_key ?? ""}
            onChange={(e) => setForm({ ...form, litellm_api_key: e.currentTarget.value })}
          />
          <Group>
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              loading={discoverMutation.isPending}
              disabled={!hasBaseUrl}
              onClick={() => discoverMutation.mutate()}
            >
              Discover Models
            </Button>
            <Button
              variant="subtle"
              leftSection={<IconHeartbeat size={16} />}
              loading={recheckMutation.isPending}
              disabled={!hasBaseUrl}
              onClick={() => recheckMutation.mutate()}
            >
              Re-check Health
            </Button>
          </Group>

          {modelsQuery.data && modelsQuery.data.length > 0 && (
            <>
              <Divider my="sm" />
              <Title order={4}>Discovered Models</Title>
              <Text size="sm" c="dimmed" mb="xs">
                Click a color swatch to change how a model appears across BenchBase.
              </Text>
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Color</Table.Th>
                    <Table.Th>Model</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Last Checked</Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {modelsQuery.data.map((m) => (
                    <Table.Tr key={m.id}>
                      <Table.Td>
                        <ModelColorPicker
                          color={modelColor(modelMaps, { id: m.id })}
                          disabled={colorMutation.isPending}
                          onChange={(color) => colorMutation.mutate({ id: m.id, color })}
                        />
                      </Table.Td>
                      <Table.Td>
                        <ModelTag
                          name={m.name}
                          color={modelColor(modelMaps, { id: m.id })}
                        />
                      </Table.Td>
                      <Table.Td>
                        <Badge
                          color={m.is_active ? "green" : "red"}
                          variant="light"
                        >
                          {m.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {m.last_checked
                            ? new Date(m.last_checked).toLocaleString()
                            : "Never"}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Button
                          variant="subtle"
                          color="red"
                          size="compact-xs"
                          leftSection={<IconTrash size={14} />}
                          onClick={() => deleteMutation.mutate(m.id)}
                        >
                          Remove
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </>
          )}

          <Divider my="sm" />

          <Title order={4}>Benchmarks</Title>
          <MultiSelect
            label="Enabled Suites"
            data={SUITE_OPTIONS}
            value={form.benchmark_suites ?? []}
            onChange={(v) => setForm({ ...form, benchmark_suites: v })}
          />
          <TextInput
            label="LiteBench request timeout (seconds)"
            description="Per-request timeout for coding and tool-use benchmarks (LiteBench → LiteLLM). Default 600."
            type="number"
            min={30}
            value={String(form.litebench_timeout_seconds ?? 600)}
            onChange={(e) => {
              const n = parseInt(e.currentTarget.value, 10);
              setForm({
                ...form,
                litebench_timeout_seconds: Number.isFinite(n) ? n : 600,
              });
            }}
          />

          <Divider my="sm" />

          <Title order={4}>Sample sizes</Title>
          <Text size="sm" c="dimmed">
            BenchBase uses sampled subsets for routine work. Scores from sampled runs are
            indicative only — not published benchmark numbers. Full benchmarks run entire
            datasets and can take hours or days on slow models.
          </Text>

          <NumberInput
            label="Run All sample size"
            description="Per-task samples when using Run All Benchmarks (default 10). Speed uses 3 timed iterations; coding/tool-use use this count."
            min={1}
            max={500}
            value={form.batch_sample_limit ?? 10}
            onChange={(v) =>
              setForm({
                ...form,
                batch_sample_limit: typeof v === "number" ? v : 10,
              })
            }
          />

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Routine comparison sample size: {form.routine_sample_limit ?? 50}
            </Text>
            <Text size="xs" c="dimmed">
              Per-task samples for Run Benchmark (default 50). Reasoning runs this limit on
              each of four tasks (~{((form.routine_sample_limit ?? 50) * 4).toLocaleString()}
              API calls). Speed uses 5 iterations.
            </Text>
            <Slider
              min={10}
              max={200}
              step={5}
              marks={[
                { value: 10, label: "10" },
                { value: 50, label: "50" },
                { value: 100, label: "100" },
                { value: 200, label: "200" },
              ]}
              value={form.routine_sample_limit ?? 50}
              onChange={(v) => setForm({ ...form, routine_sample_limit: v })}
            />
          </Stack>

          <Divider my="sm" />

          <Title order={4}>Appearance</Title>
          <Switch
            label="Dark mode"
            checked={colorScheme === "dark"}
            onChange={() => {
              const next = colorScheme === "dark" ? "light" : "dark";
              setColorScheme(next);
              setForm({ ...form, theme: next });
            }}
          />

          <Divider my="sm" />

          <Group justify="flex-end">
            <Button
              leftSection={<IconDeviceFloppy size={16} />}
              loading={mutation.isPending}
              onClick={() => mutation.mutate(form)}
            >
              Save Settings
            </Button>
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}
