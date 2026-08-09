import {
  AppShell as MantineAppShell,
  Badge,
  Burger,
  Button,
  Group,
  NavLink,
  Text,
  Title,
  ActionIcon,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconDashboard,
  IconSwords,
  IconSettings,
  IconSun,
  IconMoon,
  IconScale,
  IconFlask,
  IconTerminal,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../../api/client";

const NAV_ITEMS = [
  { label: "Dashboard", icon: IconDashboard, path: "/" },
  { label: "Benchmarks", icon: IconFlask, path: "/benchmarks" },
  { label: "Arena", icon: IconSwords, path: "/arena" },
  { label: "Compare", icon: IconScale, path: "/compare" },
  { label: "Settings", icon: IconSettings, path: "/settings" },
];

function tierWord(tier?: string) {
  if (tier === "smoke") return "Smoke";
  if (tier === "thorough") return "Thorough";
  if (tier === "standard") return "Standard";
  return tier ?? "tier";
}

export function AppShell() {
  const [opened, { toggle }] = useDisclosure();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [completeFlash, setCompleteFlash] = useState(false);
  const wasActive = useRef(false);

  const batchStatus = useQuery({
    queryKey: ["batch-status"],
    queryFn: api.benchmarks.batchStatus,
    refetchInterval: (q) => {
      const d = q.state.data;
      if (d?.status === "running" || (d?.pending_count ?? 0) > 0) return 2000;
      return 10000;
    },
  });

  const active =
    batchStatus.data?.status === "running" ||
    (batchStatus.data?.pending_count ?? 0) > 0 ||
    (batchStatus.data?.current_runs?.length ?? 0) > 0;

  useEffect(() => {
    if (wasActive.current && !active) {
      setCompleteFlash(true);
      const t = window.setTimeout(() => setCompleteFlash(false), 6000);
      return () => window.clearTimeout(t);
    }
    wasActive.current = active;
  }, [active]);

  const batch = batchStatus.data;
  const bannerText = active
    ? `Currently running: ${batch?.model_name ?? "model"} ${tierWord(batch?.tier)} (${batch?.axes_done ?? batch?.completed ?? 0}/${batch?.axes_total ?? batch?.total ?? "?"})`
    : completeFlash
      ? "All tests complete."
      : null;

  return (
    <MantineAppShell
      header={{ height: bannerText ? 96 : 56 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <MantineAppShell.Header>
        <Group h={56} px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={3}>BenchBase</Title>
          </Group>
          <ActionIcon
            variant="default"
            size="lg"
            onClick={() => toggleColorScheme()}
            aria-label="Toggle color scheme"
          >
            {colorScheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
          </ActionIcon>
        </Group>
        {bannerText && (
          <Group
            h={40}
            px="md"
            justify="space-between"
            style={{
              borderTop: "1px solid var(--mantine-color-default-border)",
              background: active
                ? "var(--mantine-color-blue-light)"
                : "var(--mantine-color-green-light)",
            }}
          >
            <Group gap="sm">
              {active && <Badge size="sm" variant="filled">live</Badge>}
              <Text size="sm">{bannerText}</Text>
              {active && batch?.current_label && (
                <Text size="xs" c="dimmed">{batch.current_label}</Text>
              )}
            </Group>
            {active && (
              <Button
                size="compact-sm"
                variant="light"
                leftSection={<IconTerminal size={14} />}
                onClick={() => navigate("/benchmarks?monitor=1")}
              >
                Monitor
              </Button>
            )}
          </Group>
        )}
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="xs">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            label={item.label}
            leftSection={<item.icon size={18} />}
            active={location.pathname === item.path}
            onClick={() => {
              navigate(item.path);
              toggle();
            }}
          />
        ))}
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
