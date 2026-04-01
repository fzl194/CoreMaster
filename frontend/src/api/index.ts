import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8000/api",
});

export interface PluginInfo {
  name: string;
  description: string;
  menu_title: string;
  icon: string;
  path: string;
}

export interface PluginsResponse {
  plugins: PluginInfo[];
}

export async function fetchPlugins(): Promise<PluginsResponse> {
  const { data } = await api.get<PluginsResponse>("/plugins");
  return data;
}

export default api;
