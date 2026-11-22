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

type GalleryRow = {
  attempt_uuid: string;
  challenge_id?: string;
  status: string;
  model_name?: string;
  created_at?: string;
};

export function CreativeArenaPage() {
  const [challengeId, setChallengeId] = useState<string | null>(null);
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

  useEffect(() => {
    if (challengeId || !challenges.data?.length) return;
    setChallengeId(challenges.data[0]?.id ?? null);
  }, [challengeId, challenges.data]);

  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const modelMaps = useMemo(() => buildModelMaps(models.data ?? []), [models.data]);

  const runningModels = useMemo(
    () => (models.data ?? []).filter((m) => m.is_active || m.status === "active"),
    [models.data],
  );

  const modelOptions = useMemo(
    () =>
      runningModels.map((m) => ({
        value: m.name,
        label: m.host ? `${m.name} · ${m.host}` : m.name,
      })),
    [runningModels],
  );

  useEffect(() => {
    if (modelName && runningModels.some((m) => m.name === modelName)) return;
    if (runningModels.length === 0) {
      setModelName(null);
      return;
    }
    setModelName(runningModels[0]?.name ?? null);
  }, [modelName, runningModels]);

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
    queryKey: ["creative-gallery", challengeId],
    queryFn: () =>
      creativeFetch<GalleryRow[]>(
        `/attempts?limit=50${challengeId ? `&challenge_id=${encodeURIComponent(challengeId)}` : ""}`,
      ),
    enabled: Boolean(challengeId),
  });

  const attemptOptions = useMemo(() => {
    return (gallery.data ?? []).map((row) => {
      const when = row.created_at
        ? new Date(row.created_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })
        : "";
      return {
        value: row.attempt_uuid,
        label: `${row.model_name ?? "unknown"} · ${row.status}${when ? ` · ${when}` : ""}`,
      };
    });
  }, [gallery.data]);

  useEffect(() => {
    if (!attemptUuid || !gallery.data) return;
    if (!gallery.data.some((r) => r.attempt_uuid === attemptUuid)) {
      setAttemptUuid(null);
      setEvents([]);
      setSelectedFile(null);
      setFileContent("");
    }
  }, [challengeId, gallery.data, attemptUuid]);

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

  const challengeOptions = useMemo(
    () =>
      (challenges.data ?? []).map((c) => ({
        value: c.id,
        label: c.title,
      })),
    [challenges.data],
  );

  const previewUrl = attemptUuid ? `/api/creative/attempts/${attemptUuid}/preview/` : null;
  const canViewResults = Boolean(
    previewUrl && (fileList.data?.files ?? []).some((f) => f === "index.html" || f.endsWith("/index.html")),
  );

  const openResults = () => {
    if (!previewUrl) return;
    window.open(previewUrl, "_blank", "noopener,noreferrer");
  };

  return (
    <Stack p="md" gap="md">
      <Title order={3}>Creative Arena</Title>
      <Text size="sm" c="dimmed">
        Monitor the agent here; use View results to open the app in a new tab when ready (later: Kasm on liminal via
        Caddy). Mock stream until live OpenCode + worker pin (ADR-006).
      </Text>

      <Group align="flex-end" grow preventGrowOverflow={false} wrap="wrap">
        <Select
          label="Challenge"
          data={challengeOptions}
          value={challengeId}
          onChange={setChallengeId}
          disabled={challengeOptions.length === 0}
          searchable={challengeOptions.length > 6}
          style={{ flex: 1, minWidth: 200 }}
        />
        <Select
          label="Recent attempts"
          placeholder={attemptOptions.length ? "Choose an attempt" : "No attempts for this challenge"}
          data={attemptOptions}
          value={attemptUuid}
          onChange={(v) => (v ? openAttempt(v) : setAttemptUuid(null))}
          clearable
          searchable
          disabled={attemptOptions.length === 0}
          style={{ flex: 1, minWidth: 240 }}
        />
      </Group>

      {models.isLoading ? (
        <Loader size="sm" />
      ) : modelOptions.length === 0 ? (
        <Text c="dimmed">No active models on LiteLLM. Run Discover in Settings, then retry.</Text>
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
          {attemptUuid && (
            <Button variant="light" disabled={!canViewResults} onClick={openResults}>
              View results
            </Button>
          )}
        </Group>
      )}

      {attemptUuid && (
        <Grid>
          <Grid.Col span={{ base: 12, md: 4 }}>
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
          <Grid.Col span={{ base: 12, md: 8 }}>
            <Card withBorder padding="sm" h={420}>
              <Group justify="space-between" mb="xs">
                <Text fw={600} size="sm">
                  Agent stream
                </Text>
                <Button size="compact-xs" variant="subtle" disabled={!canViewResults} onClick={openResults}>
                  View results
                </Button>
              </Group>
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
        </Grid>
      )}
    </Stack>
  );
}