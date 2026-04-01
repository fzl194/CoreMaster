import api from "./index";

// ── Interfaces ──────────────────────────────────────────────────────────────

export interface NeVersion {
  id: number;
  vendor: string;
  ne_type: string;
  version: string;
  created_at: string;
}

export interface FileEntry {
  id: number;
  parent_id: number | null;
  name: string;
  type: "folder" | "file";
  ne_version_id: number | null;
  file_size: number;
  description: string | null;
  created_at: string;
  updated_at: string;
  vendor: string | null;
  ne_type: string | null;
  version: string | null;
}

export interface PathSegment {
  id: number;
  name: string;
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

// ── Entries (Directory Browsing) ────────────────────────────────────────────

export async function fetchEntries(parentId?: number | null): Promise<FileEntry[]> {
  const params: Record<string, unknown> = {};
  if (parentId !== undefined && parentId !== null) {
    params.parent_id = parentId;
  }
  const { data } = await api.get<FileEntry[]>("/plugins/mml_manager/entries", { params });
  return data;
}

export async function createFolder(name: string, parentId?: number | null): Promise<FileEntry> {
  const payload: Record<string, unknown> = { name, type: "folder" };
  if (parentId !== undefined && parentId !== null) {
    payload.parent_id = parentId;
  }
  const { data } = await api.post<FileEntry>("/plugins/mml_manager/entries", payload);
  return data;
}

export async function deleteEntry(entryId: number): Promise<void> {
  await api.delete(`/plugins/mml_manager/entries/${entryId}`);
}

// ── Files ───────────────────────────────────────────────────────────────────

export async function getFileContent(id: number): Promise<string> {
  const { data } = await api.get<{ content: string }>(`/plugins/mml_manager/files/${id}/content`);
  return data.content;
}

export async function updateFileContent(id: number, content: string): Promise<void> {
  await api.put(`/plugins/mml_manager/files/${id}/content`, { content });
}

export function getFileDownloadUrl(id: number): string {
  return `http://localhost:8000/api/plugins/mml_manager/files/${id}/download`;
}

export interface UploadResult {
  uploaded: FileEntry[];
  failed: { filename: string; reason: string }[];
}

export async function uploadFiles(
  parentId: number | null | undefined,
  files: { file: File; neVersionId: number }[],
): Promise<UploadResult> {
  const formData = new FormData();
  const items: Record<string, { ne_version_id: number }> = {};
  for (const item of files) {
    formData.append("files", item.file);
    items[item.file.name] = { ne_version_id: item.neVersionId };
  }
  formData.append("metadata", JSON.stringify({ parent_id: parentId ?? null, items }));
  const { data } = await api.post<UploadResult>("/plugins/mml_manager/upload", formData);
  return data;
}

// ── Stats ───────────────────────────────────────────────────────────────────

export async function fetchMmlStats(): Promise<MmlStats> {
  const { data } = await api.get<MmlStats>("/plugins/mml_manager/stats");
  return data;
}
