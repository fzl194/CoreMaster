import api from "./index";

// ── Interfaces ──────────────────────────────────────────────────────────────

export interface CommandInstance {
  id: number;
  file_entry_id: number;
  ne_version_id: number;
  command_index: number;
  operation: string;
  name: string;
  params: { name: string; value: string | null }[];
  line_number: number;
}

export interface CandidateScores {
  support: number;
  distinctiveness: number;
  order_consistency: number;
  name_relevance: number;
}

export interface CandidateEvidence {
  hit_count: number;
  hit_file_count: number;
  total_mined_files: number;
  hit_values: string[];
  sample_scripts: { file_entry_id: number; def_line: number; ref_line: number }[];
  per_file: { file_entry_id: number; hit_count: number; hit_values: string[]; sample_scripts: { def_line: number; ref_line: number }[] }[];
}

export interface Candidate {
  id: number;
  ne_version_id: number;
  ref_command: string;
  ref_param: string;
  def_command: string;
  def_param: string;
  status: string;
  confidence: number;
  scores: CandidateScores;
  evidence: CandidateEvidence;
  graph_edge_id: number | null;
  review_route: string | null;
  non_graph_reason: string | null;
  non_graph_reviewer: string | null;
  active_algorithm_version: string;
  created_at: string;
  updated_at: string;
}

export interface FileMiningStatus {
  file_entry_id: number;
  file_name: string;
  mined: boolean | number;
  command_count: number;
  algorithm_version: string;
}

export interface MineResult {
  mined_files: number;
  total_candidates: number;
  candidates: number[];
}

// ── API Functions ───────────────────────────────────────────────────────────

export async function extractCommands(
  fileId: number
): Promise<{ instances: CommandInstance[]; total: number; report: Record<string, number> }> {
  const { data } = await api.post(
    `/plugins/mml_manager/scripts/${fileId}/extract-commands`
  );
  return data;
}

export async function fetchCandidates(params?: {
  ne_version_id?: number;
  status?: string;
}): Promise<Candidate[]> {
  const { data } = await api.get<Candidate[]>(
    "/plugins/mml_manager/candidates",
    { params }
  );
  return data;
}

export async function acceptCandidate(
  id: number,
  reviewer: string
): Promise<{ ok: boolean; graph_edge_id: number }> {
  const { data } = await api.post<{
    ok: boolean;
    graph_edge_id: number;
  }>(`/plugins/mml_manager/candidates/${id}/accept`, { reviewer });
  return data;
}

export async function rejectCandidate(
  id: number,
  reviewer: string
): Promise<{ ok: boolean }> {
  const { data } = await api.post<{ ok: boolean }>(
    `/plugins/mml_manager/candidates/${id}/reject`,
    { reviewer }
  );
  return data;
}

export async function mineFiles(fileIds: number[]): Promise<MineResult> {
  const { data } = await api.post("/plugins/mml_manager/files/mine", { file_ids: fileIds });
  return data;
}

export async function reMineFile(fileId: number): Promise<MineResult> {
  const { data } = await api.post(`/plugins/mml_manager/files/${fileId}/re-mine`);
  return data;
}

export async function fetchMiningStatus(neVersionId: number): Promise<FileMiningStatus[]> {
  const { data } = await api.get<FileMiningStatus[]>("/plugins/mml_manager/files/mining-status", {
    params: { ne_version_id: neVersionId },
  });
  return data;
}

export async function markNonGraph(id: number, reason: string, reviewer: string): Promise<{ ok: boolean }> {
  const { data } = await api.post(`/plugins/mml_manager/candidates/${id}/mark-non-graph`, { reason, reviewer });
  return data;
}

export async function revertCandidate(id: number, reviewer: string): Promise<{ ok: boolean }> {
  const { data } = await api.post(`/plugins/mml_manager/candidates/${id}/revert`, { reviewer });
  return data;
}
