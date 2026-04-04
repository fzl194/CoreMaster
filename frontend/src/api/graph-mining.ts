import api from "./index";
import { fetchNeVersions } from "./mml-manager";
import type { NeVersion } from "./mml-manager";

// ── Interfaces ──────────────────────────────────────────────────────────────

export interface JobInfo {
  id: number;
  type: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  params_json: string;
  progress_current: number;
  progress_total: number;
  result_json: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

