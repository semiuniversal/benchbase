import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { useEffect, useRef } from "react";

export type ConfirmDangerProps = {
  opened: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  confirmColor?: string;
};

/** Destructive confirm: Enter confirms, Escape cancels. */
export function ConfirmDangerDialog({
  opened,
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  loading = false,
  confirmColor = "red",
}: ConfirmDangerProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!opened) return;
    const id = window.setTimeout(() => confirmRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [opened]);

  return (
    <Modal
      opened={opened}
      onClose={onCancel}
      title={title}
      centered
      closeOnEscape
      closeOnClickOutside={false}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !loading) {
          e.preventDefault();
          onConfirm();
        }
      }}
    >
      <Stack gap="md">
        <Text size="sm">{body}</Text>
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button
            ref={confirmRef}
            color={confirmColor}
            loading={loading}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
