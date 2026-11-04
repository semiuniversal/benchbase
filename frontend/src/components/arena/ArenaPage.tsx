import {
  ActionIcon,
  Box,
  Button,
  FileButton,
  Group,
  Image,
  MultiSelect,
  Stack,
  Text,
  Textarea,
  Title,
  Badge,
  Tooltip,
} from "@mantine/core";
import { IconPhotoPlus, IconSend, IconX } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type CSSProperties,
  type ImgHTMLAttributes,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type ModelRecord } from "../../api/client";
import {
  asModelColor,
  buildModelMaps,
  modelColor,
  ModelColumnAccent,
  ModelDot,
  ModelHeading,
} from "../models/ModelColor";

const MAX_MODELS = 6;
const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
const VISION_UNSUPPORTED_MSG = "The selected model has no vision support.";
const ALLOWED_MIME = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

const arenaMarkdownComponents = {
  pre: ({ children }: { children?: ReactNode }) => (
    <pre
      style={{
        maxWidth: "100%",
        margin: 0,
        overflowX: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {children}
    </pre>
  ),
  code: ({
    className,
    children,
  }: {
    className?: string;
    children?: ReactNode;
  }) => {
    const isBlock = Boolean(className?.includes("language-"));
    if (isBlock) {
      return <code className={className}>{children}</code>;
    }
    return (
      <code style={{ wordBreak: "break-word", overflowWrap: "anywhere" }}>
        {children}
      </code>
    );
  },
  table: ({ children }: { children?: ReactNode }) => (
    <Box style={{ maxWidth: "100%", overflowX: "auto", margin: "0.5rem 0" }}>
      <table
        style={{
          borderCollapse: "collapse",
          width: "max-content",
          minWidth: "100%",
          wordBreak: "normal",
          overflowWrap: "normal",
        }}
      >
        {children}
      </table>
    </Box>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        padding: "4px 8px",
        textAlign: "left",
        fontWeight: 700,
        whiteSpace: "nowrap",
        wordBreak: "normal",
      }}
    >
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td
      style={{
        border: "1px solid var(--mantine-color-default-border)",
        padding: "4px 8px",
        textAlign: "left",
        verticalAlign: "top",
        wordBreak: "normal",
        overflowWrap: "break-word",
      }}
    >
      {children}
    </td>
  ),
  img: (props: ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line jsx-a11y/alt-text -- markdown supplies alt when present
    <img {...props} style={{ maxWidth: "100%", height: "auto" }} />
  ),
};

const arenaMarkdownStyle: CSSProperties = {
  maxWidth: "100%",
  overflowWrap: "anywhere",
  wordBreak: "break-word",
};

function ArenaMarkdown({ children }: { children: string }) {
  return (
    <Box style={arenaMarkdownStyle}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={arenaMarkdownComponents}>
        {children}
      </ReactMarkdown>
    </Box>
  );
}

interface ModelStream {
  thinking: string;
  content: string;
  error: string | null;
  metrics: {
    output_ttft: number | null;
    output_tokens: number;
    thinking_tokens: number;
    tokens_per_second: number;
    elapsed: number;
  } | null;
}

interface AttachedImage {
  id: string;
  mime: string;
  dataUrl: string;
  dataBase64: string;
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
  const hasError = Boolean(stream?.error);
  const waiting = running && !stream?.content && !hasThinking && !hasError;
  const contentSize = columnCount > 4 ? "0.8125rem" : columnCount > 2 ? "0.875rem" : undefined;

  return (
    <Box
      style={{
        minWidth: 0,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <ModelColumnAccent color={color}>
        <Box
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            width: "100%",
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
          {hasError && (
            <Text c="red" fw={600} size="sm" mb="sm">
              {stream?.error}
            </Text>
          )}

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
              <ArenaMarkdown>{stream?.thinking ?? ""}</ArenaMarkdown>
            </Box>
          )}

          {stream?.content ? (
            <ArenaMarkdown>{stream.content}</ArenaMarkdown>
          ) : waiting ? (
            <Text c="dimmed" size="sm">
              {hasThinking ? "Thinking…" : "Waiting…"}
            </Text>
          ) : !hasError ? (
            <Text c="dimmed" size="sm">
              —
            </Text>
          ) : null}
        </Box>
        </Box>
      </ModelColumnAccent>
    </Box>
  );
}

function parseDataUrl(dataUrl: string): { mime: string; dataBase64: string } | null {
  const m = /^data:([^;]+);base64,(.+)$/s.exec(dataUrl);
  if (!m) return null;
  let mime = m[1].toLowerCase();
  if (mime === "image/jpg") mime = "image/jpeg";
  if (!ALLOWED_MIME.has(mime)) return null;
  return { mime, dataBase64: m[2] };
}

async function fileToAttached(file: File): Promise<AttachedImage | null> {
  let mime = (file.type || "").toLowerCase();
  if (mime === "image/jpg") mime = "image/jpeg";
  if (!ALLOWED_MIME.has(mime)) return null;
  if (file.size > MAX_IMAGE_BYTES) return null;
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  const parsed = parseDataUrl(dataUrl);
  if (!parsed) return null;
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    mime: parsed.mime,
    dataUrl,
    dataBase64: parsed.dataBase64,
  };
}

