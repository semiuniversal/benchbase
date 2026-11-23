import {
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronRight, IconRefresh } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, type DashboardHeadline } from "../../api/client";

const TYPE_COLOR: Record<string, string> = {
  "benchmark.running": "blue",
  "benchmark.queued": "gray",
  "benchmark.interrupted": "orange",
  "benchmark.completed": "green",
};

function destinationPath(dest: DashboardHeadline["destination"]): string {
  const q = new URLSearchParams();
  if (dest.query) {
    for (const [k, v] of Object.entries(dest.query)) {
      q.set(k, v);
    }
  }
  const path = dest.routeName === "benchmarks" ? "/benchmarks" : `/${dest.routeName}`;
  const qs = q.toString();
  return qs ? `${path}?${qs}` : path;
}

function HeadlineRow({ item }: { item: DashboardHeadline }) {
  const navigate = useNavigate();
  const color = TYPE_COLOR[item.type] ?? "gray";
  const to = destinationPath(item.destination);
  return (
    <UnstyledButton
      component="a"
      href={to}
      onClick={(e) => {
        e.preventDefault();
        navigate(to);
      }}
      aria-label={`${item.type_label}: ${item.title}. ${item.subtitle ?? ""}`}
      style={{ display: "block", width: "100%" }}
    >
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" wrap="nowrap" align="flex-start" gap="sm">
          <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
            <Group gap="xs" wrap="nowrap">
              <Badge size="sm" variant="light" color={color} style={{ flexShrink: 0 }}>
                {item.type_label}
              </Badge>
              <Text fw={600} size="sm" truncate>
                {item.title}
              </Text>
            </Group>
            {item.subtitle ? (
              <Text size="xs" c="dimmed" lineClamp={2}>
                {item.subtitle}
              </Text>
            ) : null}
          </Stack>
          <IconChevronRight size={18} style={{ flexShrink: 0, opacity: 0.6 }} />
        </Group>
      </Paper>
    </UnstyledButton>
  );
}

export function DashboardPage() {
  const headlines = useQuery({
    queryKey: ["dashboard-headlines"],
    queryFn: api.dashboard.headlines,
    refetchInterval: 20_000,
  });

  const items = headlines.data?.headlines ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Stack gap={4}>
          <Title order={2}>Dashboard</Title>
          <Text size="sm" c="dimmed">
            Actionable benchmark activity — each item opens the exact run or tier set.
          </Text>
        </Stack>
        <Button
          variant="light"
          leftSection={<IconRefresh size={16} />}
          onClick={() => headlines.refetch()}
          loading={headlines.isFetching}
        >
          Refresh
        </Button>
      </Group>

      {headlines.isLoading ? (
        <Loader />
      ) : items.length === 0 ? (
        <Paper withBorder p="xl" radius="md">
          <Stack gap="sm" align="flex-start">
            <Text fw={600}>No recent benchmark activity</Text>
            <Text size="sm" c="dimmed">
              Start a tier benchmark or open the log for a past run from Benchmarks.
            </Text>
            <Group>
              <Button component={Link} to="/benchmarks">
                Go to Benchmarks
              </Button>
              <Anchor component={Link} to="/models" size="sm">
                Manage models
              </Anchor>
            </Group>
          </Stack>
        </Paper>
      ) : (
        <Stack gap="xs">
          {items.map((item) => (
            <HeadlineRow key={item.id} item={item} />
          ))}
          <Anchor component={Link} to="/benchmarks" size="sm" mt="xs">
            View all activity in Benchmarks
          </Anchor>
        </Stack>
      )}

      {headlines.data?.generated_at ? (
        <Text size="xs" c="dimmed">
          Updated {new Date(headlines.data.generated_at).toLocaleString()}
        </Text>
      ) : null}
    </Stack>
  );
}