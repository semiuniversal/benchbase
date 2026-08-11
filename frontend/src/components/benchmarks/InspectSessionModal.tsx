import {
  Badge,
  Code,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type AgenticAttemptSummary,
  type AgenticTurn,
  type AgenticWorkspaceEntry,
} from "../../api/client";
import { ModelTag } from "../models/ModelColor";

interface InspectSessionModalProps {
  runId: number;
  modelName: string;
  modelColor?: string;
  displayLabel?: string | null;
  runStatus: string;
  opened: boolean;
  onClose: () => void;
  initialItemId?: string | null;
}

function turnKey(t: AgenticTurn, i: number) {
  return `${t.kind}:${t.ts ?? ""}:${t.tool ?? ""}:${t.toolCallId ?? ""}:${i}:${(t.text || t.result || "").slice(0, 40)}`;
}

function formatElapsed(startedAt?: number | null) {
  if (!startedAt) return null;
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function InspectSessionModal({
  runId,
  modelName,
  modelColor,
  displayLabel,
  runStatus,
  opened,
  onClose,
  initialItemId,
}: InspectSessionModalProps) {
  const [attempts, setAttempts] = useState<AgenticAttemptSummary[]>([]);
  const [itemId, setItemId] = useState<string | null>(null);
  const [turns, setTurns] = useState<AgenticTurn[]>([]);
  const [tree, setTree] = useState<AgenticWorkspaceEntry[]>([]);
  const [instruction, setInstruction] = useState<string | null>(null);
  const [fixture, setFixture] = useState<string | null>(null);
  const [filePath, setFilePath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [live, setLive] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => attempts.find((a) => a.item_id === itemId) ?? null,
    [attempts, itemId],
  );

  useEffect(() => {
    if (!opened || !live) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [opened, live]);

  useEffect(() => {
    if (!opened) return;
    let cancelled = false;
    setError(null);
    setTurns([]);
    setTree([]);
    setFilePath(null);
    setFileContent("");

    (async () => {
      try {
        const data = await api.benchmarks.agenticAttempts(runId);
        if (cancelled) return;
        setAttempts(data.attempts);
        const preferred =
          initialItemId ||
          data.current?.item_id ||
          data.attempts.find((a) => a.transcript_exists)?.item_id ||
          data.attempts[0]?.item_id ||
          null;
        setItemId(preferred);
        if (data.current?.started_at) setStartedAt(data.current.started_at);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [opened, runId, initialItemId]);

  useEffect(() => {
    if (!opened || !itemId) return;
    let cancelled = false;
    let es: EventSource | null = null;

    (async () => {
      setTurns([]);
      setError(null);
      try {
        const ws = await api.benchmarks.agenticWorkspace(runId, itemId);
        if (cancelled) return;
        setTree(ws.tree);
        setFixture(ws.fixture);
        setInstruction(ws.instruction);
        const firstFile = ws.tree.find((e) => e.type === "file");
        if (firstFile) {
          setFilePath(firstFile.path);
          const file = await api.benchmarks.agenticWorkspaceFile(
            runId,
            itemId,
            firstFile.path,
          );
          if (!cancelled) setFileContent(file.content);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }

      const running = runStatus === "running" || runStatus === "pending";
      if (running) {
        setLive(true);
        es = new EventSource(
          `/api/benchmarks/runs/${runId}/agentic/attempts/${encodeURIComponent(itemId)}/events`,
        );
        es.addEventListener("turn", (event) => {
          try {
            const turn = JSON.parse((event as MessageEvent).data) as AgenticTurn;
            setTurns((prev) => [...prev, turn]);
          } catch {
            // skip
          }
        });
        es.addEventListener("done", () => {
          setLive(false);
          es?.close();
          es = null;
        });
        es.onerror = () => {
          setLive(false);
          es?.close();
        };
      } else {
        setLive(false);
        try {
          const tx = await api.benchmarks.agenticTranscript(runId, itemId);
          if (!cancelled) setTurns(tx.events);
        } catch (e) {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      cancelled = true;
      es?.close();
    };
  }, [opened, runId, itemId, runStatus]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length]);

  const openFile = async (path: string) => {
    if (!itemId) return;
    setFilePath(path);
    try {
      const file = await api.benchmarks.agenticWorkspaceFile(runId, itemId, path);
      setFileContent(file.content);
    } catch (e) {
      setFileContent(e instanceof Error ? e.message : String(e));
    }
  };

  const elapsed = live ? formatElapsed(startedAt) : null;
  void tick;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="95vw"
      title={
        <Group gap="sm">
          <Title order={4}>Inspect session</Title>
          <ModelTag name={modelName} color={modelColor ?? "gray"} />
          {displayLabel && (
            <Text size="sm" c="dimmed">
              {displayLabel}
            </Text>
          )}
          {live && <Badge color="blue">live</Badge>}
          {selected?.passed === true && <Badge color="green">PASS</Badge>}
          {selected?.passed === false && <Badge color="red">FAIL</Badge>}
        </Group>
      }
      styles={{ body: { height: "80vh", display: "flex", flexDirection: "column" } }}
    >
      <Stack gap="sm" style={{ flex: 1, minHeight: 0 }}>
        <Group justify="space-between" wrap="wrap">
          <Select
            label="Attempt"
            placeholder="Select attempt"
            data={attempts.map((a) => ({
              value: a.item_id,
              label: `${a.task_id} · seed ${a.seed}${a.transcript_exists ? "" : " (no transcript)"}`,
            }))}
            value={itemId}
            onChange={(v) => setItemId(v)}
            w={360}
            searchable
          />
          <Group gap="md">
            {fixture && (
              <Text size="sm" c="dimmed">
                fixture: {fixture}
              </Text>
            )}
            {selected?.tool_calls != null && (
              <Text size="sm">tools {selected.tool_calls}</Text>
            )}
            {selected?.turns != null && <Text size="sm">turns {selected.turns}</Text>}
            {selected?.wall_seconds != null && (
              <Text size="sm">{Number(selected.wall_seconds).toFixed(1)}s</Text>
            )}
            {elapsed && <Text size="sm">elapsed {elapsed}</Text>}
          </Group>
        </Group>

        {error && (
          <Text size="sm" c="red">
            {error}
          </Text>
        )}

        <Group align="stretch" gap="md" style={{ flex: 1, minHeight: 0 }} grow>
          <Stack gap={6} style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
            <Text size="sm" fw={600}>
              Workspace
            </Text>
            <Group align="stretch" gap="xs" style={{ flex: 1, minHeight: 0 }} grow>
              <ScrollArea
                style={{
                  flex: "0 0 40%",
                  border: "1px solid var(--mantine-color-default-border)",
                  borderRadius: 4,
                }}
              >
                <Stack gap={2} p="xs">
                  {tree
                    .filter((e) => e.type === "file")
                    .map((e) => (
                      <UnstyledButton
                        key={e.path}
                        onClick={() => openFile(e.path)}
                        style={{
                          textAlign: "left",
                          padding: "2px 6px",
                          borderRadius: 3,
                          background:
                            filePath === e.path
                              ? "var(--mantine-color-blue-light)"
                              : undefined,
                        }}
                      >
                        <Text size="xs" ff="monospace">
                          {e.path}
                        </Text>
                      </UnstyledButton>
                    ))}
                  {tree.length === 0 && (
                    <Text size="xs" c="dimmed">
                      No files
                    </Text>
                  )}
                </Stack>
              </ScrollArea>
              <ScrollArea
                style={{
                  flex: 1,
                  border: "1px solid var(--mantine-color-default-border)",
                  borderRadius: 4,
                  background: "var(--mantine-color-dark-8)",
                }}
              >
                <Code
                  block
                  style={{
                    background: "transparent",
                    color: "var(--mantine-color-gray-2)",
                    whiteSpace: "pre-wrap",
                    fontSize: 12,
                  }}
                >
                  {filePath ? `${filePath}\n\n${fileContent}` : "Select a file"}
                </Code>
              </ScrollArea>
            </Group>
          </Stack>

          <Stack gap={6} style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
            <Text size="sm" fw={600}>
              Transcript
            </Text>
            <ScrollArea
              viewportRef={scrollRef}
              style={{
                flex: 1,
                border: "1px solid var(--mantine-color-default-border)",
                borderRadius: 4,
                background: "var(--mantine-color-dark-8)",
              }}
            >
              <Stack gap="sm" p="sm">
                {instruction && (
                  <Stack gap={4}>
                    <Badge size="xs" variant="outline" color="gray">
                      instruction
                    </Badge>
                    <Text size="sm" c="gray.2" style={{ whiteSpace: "pre-wrap" }}>
                      {instruction}
                    </Text>
                  </Stack>
                )}
                {turns.map((t, i) => (
                  <Stack key={turnKey(t, i)} gap={4}>
                    {t.kind === "user" && (
                      <>
                        <Badge size="xs" color="cyan">
                          user
                        </Badge>
                        <Text size="sm" c="gray.2" style={{ whiteSpace: "pre-wrap" }}>
                          {t.text}
                        </Text>
                      </>
                    )}
                    {t.kind === "assistant" && (
                      <>
                        <Badge size="xs" color="violet">
                          assistant
                        </Badge>
                        <Text size="sm" c="gray.1" style={{ whiteSpace: "pre-wrap" }}>
                          {t.text}
                        </Text>
                      </>
                    )}
                    {t.kind === "tool_call" && (
                      <>
                        <Badge size="xs" color="yellow">
                          tool · {t.tool}
                        </Badge>
                        <Code
                          block
                          style={{
                            background: "transparent",
                            color: "var(--mantine-color-yellow-2)",
                            fontSize: 11,
                          }}
                        >
                          {JSON.stringify(t.args ?? {}, null, 2)}
                        </Code>
                      </>
                    )}
                    {t.kind === "tool_result" && (
                      <>
                        <Badge size="xs" color={t.isError ? "red" : "teal"}>
                          result · {t.tool}
                        </Badge>
                        <Code
                          block
                          style={{
                            background: "transparent",
                            color: t.isError
                              ? "var(--mantine-color-red-3)"
                              : "var(--mantine-color-teal-2)",
                            fontSize: 11,
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {(t.result || "").slice(0, 4000)}
                        </Code>
                      </>
                    )}
                    {t.kind === "end" && (
                      <Badge size="xs" color="gray">
                        end · {t.type}
                      </Badge>
                    )}
                  </Stack>
                ))}
                {turns.length === 0 && !instruction && (
                  <Text size="sm" c="dimmed">
                    {live ? "Waiting for events…" : "No transcript events"}
                  </Text>
                )}
                <div ref={bottomRef} />
              </Stack>
            </ScrollArea>
          </Stack>
        </Group>
      </Stack>
    </Modal>
  );
}
