import api from "./index";

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
  per_file: {
    file_entry_id: number;
    hit_count: number;
    hit_values: string[];
    sample_scripts: { def_line: number; ref_line: number }[];
  }[];
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
  llm_assessment_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileMiningInfo {
  file_entry_id: number;
  file_name: string;
  file_size: number;
  ne_version_id: number;
  mined: number;
  algorithm_version: string;
  command_count: number;
  mined_at: string | null;
  mining_status: "unmined" | "changed" | "queued" | "running" | "completed" | "failed";
}

export interface GraphEdge {
  id: number;
  ne_version_id: number;
  ref_command: string;
  ref_param: string;
  def_command: string;
  def_param: string;
  status: string;
  source: string;
  confidence: number;
  evidence: CandidateEvidence;
  confirmed_by: string | null;
  created_at: string;
  updated_at: string;
}

// ── API Functions ───────────────────────────────────────────────────────────

export async function startMining(
  fileIds: number[]
): Promise<{ job_id: number }> {
  const { data } = await api.post("/plugins/graph_mining/mining/start", {
    file_ids: fileIds,
  });
  return data;
}

export async function fetchJob(jobId: number): Promise<JobInfo> {
  const { data } = await api.get<JobInfo>(
    `/plugins/graph_mining/jobs/${jobId}`
  );
  return data;
}

export async function fetchFiles(
  neVersionId: number
): Promise<FileMiningInfo[]> {
  const { data } = await api.get<FileMiningInfo[]>(
    "/plugins/graph_mining/files",
    { params: { ne_version_id: neVersionId } }
  );
  return data;
}

export async function fetchCandidates(params?: {
  ne_version_id?: number;
  status?: string;
}): Promise<Candidate[]> {
  const { data } = await api.get<Candidate[]>(
    "/plugins/graph_mining/candidates",
    { params }
  );
  return data;
}

export async function acceptCandidate(
  id: number,
  reviewer: string
): Promise<{ ok: boolean; graph_edge_id: number }> {
  const { data } = await api.post(
    `/plugins/graph_mining/candidates/${id}/accept`,
    { reviewer }
  );
  return data;
}

export async function rejectCandidate(
  id: number,
  reviewer: string
): Promise<{ ok: boolean }> {
  const { data } = await api.post(
    `/plugins/graph_mining/candidates/${id}/reject`,
    { reviewer }
  );
  return data;
}

export async function markNonGraph(
  id: number,
  reason: string,
  reviewer: string
): Promise<{ ok: boolean }> {
  const { data } = await api.post(
    `/plugins/graph_mining/candidates/${id}/mark-non-graph`,
    { reason, reviewer }
  );
  return data;
}

export async function revertCandidate(
  id: number,
  reviewer: string
): Promise<{ ok: boolean }> {
  const { data } = await api.post(
    `/plugins/graph_mining/candidates/${id}/revert`,
    { reviewer }
  );
  return data;
}

export async function fetchGraphEdges(params?: {
  ne_version_id?: number;
}): Promise<GraphEdge[]> {
  const { data } = await api.get<GraphEdge[]>(
    "/plugins/graph_mining/graph-edges",
    { params }
  );
  return data;
}
