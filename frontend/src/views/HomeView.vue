<template>
  <div class="home-container">
    <!-- Hero Section -->
    <div class="hero-section">
      <div class="hero-content">
        <div class="hero-badge">
          <span class="badge-dot"></span>
          <span>v0.1.0</span>
        </div>
        <h1 class="hero-title">CoreMaster</h1>
        <p class="hero-desc">核心网 MML 配置管理与数据挖掘平台</p>
      </div>
      <div class="hero-decoration">
        <div class="code-block">
          <div class="code-line">
            <span class="code-keyword">ADD</span>
            <span class="code-cmd">APN</span><span class="code-colon">:</span>
          </div>
          <div class="code-line code-indent">
            <span class="code-param">APN</span><span class="code-eq">=</span><span class="code-val">"cmnet"</span><span class="code-comma">,</span>
          </div>
          <div class="code-line code-indent">
            <span class="code-param">BINDVPN</span><span class="code-eq">=</span><span class="code-val">ENABLE</span><span class="code-comma">,</span>
          </div>
          <div class="code-line code-indent">
            <span class="code-param">VRFNAME</span><span class="code-eq">=</span><span class="code-val">"vpn_5gc"</span><span class="code-semi">;</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon" style="background: rgba(37, 99, 235, 0.15); color: #3B82F6;">
          <n-icon size="20"><terminal-outline /></n-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ pluginCount }}</div>
          <div class="stat-label">已加载插件</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: rgba(249, 115, 22, 0.15); color: #F97316;">
          <n-icon size="20"><server-outline /></n-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ serviceCount }}</div>
          <div class="stat-label">公共服务</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: rgba(34, 197, 94, 0.15); color: #22C55E;">
          <n-icon size="20"><checkmark-circle-outline /></n-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ apiVersion }}</div>
          <div class="stat-label">API 版本</div>
        </div>
      </div>
    </div>

    <!-- Plugins Grid -->
    <div class="section-header">
      <h2 class="section-title">功能模块</h2>
      <span class="section-subtitle">从左侧菜单进入各模块</span>
    </div>
    <div class="plugin-grid">
      <div
        v-for="plugin in plugins"
        :key="plugin.name"
        class="plugin-card"
        @click="navigateTo(plugin)"
      >
        <div class="plugin-card-icon">
          <n-icon size="24"><terminal-outline /></n-icon>
        </div>
        <div class="plugin-card-body">
          <div class="plugin-card-name">{{ plugin.name }}</div>
          <div class="plugin-card-desc">{{ plugin.description }}</div>
        </div>
        <div class="plugin-card-arrow">
          <n-icon size="16"><arrow-forward-outline /></n-icon>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="plugins.length === 0 && !loading" class="empty-state">
      <n-icon size="48" color="#334155"><cloud-offline-outline /></n-icon>
      <p class="empty-title">暂无插件</p>
      <p class="empty-desc">请确认后端服务已启动</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { NIcon } from "naive-ui";
import {
  TerminalOutline,
  ServerOutline,
  CheckmarkCircleOutline,
  ArrowForwardOutline,
  CloudOfflineOutline,
} from "@vicons/ionicons5";
import { fetchPlugins, type PluginInfo } from "../api";

const router = useRouter();
const plugins = ref<PluginInfo[]>([]);
const pluginCount = ref(0);
const serviceCount = ref(3);
const apiVersion = ref("v0.1");
const loading = ref(true);

function navigateTo(plugin: PluginInfo) {
  // For now navigate by plugin name convention
  router.push(`/plugins/${plugin.name.replace(/_/g, "-")}`);
}

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    plugins.value = res.plugins;
    pluginCount.value = res.plugins.length;
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.home-container {
  max-width: 960px;
  margin: 0 auto;
}

/* Hero */
.hero-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 40px;
  padding: 32px 40px;
  background: linear-gradient(135deg, #1a1d27 0%, #16181f 100%);
  border: 1px solid #1e2028;
  border-radius: 16px;
  margin-bottom: 24px;
}
.hero-content {
  flex: 1;
}
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: rgba(37, 99, 235, 0.12);
  border: 1px solid rgba(37, 99, 235, 0.25);
  border-radius: 20px;
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  color: #60a5fa;
  margin-bottom: 16px;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
}
.hero-title {
  font-family: 'Fira Code', monospace;
  font-size: 32px;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 8px;
  letter-spacing: -1px;
}
.hero-desc {
  font-size: 15px;
  color: #64748b;
  line-height: 1.6;
}

/* Code decoration */
.hero-decoration {
  flex-shrink: 0;
}
.code-block {
  font-family: 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.8;
  padding: 16px 20px;
  background: #0c0d11;
  border: 1px solid #1e2028;
  border-radius: 10px;
  min-width: 280px;
}
.code-keyword { color: #f97316; font-weight: 600; }
.code-cmd { color: #60a5fa; }
.code-colon { color: #64748b; }
.code-eq { color: #64748b; }
.code-param { color: #94a3b8; }
.code-val { color: #22c55e; }
.code-comma { color: #475569; }
.code-semi { color: #475569; }
.code-indent { padding-left: 28px; }

/* Stats */
.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: #16181f;
  border: 1px solid #1e2028;
  border-radius: 12px;
  transition: border-color 0.2s ease;
}
.stat-card:hover {
  border-color: #2a2d38;
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-value {
  font-family: 'Fira Code', monospace;
  font-size: 20px;
  font-weight: 600;
  color: #e2e8f0;
}
.stat-label {
  font-size: 13px;
  color: #64748b;
  margin-top: 2px;
}

/* Section */
.section-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #e2e8f0;
}
.section-subtitle {
  font-size: 13px;
  color: #475569;
}

/* Plugin Grid */
.plugin-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.plugin-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: #16181f;
  border: 1px solid #1e2028;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.plugin-card:hover {
  border-color: #2563EB;
  background: #1a1d27;
  transform: translateX(4px);
}
.plugin-card:hover .plugin-card-arrow {
  color: #2563EB;
  opacity: 1;
}
.plugin-card-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(37, 99, 235, 0.1);
  color: #3B82F6;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.plugin-card-body {
  flex: 1;
  min-width: 0;
}
.plugin-card-name {
  font-family: 'Fira Code', monospace;
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}
.plugin-card-desc {
  font-size: 13px;
  color: #64748b;
  margin-top: 4px;
}
.plugin-card-arrow {
  color: #475569;
  opacity: 0;
  transition: all 0.2s ease;
}

/* Empty */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 0;
}
.empty-title {
  font-size: 16px;
  font-weight: 500;
  color: #94a3b8;
}
.empty-desc {
  font-size: 13px;
  color: #475569;
}
</style>
