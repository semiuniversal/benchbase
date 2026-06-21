import {
  Button,
  Card,
  Grid,
  Group,
  MultiSelect,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Title,
  Badge,
  Code,
} from "@mantine/core";
import { IconSend } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { api } from "../../api/client";

interface ModelStream {
  content: string;
  metrics: {
    ttft: number;
    tokens: number;
    tokens_per_second: number;
    elapsed: number;
  } | null;
}

export function ArenaPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [streams, setStreams] = useState<Record<string, ModelStream>>({});
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const handleSend = useCallback(async () => {
    if (!prompt.trim() || selected.length === 0) return;
    setRunning(true);
    const initial: Record<string, ModelStream> = {};
    selected.forEach((m) => {
      initial[m] = { content: "", metrics: null };
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
          max_tokens: 1024,
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
                setStreams((prev) => ({
                  ...prev,
                  [data.model]: {
                    content: (prev[data.model]?.content ?? "") + (data.content ?? ""),
                    metrics: data.metrics ?? prev[data.model]?.metrics,
                  },
                }));
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

  const modelOptions =
    models.data?.map((m) => ({ value: m.name, label: m.name })) ?? [];

  return (
    <Stack>
      <Title order={2}>Arena</Title>
      <Text c="dimmed">
        Send the same prompt to multiple models simultaneously and compare responses in real time.
      </Text>

      <MultiSelect
        label="Select models"
        placeholder="Choose models to compare"
        data={modelOptions}
        value={selected}
        onChange={setSelected}
      />

      <Textarea
        label="Prompt"
        placeholder="Enter your prompt..."
        minRows={3}
        value={prompt}
        onChange={(e) => setPrompt(e.currentTarget.value)}
      />

      <Group>
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

      <Grid>
        {selected.map((modelName) => (
          <Grid.Col key={modelName} span={{ base: 12, md: 6 }}>
            <Card withBorder shadow="sm" padding="md">
              <Group justify="space-between" mb="xs">
                <Title order={5}>{modelName}</Title>
                {streams[modelName]?.metrics && (
                  <Group gap="xs">
                    <Badge variant="light" color="blue" size="sm">
                      TTFT: {streams[modelName].metrics!.ttft}s
                    </Badge>
                    <Badge variant="light" color="green" size="sm">
                      {streams[modelName].metrics!.tokens_per_second} tok/s
                    </Badge>
                    <Badge variant="light" color="grape" size="sm">
                      {streams[modelName].metrics!.tokens} tokens
                    </Badge>
                  </Group>
                )}
              </Group>
              <ScrollArea h={300}>
                <Code block style={{ whiteSpace: "pre-wrap" }}>
                  {streams[modelName]?.content || (running ? "Waiting..." : "—")}
                </Code>
              </ScrollArea>
            </Card>
          </Grid.Col>
        ))}
      </Grid>
    </Stack>
  );
}
