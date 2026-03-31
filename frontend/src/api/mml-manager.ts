import api from "./index";

// ── Interfaces ──────────────────────────────────────────────────────────────

export interface NeVersion {
  id: number;
  vendor: string;
  ne_type: string;
  version: string;
  created_at: string;
}

export interface MmlFile {
  id: number;
  filename: string;
  ne_version_id: number;
  file_size: number;
  created_at: string;
  updated_at: string;
  vendor: string;
  ne_type: string;
  ne_version: string;
}

export interface MmlStats {
  file_count: number;
  ne_version_count: number;
}

// ── NE Versions ─────────────────────────────────────────────────────────────

export async function fetchNeVersions(): Promise<NeVersion[]> {
  const { data } = await api.get<NeVersion[]>("/plugins/mml_manager/ne-versions");
  return data;
}

export async function createNeVersion(payload: {
  ne_type: string;
  version: string;
  vendor?: string;
}): Promise<NeVersion> {
  const { data } = await api.post<NeVersion>("/plugins/mml_manager/ne-versions", payload);
  return data;
}

export async function deleteNeVersion(id: number): Promise<void> {
  await api.delete(`/plugins/mml_manager/ne-versions/${id}`);
}

// ── Files ───────────────────────────────────────────────────────────────────

export async function fetchFiles(neVersionId?: number): Promise<MmlFile[]> {
  const params: Record<string, unknown> = {};
  if (neVersionId !== undefined) {
    params.ne_version_id = neVersionId;
  }
  const { data } = await api.get<MmlFile[]>("/plugins/mml_manager/files", { params });
  return data;
}

export async function getFileContent(id: number): Promise<string> {
  const { data } = await api.get<{ content: string }>(`/plugins/mml_manager/files/${id}/content`);
  return data.content;
}

export async function updateFileContent(id: number, content: string): Promise<void> {
  await api.put(`/plugins/mml_manager/files/${id}/content`, { content });
}

export async function deleteFile(id: number): Promise<void> {
  await api.delete(`/plugins/mml_manager/files/${id}`);
}

export async function uploadFiles(
  neVersionId: number,
  files: File[],
): Promise<{ count: number; uploaded: MmlFile[] }> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  const { data } = await api.post<{ count: number; uploaded: MmlFile[] }>(
    `/plugins/mml_manager/upload`,
    formData,
    { params: { ne_version_id: neVersionId } },
  );
  return data;
}

export function getFileDownloadUrl(id: number): string {
  return `http://localhost:8000/api/plugins/mml_manager/files/${id}/download`;
}

// ── Stats ───────────────────────────────────────────────────────────────────

export async function fetchMmlStats(): Promise<MmlStats> {
  const { data } = await api.get<MmlStats>("/plugins/mml_manager/stats");
  return data;
}
