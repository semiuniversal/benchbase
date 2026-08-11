import {
  Accordion,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArchive,
  IconEye,
  IconFlask,
  IconRocket,
  IconTrash,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type ModelDetail,
  type ModelRecord,
  type ModelRunSummary,
} from "../../api/client";
import {
  formatMean,
  formatPassRate,
  formatTeff,
  TEFF_GLOSSARY,
} from "./agenticScoreFormat";
import { buildModelMaps, modelColor, ModelColorPicker, ModelTag } from "./ModelColor";

function statusColor(status: string) {
  if (status === "active") return "green";
  if (status === "archived") return "gray";
  if (status === "unreachable") return "red";
  return "gray";
}

function ModelCard({
  model,
  detail,
  detailLoading,
  expanded,
  onToggle,
}: {
  model: ModelRecord;
  detail?: ModelDetail;
  detailLoading: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const maps = buildModelMaps([model]);
  const [notes, setNotes] = useState(model.notes ?? "");

  useEffect(() => {
    setNotes(detail?.model.notes ?? model.notes ?? "");
  }, [detail?.model.notes, model.notes, model.id]);

  const saveNotes = useMutation({
    mutationFn: () => api.models.update(model.id, { notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      queryClient.invalidateQueries({ queryKey: ["model-detail", model.id] });
      notifications.show({ title: "Notes saved", message: model.name, color: "green" });
    },
    onError: (e: Error) =>
      notifications.show({ title: "Save failed", message: e.message, color: "red" }),
  });

  const colorMutation = useMutation({
    mutationFn: (color: string) => api.models.update(model.id, { color }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["models"] }),
  });

  const archiveMutation = useMutation({
    mutationFn: () =>
      model.status === "archived"
        ? api.models.unarchive(model.id)
        : api.models.archive(model.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      queryClient.invalidateQueries({ queryKey: ["model-detail", model.id] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.models.delete(model.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models"] });
      notifications.show({ title: "Deleted", message: model.name, color: "orange" });
    },
  });

  const tiers = detail?.tiers;
  const last = detail?.last_agentic;
  const eligible = model.finalist_eligible ?? tiers?.finalist_eligible ?? false;

  return (
    <Card withBorder shadow="sm" padding="md">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Group gap="sm">
          <ModelColorPicker
            color={modelColor(maps, { id: model.id })}
            disabled={colorMutation.isPending}
            onChange={(c) => colorMutation.mutate(c)}
          />
          <Stack gap={2}>
            <ModelTag name={model.name} color={modelColor(maps, { id: model.id })} />
            <Group gap={6}>
              <Badge size="sm" color={statusColor(model.status)} variant="light">
                {model.status}
              </Badge>
              {model.supports_vision && (
                <Badge size="sm" variant="outline">
                  vision
                </Badge>
              )}
              {model.context_window != null && (
                <Badge size="sm" variant="outline">
                  ctx {model.context_window.toLocaleString()}
                </Badge>
              )}
              {eligible ? (
                <Badge size="sm" color="teal" variant="light">
                  Finalist ready
                </Badge>
              ) : (
                model.status === "active" && (
                  <Badge size="sm" color="yellow" variant="light">
                    Need Standard
                  </Badge>
                )
              )}
            </Group>
          </Stack>
        </Group>
        <Group gap={6}>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconFlask size={14} />}
            onClick={() =>
              navigate(`/benchmarks?tab=tier&model_id=${model.id}`)
            }
          >
            Tier run
          </Button>
          <Tooltip
            label={
              eligible
                ? "Open Finalist tab"
                : "Complete Standard tier first (or use Instrument on Finalist tab)"
            }
          >
            <Button
              size="xs"
              variant="light"
              color="violet"
              leftSection={<IconRocket size={14} />}
              onClick={() =>
                navigate(
                  `/benchmarks?tab=finalist&model_id=${model.id}${eligible ? "" : "&instrument=1"}`,
                )
              }
            >
              Finalist
            </Button>
          </Tooltip>
          <Button size="xs" variant="subtle" onClick={onToggle}>
            {expanded ? "Hide" : "Details"}
          </Button>
        </Group>
      </Group>

      {last && (
        <Text size="xs" c="dimmed" mt="sm">
          Last Finalist: pass {formatPassRate(last.n_passed, last.n_attempts)}
          {" · "}tools {formatMean(last.mean_tool_calls)}
          {" · "}turns {formatMean(last.mean_turns)}
          {" · "}T_eff {formatTeff(last.geo_mean_teff_vs_self)} (vs self)
        </Text>
      )}

      {expanded && (
        <Stack gap="md" mt="md">
          {detailLoading && <Loader size="sm" />}
          {detail && (
            <>
              <div>
                <Text size="sm" fw={600}>
                  From LiteLLM
                </Text>
                <Text size="xs" c="dimmed" mb={4}>
                  Published proxy metadata (refresh via Settings → Re-check).
                </Text>
                <Group gap="md">
                  <Text size="sm">
                    Vision: {detail.model.supports_vision ? "yes" : "no"}
                  </Text>
                  <Text size="sm">
                    Context:{" "}
                    {detail.model.context_window?.toLocaleString() ?? "—"}
                  </Text>
                  <Text size="sm">
                    Max out:{" "}
                    {detail.model.max_output_tokens?.toLocaleString() ?? "—"}
                  </Text>
                </Group>
                {detail.model.litellm_model_info && (
                  <Accordion mt="xs" variant="contained">
                    <Accordion.Item value="raw">
                      <Accordion.Control>Raw published fields</Accordion.Control>
                      <Accordion.Panel>
                        <Code block style={{ fontSize: 11 }}>
                          {JSON.stringify(detail.model.litellm_model_info, null, 2)}
                        </Code>
                      </Accordion.Panel>
                    </Accordion.Item>
                  </Accordion>
                )}
              </div>

              <div>
                <Text size="sm" fw={600}>
                  Tier progress
                </Text>
                <Group gap="xs" mt={4}>
                  <Badge
                    color={detail.tiers.smoke_completed ? "green" : "gray"}
                    variant="light"
                  >
                    Smoke {detail.tiers.smoke_completed ? "✓" : "—"}
                  </Badge>
                  <Badge
                    color={detail.tiers.standard_completed ? "green" : "gray"}
                    variant="light"
                  >
                    Standard {detail.tiers.standard_completed ? "✓" : "—"}
                  </Badge>
                  <Badge
                    color={detail.tiers.thorough_completed ? "green" : "gray"}
                    variant="light"
                  >
                    Thorough {detail.tiers.thorough_completed ? "✓" : "—"}
                  </Badge>
                </Group>
              </div>

              <div>
                <Text size="sm" fw={600}>
                  Notes
                </Text>
                <Text size="xs" c="dimmed" mb={4}>
                  Machine, HF base, VRAM, stability — freeform.
                </Text>
                <Textarea
                  minRows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.currentTarget.value)}
                  placeholder="e.g. Spark-A · Q4_K_M · ~18GB · stable overnight"
                />
                <Button
                  size="xs"
                  mt="xs"
                  loading={saveNotes.isPending}
                  onClick={() => saveNotes.mutate()}
                  disabled={notes === (detail.model.notes ?? "")}
                >
                  Save notes
                </Button>
              </div>

              <div>
                <Group justify="space-between" mb={4}>
                  <Text size="sm" fw={600}>
                    Benchmarks on this model
                  </Text>
                  <Tooltip label={TEFF_GLOSSARY} multiline w={280}>
                    <Text size="xs" c="dimmed" style={{ cursor: "help" }}>
                      T_eff glossary
                    </Text>
                  </Tooltip>
                </Group>
                <RunsTable runs={detail.recent_runs} />
              </div>

              <Group gap="xs">
                <Button
                  size="xs"
                  variant="subtle"
                  leftSection={<IconArchive size={14} />}
                  loading={archiveMutation.isPending}
                  onClick={() => archiveMutation.mutate()}
                >
                  {model.status === "archived" ? "Unarchive" : "Archive"}
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  leftSection={<IconTrash size={14} />}
                  loading={deleteMutation.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        `Delete ${model.name}? Run data for this model will be lost.`,
                      )
                    ) {
                      deleteMutation.mutate();
                    }
                  }}
                >
                  Remove
                </Button>
              </Group>
            </>
          )}
        </Stack>
      )}
    </Card>
  );
}

