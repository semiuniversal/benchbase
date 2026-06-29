import {
  Box,
  Button,
  Group,
  MultiSelect,
  Stack,
  Text,
  Textarea,
  Title,
  Badge,
} from "@mantine/core";
import { IconSend } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../../api/client";
import {
  asModelColor,
  buildModelMaps,
  modelColor,
  ModelColumnAccent,
  ModelDot,
  ModelHeading,
} from "../models/ModelColor";

const MAX_MODELS = 6;

interface ModelStream {
  thinking: string;
  content: string;
  metrics: {
    output_ttft: number | null;
    output_tokens: number;
    thinking_tokens: number;
    tokens_per_second: number;
    elapsed: number;
  } | null;
}

function ModelColumn({
  modelName,
  modelColorName,
  stream,
  running,
  columnCount,
  scrollRef,
}: {
  modelName: string;
  modelColorName: string;
  stream: ModelStream | undefined;
  running: boolean;
  columnCount: number;
  scrollRef: (el: HTMLDivElement | null) => void;
}) {
  const color = asModelColor(modelColorName);
  const hasThinking = Boolean(stream?.thinking);
  const waiting = running && !stream?.content && !hasThinking;
  const contentSize = columnCount > 4 ? "0.8125rem" : columnCount > 2 ? "0.875rem" : undefined;

  return (
    <ModelColumnAccent color={color}>
    <Box
      style={{
        flex: "1 1 0",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: "var(--mantine-radius-sm)",
        background: "var(--mantine-color-body)",
      }}
    >
      <Group
        justify="space-between"
        wrap="nowrap"
        gap="xs"
        p="xs"
        style={{
          flexShrink: 0,
          borderBottom: "1px solid var(--mantine-color-default-border)",
        }}
      >
        <ModelHeading name={modelName} color={color} size="sm" />
        {stream?.metrics && (
          <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
            {stream.metrics.output_ttft != null && (
              <Badge variant="light" color="blue" size="xs">
                Out TTFT {stream.metrics.output_ttft}s
              </Badge>
            )}
            <Badge variant="light" color="green" size="xs">
              {stream.metrics.tokens_per_second} out tok/s
            </Badge>
            <Badge variant="light" color="grape" size="xs">
              {stream.metrics.output_tokens} out
            </Badge>
          </Group>
        )}
      </Group>

      <Box
        ref={scrollRef}
        p="sm"
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          overflowX: "hidden",
          fontSize: contentSize,
        }}
      >
        {hasThinking && (
          <Box
            mb="sm"
            p="xs"
            style={{
              background: "var(--mantine-color-default-hover)",
              borderRadius: "var(--mantine-radius-sm)",
              fontSize: "0.85em",
              opacity: 0.9,
            }}
          >
            <Text size="xs" fw={600} c="dimmed" mb={4}>
              Thinking
            </Text>
            <ReactMarkdown>{stream?.thinking ?? ""}</ReactMarkdown>
          </Box>
        )}

        {stream?.content ? (
          <ReactMarkdown>{stream.content}</ReactMarkdown>
        ) : waiting ? (
          <Text c="dimmed" size="sm">
            {hasThinking ? "Thinking…" : "Waiting…"}
          </Text>
        ) : (
          <Text c="dimmed" size="sm">—</Text>
        )}
      </Box>
    </Box>
    </ModelColumnAccent>
  );
}

export function ArenaPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [streams, setStreams] = useState<Record<string, ModelStream>>({});
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const setColumnScrollRef = useCallback(
    (model: string, el: HTMLDivElement | null) => {
      scrollRefs.current[model] = el;
    },
    [],
  );

  useLayoutEffect(() => {
    selected.forEach((model) => {
      const el = scrollRefs.current[model];
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }, [streams, selected, running]);

  const handleSend = useCallback(async () => {
    if (!prompt.trim() || selected.length === 0) return;
    setRunning(true);
    const initial: Record<string, ModelStream> = {};
    selected.forEach((m) => {
      initial[m] = { thinking: "", content: "", metrics: null };
    });
    setStreams(initial);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/arena/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          models: selected,
          temperature: 0.7,
        }),
        signal: controller.signal,
      });

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.model) {
                const kind: string = data.kind ?? "content";
                setStreams((prev) => {
                  const cur = prev[data.model] ?? { thinking: "", content: "", metrics: null };
                  return {
                    ...prev,
                    [data.model]: {
                      thinking: kind === "thinking"
                        ? cur.thinking + (data.content ?? "")
                        : cur.thinking,
                      content: kind === "content"
                        ? cur.content + (data.content ?? "")
                        : cur.content,
                      metrics: data.metrics ?? cur.metrics,
                    },
                  };
                });
              }
            } catch {
              // skip malformed
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        console.error("Arena stream error:", err);
      }
    } finally {
      setRunning(false);
    }
  }, [prompt, selected]);

  const modelMaps = buildModelMaps(models.data ?? []);

  const modelOptions =
    models.data
      ?.filter((m) => m.is_active)
      .map((m) => ({ value: m.name, label: m.name })) ?? [];

  const showColumns = selected.length > 0;

  return (
    <Stack
      gap="sm"
      h="calc(100dvh - 56px - 32px)"
      style={{ minHeight: 420 }}
    >
      <Box style={{ flexShrink: 0 }}>
        <Title order={2} mb={4}>Arena</Title>
        <Text c="dimmed" size="sm" mb="sm">
          Compare models side-by-side — each column streams independently so you can
          read responses as they generate.
        </Text>

        <MultiSelect
          label="Models"
          placeholder="Choose up to 6 models"
          data={modelOptions}
          value={selected}
          onChange={setSelected}
          maxValues={MAX_MODELS}
          renderOption={({ option }) => (
            <Group gap="xs">
              <ModelDot color={modelColor(modelMaps, { name: option.value })} />
              <span>{option.label}</span>
            </Group>
          )}
        />

        <Textarea
          label="Prompt"
          placeholder="Enter your prompt… (Enter to send, Shift+Enter for new line)"
          minRows={2}
          autosize
          maxRows={5}
          mt="sm"
          value={prompt}
          onChange={(e) => setPrompt(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
        />

        <Group mt="sm">
          <Button
            leftSection={<IconSend size={16} />}
            onClick={handleSend}
            loading={running}
            disabled={!prompt.trim() || selected.length === 0}
          >
            Send
          </Button>
          {running && (
            <Button
              variant="light"
              color="red"
              onClick={() => abortRef.current?.abort()}
            >
              Stop
            </Button>
          )}
        </Group>
      </Box>

      {showColumns ? (
        <Box
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            gap: "var(--mantine-spacing-xs)",
          }}
        >
          {selected.map((modelName) => (
            <ModelColumn
              key={modelName}
              modelName={modelName}
              modelColorName={modelMaps.byName[modelName]?.color ?? "blue"}
              stream={streams[modelName]}
              running={running}
              columnCount={selected.length}
              scrollRef={(el) => setColumnScrollRef(modelName, el)}
            />
          ))}
        </Box>
      ) : (
        <Box
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: "1px dashed var(--mantine-color-default-border)",
            borderRadius: "var(--mantine-radius-sm)",
          }}
        >
          <Text c="dimmed" size="sm">
            Select models above to open comparison columns
          </Text>
        </Box>
      )}
    </Stack>
  );
}