export function ArenaPage() {
  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const [selected, setSelected] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [images, setImages] = useState<AttachedImage[]>([]);
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

  const modelByName = useCallback(
    (name: string): ModelRecord | undefined =>
      models.data?.find((m) => m.name === name),
    [models.data],
  );

  const addImages = useCallback(async (files: File[]) => {
    const next: AttachedImage[] = [];
    for (const file of files) {
      if (images.length + next.length >= MAX_IMAGES) break;
      const attached = await fileToAttached(file);
      if (attached) next.push(attached);
    }
    if (next.length) setImages((prev) => [...prev, ...next].slice(0, MAX_IMAGES));
  }, [images.length]);

  const handlePaste = useCallback(
    async (e: ClipboardEvent) => {
      const items = Array.from(e.clipboardData?.items ?? []);
      const imageFiles: File[] = [];
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length === 0) return;
      e.preventDefault();
      await addImages(imageFiles);
    },
    [addImages],
  );

  const handleSend = useCallback(async () => {
    if (selected.length === 0) return;
    if (!prompt.trim() && images.length === 0) return;

    setRunning(true);
    const hasImages = images.length > 0;
    const initial: Record<string, ModelStream> = {};
    const visionModels: string[] = [];
    const blocked: string[] = [];

    selected.forEach((m) => {
      const supports = Boolean(modelByName(m)?.supports_vision);
      if (hasImages && !supports) {
        blocked.push(m);
        initial[m] = {
          thinking: "",
          content: "",
          error: VISION_UNSUPPORTED_MSG,
          metrics: null,
        };
      } else {
        visionModels.push(m);
        initial[m] = { thinking: "", content: "", error: null, metrics: null };
      }
    });
    setStreams(initial);

    if (visionModels.length === 0) {
      setRunning(false);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/arena/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          models: visionModels,
          // Vision: cooler sampling; leave max_tokens unset (same as text) so outputs
          // are not truncated at 512 (finish_reason=length).
          temperature: hasImages ? 0.2 : 0.7,
          images: images.map((img) => ({
            mime: img.mime,
            data_base64: img.dataBase64,
          })),
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`API ${res.status}: ${body}`);
      }

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
                  const cur = prev[data.model] ?? {
                    thinking: "",
                    content: "",
                    error: null,
                    metrics: null,
                  };
                  if (kind === "error") {
                    return {
                      ...prev,
                      [data.model]: {
                        ...cur,
                        error: data.content ?? VISION_UNSUPPORTED_MSG,
                      },
                    };
                  }
                  return {
                    ...prev,
                    [data.model]: {
                      thinking:
                        kind === "thinking"
                          ? cur.thinking + (data.content ?? "")
                          : cur.thinking,
                      content:
                        kind === "content"
                          ? cur.content + (data.content ?? "")
                          : cur.content,
                      error: cur.error,
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
  }, [prompt, selected, images, modelByName]);

  const modelMaps = buildModelMaps(models.data ?? []);

  const modelOptions =
    models.data
      ?.filter((m) => m.is_active || m.status === "active")
      .map((m) => ({
        value: m.name,
        label: m.supports_vision ? `${m.name} · vision` : m.name,
      })) ?? [];

  const showColumns = selected.length > 0;
  const canSend =
    selected.length > 0 && (!!prompt.trim() || images.length > 0) && !running;

  return (
    <Stack
      gap="sm"
      h="calc(100dvh - 56px - 32px)"
      style={{ minHeight: 420 }}
    >
      <Box style={{ flexShrink: 0 }}>
        <Title order={2} mb={4}>
          Arena
        </Title>
        <Text c="dimmed" size="sm" mb="sm">
          Compare models side-by-side — each column streams independently so you can
          read responses as they generate. Paste or attach images for vision-capable
          models.
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

        {images.length > 0 && (
          <Group gap="xs" mt="sm" wrap="wrap">
            {images.map((img) => (
              <Box
                key={img.id}
                style={{
                  position: "relative",
                  width: 72,
                  height: 72,
                  borderRadius: 8,
                  overflow: "hidden",
                  border: "1px solid var(--mantine-color-default-border)",
                }}
              >
                <Image src={img.dataUrl} alt="attachment" h={72} w={72} fit="cover" />
                <ActionIcon
                  size="xs"
                  color="dark"
                  variant="filled"
                  radius="xl"
                  style={{ position: "absolute", top: 4, right: 4 }}
                  onClick={() =>
                    setImages((prev) => prev.filter((x) => x.id !== img.id))
                  }
                  aria-label="Remove image"
                >
                  <IconX size={12} />
                </ActionIcon>
              </Box>
            ))}
          </Group>
        )}

        <Textarea
          label="Prompt"
          placeholder="Enter your prompt… Paste images here. (Enter to send, Shift+Enter for new line)"
          minRows={2}
          autosize
          maxRows={5}
          mt="sm"
          value={prompt}
          onChange={(e) => setPrompt(e.currentTarget.value)}
          onPaste={handlePaste}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) handleSend();
            }
          }}
        />

        <Group mt="sm">
          <Button
            leftSection={<IconSend size={16} />}
            onClick={handleSend}
            loading={running}
            disabled={!canSend}
          >
            Send
          </Button>
          <FileButton
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            onChange={(files) => {
              if (files?.length) void addImages(files);
            }}
          >
            {(props) => (
              <Tooltip label={`Attach up to ${MAX_IMAGES} images`}>
                <Button
                  {...props}
                  variant="light"
                  leftSection={<IconPhotoPlus size={16} />}
                  disabled={running || images.length >= MAX_IMAGES}
                >
                  Attach
                </Button>
              </Tooltip>
            )}
          </FileButton>
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
            minWidth: 0,
            display: "grid",
            gridTemplateColumns: `repeat(${selected.length}, minmax(0, 1fr))`,
            gap: "var(--mantine-spacing-xs)",
            alignContent: "stretch",
            overflowX: selected.length > 2 ? "auto" : "hidden",
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
