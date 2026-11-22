import type { RunRecord } from "../../api/client";

export interface RunGroupRow {
  key: string;
  run_group_id: string | null;
  model_id: number;
  tier: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  members: RunRecord[];
  current: RunRecord | null;
}