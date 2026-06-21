import {
  Button,
  Card,
  Divider,
  Group,
  Loader,
  PasswordInput,
  Stack,
  TextInput,
  Title,
  Switch,
  MultiSelect,
  useMantineColorScheme,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDeviceFloppy, IconRefresh, IconHeartbeat } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type AppSettings } from "../../api/client";

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
    mutationFn: api.models.discover,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      const activeList = data.active.length > 0 ? data.active.join(", ") : "none";
      const inactiveList = data.inactive.length > 0 ? data.inactive.join(", ") : "none";
      notifications.show({
        title: "Discovery complete",
        message: `${data.discovered} models found. Active: ${activeList}. Inactive: ${inactiveList}.`,
        color: data.inactive.length > 0 ? "yellow" : "green",
        autoClose: 8000,
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Discovery failed", message: err.message, color: "red" });
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
              onClick={() => discoverMutation.mutate()}
            >
              Discover Models
            </Button>
            <Button
              variant="subtle"
              leftSection={<IconHeartbeat size={16} />}
              loading={recheckMutation.isPending}
              onClick={() => recheckMutation.mutate()}
            >
              Re-check Health
            </Button>
          </Group>

          <Divider my="sm" />

          <Title order={4}>Benchmarks</Title>
          <MultiSelect
            label="Enabled Suites"
            data={SUITE_OPTIONS}
            value={form.benchmark_suites ?? []}
            onChange={(v) => setForm({ ...form, benchmark_suites: v })}
          />

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
