import {
  Badge,
  Box,
  ColorSwatch,
  Group,
  Popover,
  Text,
  UnstyledButton,
  type MantineColor,
} from "@mantine/core";
import type { ReactNode } from "react";
import type { ModelRecord } from "../../api/client";

export const MODEL_COLOR_PALETTE = [
  "cyan",
  "orange",
  "grape",
  "lime",
  "pink",
  "teal",
  "yellow",
  "indigo",
  "red",
  "violet",
  "blue",
  "green",
] as const;

export type ModelColorName = (typeof MODEL_COLOR_PALETTE)[number];

export function asModelColor(color: string | null | undefined): MantineColor {
  if (color && MODEL_COLOR_PALETTE.includes(color as ModelColorName)) {
    return color as MantineColor;
  }
  return "blue";
}

export function buildModelMaps(models: ModelRecord[]) {
  const byId: Record<number, ModelRecord> = {};
  const byName: Record<string, ModelRecord> = {};
  for (const m of models) {
    byId[m.id] = m;
    byName[m.name] = m;
  }
  return { byId, byName };
}

export function modelColor(
  maps: { byId: Record<number, ModelRecord>; byName: Record<string, ModelRecord> },
  ref: { id?: number; name?: string },
): MantineColor {
  if (ref.id != null && maps.byId[ref.id]) {
    return asModelColor(maps.byId[ref.id].color);
  }
  if (ref.name && maps.byName[ref.name]) {
    return asModelColor(maps.byName[ref.name].color);
  }
  return "blue";
}

export function modelColorCss(color: MantineColor, shade = 6) {
  return `var(--mantine-color-${color}-${shade})`;
}

export function ModelDot({
  color,
  size = 8,
}: {
  color: MantineColor;
  size?: number;
}) {
  return (
    <Box
      style={{
        width: size,
        height: size,
        borderRadius: 999,
        background: modelColorCss(color),
        flexShrink: 0,
      }}
    />
  );
}

export function ModelTag({
  name,
  color,
  size = "sm",
  fw = 500,
  truncate = false,
}: {
  name: string;
  color: MantineColor;
  size?: "xs" | "sm" | "md";
  fw?: number;
  truncate?: boolean;
}) {
  return (
    <Badge variant="light" color={color} size={size === "md" ? "md" : "sm"}>
      <Text size={size} fw={fw} truncate={truncate} m={0}>
        {name}
      </Text>
    </Badge>
  );
}

export function ModelHeading({
  name,
  color,
  size = "sm",
}: {
  name: string;
  color: MantineColor;
  size?: "xs" | "sm" | "md";
}) {
  return (
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
      <ModelDot color={color} />
      <Text size={size} fw={700} c={color} truncate title={name}>
        {name}
      </Text>
    </Group>
  );
}

export function ModelColumnAccent({
  color,
  children,
}: {
  color: MantineColor;
  children: ReactNode;
}) {
  return (
    <Box
      style={{
        borderTop: `3px solid ${modelColorCss(color)}`,
        borderRadius: "var(--mantine-radius-sm)",
      }}
    >
      {children}
    </Box>
  );
}

export function ModelColorPicker({
  color,
  onChange,
  disabled = false,
}: {
  color: MantineColor;
  onChange: (color: ModelColorName) => void;
  disabled?: boolean;
}) {
  return (
    <Popover position="bottom-start" withArrow shadow="md">
      <Popover.Target>
        <UnstyledButton
          disabled={disabled}
          aria-label="Choose model color"
          style={{ borderRadius: 999, lineHeight: 0 }}
        >
          <ColorSwatch color={modelColorCss(color)} size={28} />
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown p="sm">
        <Text size="xs" c="dimmed" mb="xs">
          Model color
        </Text>
        <Group gap={6}>
          {MODEL_COLOR_PALETTE.map((swatch) => (
            <ColorSwatch
              key={swatch}
              component="button"
              type="button"
              color={modelColorCss(swatch)}
              aria-label={swatch}
              onClick={() => onChange(swatch)}
              style={
                swatch === color
                  ? { outline: "2px solid var(--mantine-color-default-color)", outlineOffset: 2 }
                  : undefined
              }
            />
          ))}
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
}
