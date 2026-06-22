import { Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

interface RunTimingLineProps {
  runId: number;
  active: boolean;
}

export function RunTimingLine({ runId, active }: RunTimingLineProps) {
  const timing = useQuery({
    queryKey: ["run-timing", runId],
    queryFn: () => api.benchmarks.runTiming(runId),
    enabled: active,
    refetchInterval: active ? 2000 : false,
  });

  if (!active || !timing.data) return null;

  const t = timing.data;
  const parts: string[] = [];

  if (t.elapsed_seconds > 0) {
    parts.push(`Elapsed: ${t.elapsed_label}`);
  }
  if (t.estimate_label && t.estimate_label !== "—") {
    parts.push(`Est. total: ${t.estimate_label}`);
  }
  if (t.progress_label) {
    parts.push(t.progress_label);
  }
  if (t.eta_label) {
    parts.push(t.eta_label);
  }

  if (parts.length === 0) return null;

  return (
    <Text size="xs" c="dimmed">
      {parts.join(" · ")}
    </Text>
  );
}