function RunsTable({ runs }: { runs: ModelRunSummary[] }) {
  const navigate = useNavigate();
  if (!runs.length) {
    return (
      <Text size="sm" c="dimmed">
        No runs yet.
      </Text>
    );
  }
  return (
    <Table striped highlightOnHover>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Run</Table.Th>
          <Table.Th>Kind</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>Score</Table.Th>
          <Table.Th />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {runs.map((r) => (
          <Table.Tr key={r.id}>
            <Table.Td>
              <Text size="sm">#{r.id}</Text>
              <Text size="xs" c="dimmed">
                {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
              </Text>
            </Table.Td>
            <Table.Td>
              <Text size="sm">
                {r.finalist
                  ? "Finalist"
                  : r.tier
                    ? r.tier.charAt(0).toUpperCase() + r.tier.slice(1)
                    : r.axis ?? "—"}
              </Text>
            </Table.Td>
            <Table.Td>
              <Badge size="sm" variant="light">
                {r.status}
              </Badge>
            </Table.Td>
            <Table.Td>
              {r.finalist ? (
                <Text size="xs">
                  pass {formatPassRate(r.n_passed, r.n_attempts)}
                  {" · "}T_eff {formatTeff(r.geo_mean_teff_vs_self)}
                  {" · "}tools {formatMean(r.mean_tool_calls)}
                </Text>
              ) : (
                <Text size="sm">
                  {r.score != null ? r.score.toFixed(1) : "—"}
                </Text>
              )}
            </Table.Td>
            <Table.Td>
              {r.finalist && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  leftSection={<IconEye size={14} />}
                  onClick={() =>
                    navigate(`/benchmarks?tab=finalist&inspect=${r.id}`)
                  }
                >
                  Inspect
                </Button>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function ModelsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [showUnreachable, setShowUnreachable] = useState(false);
  const focusId = searchParams.get("model_id");
  const [expandedId, setExpandedId] = useState<number | null>(
    focusId ? Number(focusId) : null,
  );

  const models = useQuery({ queryKey: ["models"], queryFn: api.models.list });
  const maps = useMemo(
    () => buildModelMaps(models.data ?? []),
    [models.data],
  );
  void maps;

  // Deep-link to a non-active model: reveal the matching status once.
  useEffect(() => {
    if (!focusId || !models.data) return;
    const m = models.data.find((x) => String(x.id) === focusId);
    if (!m) return;
    if (m.status === "archived") setShowArchived(true);
    else if (m.status === "unreachable" || (!m.is_active && m.status !== "active")) {
      setShowUnreachable(true);
    }
  }, [focusId, models.data]);

  const detail = useQuery({
    queryKey: ["model-detail", expandedId],
    queryFn: () => api.models.get(expandedId!),
    enabled: expandedId != null,
  });

  const filtered = useMemo(() => {
    const list = models.data ?? [];
    const needle = q.trim().toLowerCase();
    return list.filter((m) => {
      const active = m.status === "active" || m.is_active;
      const archived = m.status === "archived";
      const unreachable = !active && !archived;
      if (active) {
        // always include
      } else if (archived && !showArchived) {
        return false;
      } else if (unreachable && !showUnreachable) {
        return false;
      }
      if (!needle) return true;
      return (
        m.name.toLowerCase().includes(needle) ||
        (m.base_model ?? "").toLowerCase().includes(needle) ||
        (m.notes ?? "").toLowerCase().includes(needle)
      );
    });
  }, [models.data, q, showArchived, showUnreachable]);

  const counts = useMemo(() => {
    const list = models.data ?? [];
    let active = 0;
    let archived = 0;
    let unreachable = 0;
    for (const m of list) {
      if (m.status === "archived") archived += 1;
      else if (m.status === "active" || m.is_active) active += 1;
      else unreachable += 1;
    }
    return { active, archived, unreachable };
  }, [models.data]);

  return (
    <Stack>
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <div>
          <Title order={2}>Models</Title>
          <Text size="sm" c="dimmed">
            Local deployments under test — notes, LiteLLM metadata, and run history.
            Discover new IDs from Settings.
          </Text>
        </div>
        <Stack gap="xs" align="flex-end">
          <TextInput
            placeholder="Filter models…"
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
            w={260}
          />
          <Group gap="md">
            <Checkbox
              label={`Show unreachable (${counts.unreachable})`}
              checked={showUnreachable}
              onChange={(e) => setShowUnreachable(e.currentTarget.checked)}
            />
            <Checkbox
              label={`Show archived (${counts.archived})`}
              checked={showArchived}
              onChange={(e) => setShowArchived(e.currentTarget.checked)}
            />
          </Group>
        </Stack>
      </Group>

      {models.isLoading ? (
        <Loader />
      ) : filtered.length === 0 ? (
        <Text c="dimmed">
          {counts.active === 0
            ? "No reachable models. Open Settings to Discover / Re-check, or show unreachable."
            : "No models match this filter."}
        </Text>
      ) : (
        <Stack gap="sm">
          {filtered.map((m: ModelRecord) => (
            <ModelCard
              key={m.id}
              model={
                detail.data?.model.id === m.id ? detail.data.model : m
              }
              detail={detail.data?.model.id === m.id ? detail.data : undefined}
              detailLoading={detail.isFetching && expandedId === m.id}
              expanded={expandedId === m.id}
              onToggle={() => {
                const next = expandedId === m.id ? null : m.id;
                setExpandedId(next);
                if (next != null) {
                  setSearchParams({ model_id: String(next) });
                } else {
                  setSearchParams({});
                }
              }}
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
