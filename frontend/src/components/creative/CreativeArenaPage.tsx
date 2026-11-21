import { Button, Code, Group, Stack, Text, Textarea, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";

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
  const [modelName, setModelName] = useState("");
  const [attemptUuid, setAttemptUuid] = useState<string | null>(null);
  const [source, setSource] = useState<string>("");

  const challenges = useQuery({
    queryKey: ["creative-challenges"],
    queryFn: () => creativeFetch<{ id: string; title: string }[]>("/challenges"),
    retry: false,
  });

  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });

  if (challenges.isError) {
    return (
      <Stack p="md">
        <Title order={3}>Creative Arena</Title>
        <Text c="dimmed">
          Disabled. Set BENCHBASE_CREATIVE_ARENA=1 or creative_arena_enabled in settings.
        </Text>
      </Stack>
    );
  }

  return (
    <Stack p="md" gap="md">
      <Title order={3}>Creative Arena</Title>
      <Text size="sm" c="dimmed">
        Volcano & Skunk challenge (mock harness for vNext foundation).
      </Text>
      <Group>
        <Textarea
          placeholder="Model name"
          value={modelName}
          onChange={(e) => setModelName(e.currentTarget.value)}
          minRows={1}
          style={{ flex: 1 }}
        />
        <Button
          disabled={!modelName.trim()}
          onClick={async () => {
            const out = await creativeFetch<{ attempt_uuid: string }>("/attempts/mock", {
              method: "POST",
              body: JSON.stringify({ model_name: modelName }),
            });
            setAttemptUuid(out.attempt_uuid);
            const file = await creativeFetch<{ content: string }>(
              `/attempts/${out.attempt_uuid}/source/index.html`,
            );
            setSource(file.content);
          }}
        >
          Run mock attempt
        </Button>
      </Group>
      {attemptUuid && (
        <Stack gap="xs">
          <Text size="sm">Attempt {attemptUuid}</Text>
          <Code block>{source || "…"}</Code>
        </Stack>
      )}
      {models.data?.length ? (
        <Text size="xs" c="dimmed">
          {models.data.length} models in registry
        </Text>
      ) : null}
    </Stack>
  );
}