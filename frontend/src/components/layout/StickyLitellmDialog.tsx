import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPower } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";

export function StickyLitellmDialog() {
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState(false);
  const status = useQuery({
    queryKey: ["litellm-sticky"],
    queryFn: api.settings.stickyStatus,
    refetchInterval: 15000,
    retry: false,
  });

  const sticky = Boolean(status.data?.sticky_min_tokens);
  const busy = Boolean(status.data?.benchmark_active);

  useEffect(() => {
    if (!sticky) setDismissed(false);
  }, [sticky]);

  const restart = useMutation({
    mutationFn: () => api.settings.restartLitellm(),
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey: ["litellm-sticky"] });
      if (data.sticky_min_tokens) {
        notifications.show({
          title: "LiteLLM restarted — still sticky",
          message: `Method: ${data.method}. The probe still sees forced-length settings.`,
          color: "yellow",
          autoClose: 12000,
        });
        return;
      }
      setDismissed(false);
      notifications.show({
        title: "LiteLLM restarted",
        message: `Method: ${data.method}. Sticky token settings are cleared.`,
        color: "green",
        autoClose: 8000,
      });
    },
    onError: (err: Error) => {
      notifications.show({
        title: "LiteLLM restart failed",
        message: err.message,
        color: "red",
        autoClose: 12000,
      });
    },
  });

  return (
    <Modal
      opened={sticky && !busy && !dismissed}
      onClose={() => setDismissed(true)}
      title="LiteLLM is holding sticky token settings"
      centered
    >
      <Stack>
        <Text size="sm">
          A Speed run left <Text span fw={600}>min_tokens</Text> or{" "}
          <Text span fw={600}>ignore_eos</Text> on the proxy
          {status.data?.model ? ` (${status.data.model})` : ""}. Quality answers
          will run on until that forced length, so scores from here will not be trustworthy.
        </Text>
        {status.data?.detail && (
          <Text size="xs" c="dimmed">
            {status.data.detail}
          </Text>
        )}
        <Text size="sm">
          Restart LiteLLM to clear it. The proxy drops for a few seconds while it comes back.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDismissed(true)}>
            Not now
          </Button>
          <Button
            color="orange"
            leftSection={<IconPower size={16} />}
            loading={restart.isPending}
            onClick={() => restart.mutate()}
          >
            Restart LiteLLM
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
