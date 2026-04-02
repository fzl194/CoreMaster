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
  total_scripts: number;
  hit_values: string[];
  sample_scripts: { def_line: number; ref_line: number }[];
  counter_examples: { file_entry_id: number; reason: string }[];
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
  created_at: string;
  updated_at: string;
}

// ── API Functions ───────────────────────────────────────────────────────────

export async function batchExtractCommands(
  neVersionId: number
): Promise<{ extracted: { file_id: number; file_name: string; instance_count: number }[]; total_files: number; total_instances: number }> {
  const { data } = await api.post(
    `/plugins/mml_manager/versions/${neVersionId}/batch-extract`
  );
  return data;
}

export async function extractCommands(
  fileId: number
): Promise<{ instances: CommandInstance[]; total: number; report: Record<string, number> }> {
  const { data } = await api.post(
    `/plugins/mml_manager/scripts/${fileId}/extract-commands`
  );
  return data;
}

export async function generateCandidates(
  neVersionId: number
): Promise<{ candidates: Candidate[]; total: number }> {
  const { data } = await api.post<{
    candidates: Candidate[];
    total: number;
  }>("/plugins/mml_manager/candidates/generate", {
    ne_version_id: neVersionId,
  });
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
