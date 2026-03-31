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
    </div>

    <!-- Metrics Grid -->
    <div class="metrics-grid">
      <div
        v-for="metric in metrics"
        :key="metric.key"
        class="metric-card"
        :class="{ clickable: metric.link }"
        @click="metric.link && router.push(metric.link)"
      >
        <div class="metric-header">
          <div class="metric-icon" :style="{ background: metric.bgColor, color: metric.iconColor }">
            <n-icon size="20"><component :is="metric.icon" /></n-icon>
          </div>
          <div class="metric-trend" v-if="metric.trend">
            <n-icon size="14" :color="metric.trend > 0 ? '#22C55E' : '#EF4444'">
              <trending-up-outline v-if="metric.trend > 0" />
              <trending-down-outline v-else />
            </n-icon>
          </div>
        </div>
        <div class="metric-value">{{ metric.value }}</div>
        <div class="metric-label">{{ metric.label }}</div>
        <div class="metric-sub" v-if="metric.sub">{{ metric.sub }}</div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && metrics.length === 0" class="empty-state">
      <n-icon size="48" color="#334155"><cloud-offline-outline /></n-icon>
      <p class="empty-title">无法连接后端服务</p>
      <p class="empty-desc">请确认后端已启动：python -m uvicorn main:app --port 8000</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, type Component } from "vue";
import { useRouter } from "vue-router";
import { NIcon } from "naive-ui";
import {
  DocumentTextOutline,
  GitCompareOutline,
  ScanOutline,
  CreateOutline,
  CheckmarkCircleOutline,
  CloudOfflineOutline,
  TrendingUpOutline,
  TrendingDownOutline,
  ServerOutline,
  TerminalOutline,
} from "@vicons/ionicons5";
import { fetchPlugins, type PluginInfo, type MenuItem } from "../api";

const router = useRouter();
const loading = ref(true);

interface Metric {
  key: string;
  label: string;
  value: string | number;
  sub?: string;
  icon: Component;
  bgColor: string;
  iconColor: string;
  trend?: number;
  link?: string;
}

const metrics = ref<Metric[]>([]);

function buildMetrics(plugins: PluginInfo[], menus: MenuItem[]): Metric[] {
  const result: Metric[] = [
    {
      key: "plugins",
      label: "功能模块",
      value: plugins.length,
      sub: `${plugins.length} 个模块已加载`,
      icon: TerminalOutline,
      bgColor: "rgba(37, 99, 235, 0.15)",
      iconColor: "#3B82F6",
    },
    {
      key: "services",
      label: "公共服务",
      value: "3",
      sub: "数据库 / 解析器 / 配置",
      icon: ServerOutline,
      bgColor: "rgba(249, 115, 22, 0.15)",
      iconColor: "#F97316",
    },
  ];

  // 为每个插件生成一个指标卡片（占位数据，后续由插件提供真实数据）
  const pluginIconMap: Record<string, Component> = {
    mml_manager: DocumentTextOutline,
    version_diff: GitCompareOutline,
    mml_graph: ScanOutline,
    script_gen: CreateOutline,
    validator: CheckmarkCircleOutline,
  };
  const pluginColorMap: Record<string, { bg: string; color: string }> = {
    mml_manager: { bg: "rgba(34, 197, 94, 0.15)", color: "#22C55E" },
    version_diff: { bg: "rgba(168, 85, 247, 0.15)", color: "#A855F7" },
    mml_graph: { bg: "rgba(6, 182, 212, 0.15)", color: "#06B6D4" },
    script_gen: { bg: "rgba(245, 158, 11, 0.15)", color: "#F59E0B" },
    validator: { bg: "rgba(239, 68, 68, 0.15)", color: "#EF4444" },
  };

  const placeholderLabels: Record<string, string> = {
    mml_manager: "MML 脚本",
    version_diff: "版本对比",
    mml_graph: "图谱节点",
    script_gen: "生成模板",
    validator: "校验规则",
  };

  for (const plugin of plugins) {
    const menu = menus.find((m) => m.path === `/plugins/${plugin.name.replace(/_/g, "-")}`);
    const colors = pluginColorMap[plugin.name] || { bg: "rgba(37, 99, 235, 0.15)", color: "#3B82F6" };
    result.push({
      key: plugin.name,
      label: placeholderLabels[plugin.name] || plugin.name,
      value: "--",
      sub: plugin.description,
      icon: pluginIconMap[plugin.name] || TerminalOutline,
      bgColor: colors.bg,
      iconColor: colors.color,
      link: menu?.path,
    });
  }

  return result;
}

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    metrics.value = buildMetrics(res.plugins, res.menus);
  } catch (e) {
    console.error(e);
    metrics.value = [];
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
  padding: 32px 40px;
  background: linear-gradient(135deg, #1a1d27 0%, #16181f 100%);
  border: 1px solid #1e2028;
  border-radius: 16px;
  margin-bottom: 24px;
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

/* Metrics Grid */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}
.metric-card {
  padding: 20px;
  background: #16181f;
  border: 1px solid #1e2028;
  border-radius: 12px;
  transition: all 0.2s ease;
}
.metric-card.clickable {
  cursor: pointer;
}
.metric-card.clickable:hover {
  border-color: #2563EB;
  background: #1a1d27;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
}
.metric-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.metric-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.metric-trend {
  display: flex;
  align-items: center;
}
.metric-value {
  font-family: 'Fira Code', monospace;
  font-size: 28px;
  font-weight: 700;
  color: #e2e8f0;
  margin-bottom: 4px;
}
.metric-label {
  font-size: 13px;
  color: #64748b;
}
.metric-sub {
  font-size: 12px;
  color: #475569;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #1e2028;
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
  font-family: 'Fira Code', monospace;
}
</style>
