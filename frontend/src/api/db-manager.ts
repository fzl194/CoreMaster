import api from "./index";

// ── Interfaces ──────────────────────────────────────────────────────────────

export interface TableInfo {
  name: string;
  row_count: number;
}

export interface ColumnInfo {
  cid: number;
  name: string;
  type: string;
  notnull: number;
  dflt_value: string | null;
  pk: number;
}

export interface RowsResponse {
  rows: Record<string, any>[];
  total: number;
}

// ── API ─────────────────────────────────────────────────────────────────────

export async function fetchTables(): Promise<TableInfo[]> {
  const { data } = await api.get<TableInfo[]>("/plugins/db_manager/tables");
  return data;
}

export async function fetchTableSchema(tableName: string): Promise<ColumnInfo[]> {
  const { data } = await api.get<ColumnInfo[]>(`/plugins/db_manager/tables/${tableName}/schema`);
  return data;
}

export async function fetchTableRows(
  tableName: string,
  limit = 50,
  offset = 0,
): Promise<RowsResponse> {
  const { data } = await api.get<RowsResponse>(`/plugins/db_manager/tables/${tableName}/rows`, {
    params: { limit, offset },
  });
  return data;
}

export async function insertRow(
  tableName: string,
  fields: Record<string, any>,
): Promise<Record<string, any>> {
  const { data } = await api.post(`/plugins/db_manager/tables/${tableName}/rows`, { fields });
  return data;
}

export async function updateRow(
  tableName: string,
  rowId: number,
  fields: Record<string, any>,
): Promise<Record<string, any>> {
  const { data } = await api.put(`/plugins/db_manager/tables/${tableName}/rows/${rowId}`, {
    fields,
  });
  return data;
}

export async function deleteRow(tableName: string, rowId: number): Promise<void> {
  await api.delete(`/plugins/db_manager/tables/${tableName}/rows/${rowId}`);
}
