import {
  Button,
  Card,
  Code,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { buildModelMaps, ModelDot, modelColor } from "../models/ModelColor";

async function creativeFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/creative${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json();
}

export function CreativeArenaPage() {
  const [modelName, setModelName] = useState<string | null>(null);
  const [attemptUuid, setAttemptUuid] = useState<string | null>(null);
  const [source, setSource] = useState<string>("");

  const challenges = useQuery({
    queryKey: ["creative-challenges"],
    queryFn: () => creativeFetch<{ id: string; title: string; prompt_sha256?: string }[]>(
      "/challenges",
    ),
    retry: false,
  });

  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });

  const modelMaps = useMemo(() => buildModelMaps(models.data ?? []), [models.data]);

  const modelOptions = useMemo(() => {
    const rows = models.data ?? [];
    const active = rows.filter((m) => m.is_active || m.status === "active");
    const other = rows.filter((m) => !m.is_active && m.status !== "active");
    const mapRow = (m: (typeof rows)[0]) => ({
      value: m.name,
      label: m.host ? `${m.name} · ${m.host}` : m.name,
    });
    return [
      ...active.map(mapRow),
      ...other.map((m) => ({
        ...mapRow(m),
        label: `${mapRow(m).label} (${m.status})`,
      })),
    ];
  }, [models.data]);

  useEffect(() => {
    if (modelName || modelOptions.length === 0) return;
    const firstActive = models.data?.find((m) => m.is_active || m.status === "active");
    setModelName(firstActive?.name ?? modelOptions[0]?.value ?? null);
  }, [modelName, modelOptions, models.data]);

  const runMock = useMutation({
    mutationFn: async (seat: string) => {
      const out = await creativeFetch<{ attempt_uuid: string }>("/attempts/mock", {
        method: "POST",
        body: JSON.stringify({ model_name: seat }),
      });
      const file = await creativeFetch<{ content: string }>(
        `/attempts/${out.attempt_uuid}/source/index.html`,
      );
      return { attempt_uuid: out.attempt_uuid, content: file.content };
    },
    onSuccess: (data) => {
      setAttemptUuid(data.attempt_uuid);
      setSource(data.content);
      notifications.show({
        title: "Mock attempt complete",
        message: `Workspace ${data.attempt_uuid.slice(0, 8)}…`,
        color: "green",
      });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Attempt failed", message: err.message, color: "red" });
    },
  });

  if (challenges.isError) {
    return (
      <Stack p="md">
        <Title order={3}>Creative Arena</Title>
        <Text c="dimmed">
          Disabled. Turn on Creative Arena in Settings, or set BENCHBASE_CREATIVE_ARENA=1 on the
          server.
        </Text>
      </Stack>
    );
  }

  const challenge = challenges.data?.[0];

  return (
    <Stack p="md" gap="md">
      <Title order={3}>Creative Arena</Title>
      <Text size="sm" c="dimmed">
        Build challenges for agentic coding seats. Mock harness materializes a sample workspace
        until the isolated worker (WP7) is live.
      </Text>

      {challenges.isLoading ? (
        <Loader size="sm" />
      ) : challenge ? (
        <Card withBorder padding="md">
          <Text fw={600}>{challenge.title}</Text>
          <Text size="xs" c="dimmed">
            Challenge id: {challenge.id}
          </Text>
        </Card>
      ) : null}

      {models.isLoading ? (
        <Loader size="sm" />
      ) : modelOptions.length === 0 ? (
        <Text c="dimmed">
          No models in the registry.{" "}
          <Text span component="a" href="/models" c="blue">
            Discover models
          </Text>{" "}
          first.
        </Text>
      ) : (
        <Group align="flex-end" wrap="wrap">
          <Select
            label="Model"
            description="Active seats from your registry (same list as Arena)"
            placeholder="Pick a model"
            data={modelOptions}
            value={modelName}
            onChange={setModelName}
            searchable
            clearable
            nothingFoundMessage="No matching model"
            style={{ flex: 1, minWidth: 280 }}
            renderOption={({ option }) => (
              <Group gap="xs" wrap="nowrap">
                <ModelDot color={modelColor(modelMaps, { name: option.value })} />
                <span>{option.label}</span>
              </Group>
            )}
          />
          <Button
            disabled={!modelName?.trim()}
            loading={runMock.isPending}
            onClick={() => modelName && runMock.mutate(modelName)}
          >
            Run mock attempt
          </Button>
        </Group>
      )}

      {attemptUuid && (
        <Stack gap="xs">
          <Text size="sm">
            Attempt <Code>{attemptUuid}</Code>
          </Text>
          <Text size="xs" c="dimmed">
            Generated <Code>index.html</Code> (mock harness)
          </Text>
          <Code block style={{ maxHeight: 480, overflow: "auto" }}>
            {source || "…"}
          </Code>
        </Stack>
      )}
    </Stack>
  );
}