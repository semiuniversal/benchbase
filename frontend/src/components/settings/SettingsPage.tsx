import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Modal,
  PasswordInput,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Switch,
  useMantineColorScheme,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useDisclosure } from "@mantine/hooks";
import { IconAlertTriangle, IconDeviceFloppy, IconRefresh, IconHeartbeat, IconTrash } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type AppSettings, type SettingsUpdatePayload } from "../../api/client";
import { buildModelMaps, modelColor, ModelColorPicker, ModelTag } from "../models/ModelColor";

function buildSettingsPayload(
  form: Partial<AppSettings>,
  apiKeyInput: string,
): SettingsUpdatePayload {
  const payload: SettingsUpdatePayload = { ...form };
  delete (payload as { litellm_api_key_set?: boolean }).litellm_api_key_set;
  if (apiKeyInput.trim()) {
    payload.litellm_api_key = apiKeyInput.trim();
  }
  return payload;
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const [form, setForm] = useState<Partial<AppSettings>>({});
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [clearOpen, { open: openClear, close: closeClear }] = useDisclosure(false);

  useEffect(() => {
    if (settingsQuery.data) {
      setForm(settingsQuery.data);
      setApiKeyInput("");
    }
  }, [settingsQuery.data]);

  const mutation = useMutation({
    mutationFn: () => api.settings.update(buildSettingsPayload(form, apiKeyInput)),
    onSuccess: () => {
      setApiKeyInput("");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      notifications.show({ title: "Saved", message: "Settings updated.", color: "green" });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Error", message: err.message, color: "red" });
    },
  });

  const discoverMutation = useMutation({
    mutationFn: async () => {
      const payload: SettingsUpdatePayload = {};
      if (form.litellm_base_url?.trim()) {
        payload.litellm_base_url = form.litellm_base_url.trim();
      }
      if (apiKeyInput.trim()) {
        payload.litellm_api_key = apiKeyInput.trim();
      }
      if (Object.keys(payload).length > 0) {
        await api.settings.update(payload);
        setApiKeyInput("");
        queryClient.invalidateQueries({ queryKey: ["settings"] });
      }
      return api.models.discover();
    },
    onSuccess: async (data) => {
      await queryClient.refetchQueries({ queryKey: ["models"] });
      const unreachable = data.unreachable ?? data.inactive ?? [];
      const asOf = data.checked_at
        ? ` as of ${new Date(data.checked_at).toLocaleTimeString()}`
        : "";
      notifications.show({
        title: "Discovery complete",
        message: `${data.discovered} listed · ${data.active.length} active · ${unreachable.length} unreachable · ${data.archived_skipped ?? 0} archived skipped${asOf}`,
        color: unreachable.length > 0 ? "yellow" : "green",
        autoClose: 12000,
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
    onSuccess: async (data) => {
      await queryClient.refetchQueries({ queryKey: ["models"] });
      const unreachable = data.unreachable ?? data.inactive ?? [];
      const asOf = data.checked_at
        ? ` as of ${new Date(data.checked_at).toLocaleTimeString()}`
        : "";
      notifications.show({
        title: "Health check complete",
        message: `${data.active.length} active, ${unreachable.length} unreachable, ${data.archived_skipped ?? 0} archived skipped${asOf}`,
        color: unreachable.length > 0 ? "yellow" : "green",
        autoClose: 12000,
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

  const clearBenchmarksMutation = useMutation({
    mutationFn: api.benchmarks.deleteAllRuns,
    onSuccess: (data) => {
      closeClear();
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["batch-status"] });
      queryClient.invalidateQueries({ queryKey: ["model-scorecard"] });
      notifications.show({
        title: "Benchmarks cleared",
        message: `Removed ${data.deleted} run${data.deleted === 1 ? "" : "s"} and all results.`,
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Could not clear benchmarks", message: err.message, color: "red" });
    },
  });

  const hasBaseUrl = Boolean(form.litellm_base_url?.trim());
  const hasApiKey =
    Boolean(settingsQuery.data?.litellm_api_key_set) || Boolean(apiKeyInput.trim());

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
            description="Leave empty to keep the saved key. Enter a new value only when changing it."
            placeholder={
              settingsQuery.data?.litellm_api_key_set
                ? "Key saved — enter only to replace"
                : "Required for LiteLLM auth"
            }
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.currentTarget.value)}
          />
          {settingsQuery.data?.litellm_api_key_set && !apiKeyInput && (
            <Badge color="green" variant="light" size="sm">
              API key saved
            </Badge>
          )}
          <Group>
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              loading={discoverMutation.isPending}
              disabled={!hasBaseUrl || !hasApiKey}
              onClick={() => discoverMutation.mutate()}
            >
              Discover Models
            </Button>
            <Button
              variant="subtle"
              leftSection={<IconHeartbeat size={16} />}
              loading={recheckMutation.isPending}
              disabled={!hasBaseUrl || !hasApiKey}
              onClick={() => recheckMutation.mutate()}
            >
              Re-check Health
            </Button>
          </Group>
          {!hasApiKey && hasBaseUrl && (
            <Text size="xs" c="dimmed">
              Save an API key before discovering or health-checking models.
            </Text>
          )}

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
                          color={
                            m.status === "active" || m.is_active
                              ? "green"
                              : m.status === "archived"
                                ? "gray"
                                : "red"
                          }
                          variant="light"
                        >
                          {m.status ?? (m.is_active ? "active" : "unreachable")}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {m.last_checked
                            ? `as of ${new Date(m.last_checked).toLocaleString()}`
                            : "Never"}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          {m.status !== "archived" ? (
                            <Button
                              variant="subtle"
                              size="compact-xs"
                              onClick={() =>
                                api.models.archive(m.id).then(() =>
                                  queryClient.invalidateQueries({ queryKey: ["models"] }),
                                )
                              }
                            >
                              Archive
                            </Button>
                          ) : (
                            <Button
                              variant="subtle"
                              size="compact-xs"
                              onClick={() =>
                                api.models.unarchive(m.id).then(() =>
                                  queryClient.invalidateQueries({ queryKey: ["models"] }),
                                )
                              }
                            >
                              Unarchive
                            </Button>
                          )}
                          <Button
                            variant="subtle"
                            color="red"
                            size="compact-xs"
                            leftSection={<IconTrash size={14} />}
                            onClick={() => {
                              if (
                                window.confirm(
                                  `Delete ${m.name}? Run data for this model will be lost.`,
                                )
                              ) {
                                deleteMutation.mutate(m.id);
                              }
                            }}
                          >
                            Remove
                          </Button>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </>
          )}

          <Divider my="sm" />

          <Title order={4}>Benchmarks</Title>
          <Text size="sm" c="dimmed">
            Coverage is controlled by run tier (Smoke / Standard / Thorough) on the Models
            page — not by per-suite toggles. Every tier runs format coherency, the eight
            quality axes, and speed; Smoke uses the smallest fixed item sets.
          </Text>
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

          <Title order={4}>Danger zone</Title>
          <Text size="sm" c="dimmed">
            Permanently delete all benchmark runs, scores, and logs. Models and settings are
            kept. Stop any running benchmark first.
          </Text>
          <Button
            variant="light"
            color="red"
            leftSection={<IconTrash size={16} />}
            onClick={openClear}
          >
            Clear All Benchmarks
          </Button>

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
              onClick={() => mutation.mutate()}
            >
              Save Settings
            </Button>
          </Group>
        </Stack>
      </Card>

      <Modal
        opened={clearOpen}
        onClose={closeClear}
        title="Clear all benchmarks?"
        centered
      >
        <Stack>
          <Text size="sm">
            This permanently deletes every benchmark run, score, and log. Model registry and
            settings are not affected. This cannot be undone.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={closeClear}>
              Cancel
            </Button>
            <Button
              color="red"
              leftSection={<IconAlertTriangle size={16} />}
              loading={clearBenchmarksMutation.isPending}
              onClick={() => clearBenchmarksMutation.mutate()}
            >
              Clear everything
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
