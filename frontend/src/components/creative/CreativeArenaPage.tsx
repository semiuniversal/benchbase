import {
  Badge,
  Button,
  Card,
  Code,
  Grid,
  Group,
  Loader,
  ScrollArea,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { buildModelMaps, ModelDot, modelColor } from "../models/ModelColor";

type CreativeEvent = {
  kind: string;
  message?: string;
  tool?: string;
  path?: string;
  ts?: number;
};

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

function eventLine(e: CreativeEvent): string {
  const tool = e.tool ? `[${e.tool}] ` : "";
  const path = e.path ? `${e.path} — ` : "";
  return `${e.kind}: ${tool}${path}${e.message ?? ""}`;
}

export function CreativeArenaPage() {
  const [modelName, setModelName] = useState<string | null>(null);
  const [attemptUuid, setAttemptUuid] = useState<string | null>(null);
  const [events, setEvents] = useState<CreativeEvent[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const logEndRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const challenges = useQuery({
    queryKey: ["creative-challenges"],
    queryFn: () => creativeFetch<{ id: string; title: string }[]>("/challenges"),
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
    return [...active.map(mapRow), ...other.map((m) => ({ ...mapRow(m), label: `${mapRow(m).label} (${m.status})` }))];
  }, [models.data]);

  useEffect(() => {
    if (modelName || modelOptions.length === 0) return;
    const first = models.data?.find((m) => m.is_active || m.status === "active");
    setModelName(first?.name ?? modelOptions[0]?.value ?? null);
  }, [modelName, modelOptions, models.data]);

  const attemptStatus = useQuery({
    queryKey: ["creative-attempt", attemptUuid],
    queryFn: () => creativeFetch<{ status: string }>(`/attempts/${attemptUuid}`),
    enabled: Boolean(attemptUuid),
    refetchInterval: (q) => (q.state.data?.status === "completed" ? false : 2000),
  });

  const fileList = useQuery({
    queryKey: ["creative-files", attemptUuid],
    queryFn: () => creativeFetch<{ files: string[] }>(`/attempts/${attemptUuid}/source`),
    enabled: Boolean(attemptUuid),
    refetchInterval: attemptStatus.data?.status === "completed" ? false : 1500,
  });

  useEffect(() => {
    if (!attemptUuid) return;
    const es = new EventSource(`/api/creative/attempts/${attemptUuid}/events`);
    es.onmessage = (ev) => {
      try {
        const row = JSON.parse(ev.data) as CreativeEvent;
        setEvents((prev) => [...prev, row]);
        void queryClient.invalidateQueries({ queryKey: ["creative-files", attemptUuid] });
      } catch {
        /* ignore */
      }
    };
    es.addEventListener("creative", (ev) => {
      try {
        const row = JSON.parse((ev as MessageEvent).data) as CreativeEvent;
        setEvents((prev) => [...prev, row]);
        void queryClient.invalidateQueries({ queryKey: ["creative-files", attemptUuid] });
      } catch {
        /* ignore */
      }
    });
    es.addEventListener("done", () => {
      void queryClient.invalidateQueries({ queryKey: ["creative-attempt", attemptUuid] });
      void queryClient.invalidateQueries({ queryKey: ["creative-files", attemptUuid] });
      es.close();
    });
    return () => es.close();
  }, [attemptUuid, queryClient]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  useEffect(() => {
    if (!attemptUuid || !selectedFile) return;
    creativeFetch<{ content: string }>(`/attempts/${attemptUuid}/source/${selectedFile}`)
      .then((d) => setFileContent(d.content))
      .catch(() => setFileContent(""));
  }, [attemptUuid, selectedFile, fileList.dataUpdatedAt]);

  const gallery = useQuery({
    queryKey: ["creative-gallery"],
    queryFn: () =>
      creativeFetch<
        { attempt_uuid: string; status: string; model_name?: string; created_at?: string }[]
      >("/attempts"),
  });

  const openAttempt = (uuid: string) => {
    setAttemptUuid(uuid);
    setEvents([]);
    setSelectedFile(null);
    setFileContent("");
    void queryClient.invalidateQueries({ queryKey: ["creative-attempt", uuid] });
    void queryClient.invalidateQueries({ queryKey: ["creative-files", uuid] });
  };

  const startAttempt = useMutation({
    mutationFn: (seat: string) =>
      creativeFetch<{ attempt_uuid: string }>("/attempts/start", {
        method: "POST",
        body: JSON.stringify({ model_name: seat, harness: "mock" }),
      }),
    onSuccess: (data) => {
      setAttemptUuid(data.attempt_uuid);
      setEvents([]);
      setSelectedFile(null);
      setFileContent("");
      void queryClient.invalidateQueries({ queryKey: ["creative-gallery"] });
      notifications.show({ title: "Attempt started", message: data.attempt_uuid, color: "blue" });
    },
    onError: (err: Error) => {
      notifications.show({ title: "Start failed", message: err.message, color: "red" });
    },
  });

  if (challenges.isError) {
    return (
      <Stack p="md">
        <Title order={3}>Creative Arena</Title>
        <Text c="dimmed">
          Disabled. Turn on Creative Arena in Settings, or set BENCHBASE_CREATIVE_ARENA=1 on the server.
        </Text>
      </Stack>
    );
  }

  const challenge = challenges.data?.[0];
  const previewUrl = attemptUuid ? `/api/creative/attempts/${attemptUuid}/preview/` : null;

  return (
    <Stack p="md" gap="md">
      <Title order={3}>Creative Arena</Title>
      <Text size="sm" c="dimmed">
        OpenCode harness: skills live under corpus/creative/opencode/skills/ and copy into each attempt. Mock
        stream simulates tools until live OpenCode + worker pin (ADR-006).
      </Text>

      {challenge && (
        <Card withBorder padding="sm">
          <Group justify="space-between">
            <Text fw={600}>{challenge.title}</Text>
            <Badge variant="light">volcano-skunk-v1</Badge>
          </Group>
        </Card>
      )}

      {(gallery.data?.length ?? 0) > 0 && (
        <Card withBorder padding="sm">
          <Text fw={600} size="sm" mb="xs">
            Recent attempts
          </Text>
          <ScrollArea.Autosize mah={120} type="auto">
            <Stack gap={4}>
              {gallery.data?.map((row) => (
                <Group key={row.attempt_uuid} gap="xs" wrap="nowrap">
                  <Button
                    variant={attemptUuid === row.attempt_uuid ? "light" : "subtle"}
                    size="compact-xs"
                    onClick={() => openAttempt(row.attempt_uuid)}
                  >
                    {row.model_name ?? "unknown"} · {row.status}
                  </Button>
                  <Text size="xs" c="dimmed" truncate style={{ maxWidth: 180 }}>
                    {row.attempt_uuid.slice(0, 8)}
                  </Text>
                </Group>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        </Card>
      )}

      {models.isLoading ? (
        <Loader size="sm" />
      ) : modelOptions.length === 0 ? (
        <Text c="dimmed">Discover models first.</Text>
      ) : (
        <Group align="flex-end" wrap="wrap">
          <Select
            label="Model seat"
            data={modelOptions}
            value={modelName}
            onChange={setModelName}
            searchable
            style={{ flex: 1, minWidth: 280 }}
            renderOption={({ option }) => (
              <Group gap="xs">
                <ModelDot color={modelColor(modelMaps, { name: option.value })} />
                <span>{option.label}</span>
              </Group>
            )}
          />
          <Button
            disabled={!modelName}
            loading={startAttempt.isPending}
            onClick={() => modelName && startAttempt.mutate(modelName)}
          >
            Start attempt (mock)
          </Button>
          {attemptStatus.data && (
            <Badge color={attemptStatus.data.status === "completed" ? "green" : "blue"}>
              {attemptStatus.data.status}
            </Badge>
          )}
        </Group>
      )}

      {attemptUuid && (
        <Grid>
          <Grid.Col span={{ base: 12, md: 3 }}>
            <Card withBorder padding="sm" h={420}>
              <Text fw={600} size="sm" mb="xs">
                Workspace files
              </Text>
              <ScrollArea h={360} type="auto">
                {(fileList.data?.files ?? []).map((f) => (
                  <Text
                    key={f}
                    size="xs"
                    component="button"
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      background: selectedFile === f ? "var(--mantine-color-blue-light)" : undefined,
                      border: 0,
                      cursor: "pointer",
                      padding: "4px 6px",
                      borderRadius: 4,
                    }}
                    onClick={() => setSelectedFile(f)}
                  >
                    {f}
                  </Text>
                ))}
                {!fileList.data?.files?.length && <Text size="xs" c="dimmed">Waiting for agent…</Text>}
              </ScrollArea>
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Card withBorder padding="sm" h={420}>
              <Text fw={600} size="sm" mb="xs">
                Agent stream
              </Text>
              <ScrollArea h={300} type="auto">
                <Stack gap={4}>
                  {events.map((e, i) => (
                    <Text key={i} size="xs" ff="monospace">
                      {eventLine(e)}
                    </Text>
                  ))}
                  <div ref={logEndRef} />
                </Stack>
              </ScrollArea>
              {selectedFile && (
                <ScrollArea h={80} mt="xs">
                  <Code block fz="xs">
                    {fileContent.slice(0, 2000)}
                  </Code>
                </ScrollArea>
              )}
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Card withBorder padding="sm" h={420}>
              <Text fw={600} size="sm" mb="xs">
                Preview
              </Text>
              {previewUrl ? (
                <iframe
                  title="creative-preview"
                  src={previewUrl}
                  style={{ width: "100%", height: 360, border: "1px solid var(--mantine-color-default-border)", borderRadius: 8 }}
                  sandbox="allow-scripts allow-same-origin"
                />
              ) : (
                <Text size="xs" c="dimmed">
                  No preview
                </Text>
              )}
            </Card>
          </Grid.Col>
        </Grid>
      )}
    </Stack>
  );
}