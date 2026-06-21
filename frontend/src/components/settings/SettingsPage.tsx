import {
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Stack,
  TextInput,
  Title,
  Switch,
  MultiSelect,
  useMantineColorScheme,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDeviceFloppy, IconRefresh } from "@tabler/icons-react";
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
      notifications.show({
        title: "Discovery complete",
        message: `Found ${data.discovered} models, added ${data.added.length} new.`,
        color: "blue",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Discovery failed", message: err.message, color: "red" });
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
          <Group>
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              loading={discoverMutation.isPending}
              onClick={() => discoverMutation.mutate()}
            >
              Discover Models
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
