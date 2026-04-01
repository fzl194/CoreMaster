<template>
  <div class="home-container">
    <!-- Hero Section -->
    <div
      class="hero-section"
      ref="heroRef"
      @mousemove="onHeroMouseMove"
      @mouseleave="onHeroMouseLeave"
    >
      <div class="hero-grid-pattern"></div>
      <!-- Mouse-following glow -->
      <div class="hero-cursor-glow" :style="heroGlowStyle"></div>
      <!-- Static ambient glow -->
      <div class="hero-ambient-glow"></div>
      <div class="hero-content">
        <h1 class="hero-title">
          <span class="hero-title-text">CoreMaster</span>
        </h1>
        <p class="hero-desc">
          核心网 MML 配置管理与数据挖掘平台
          <span class="hero-badge"><span class="badge-dot"></span> v0.1.0</span>
        </p>
      </div>
      <!-- Tech decoration -->
      <div class="hero-corner hero-corner-tl"></div>
      <div class="hero-corner hero-corner-br"></div>
    </div>

    <!-- Metrics Grid -->
    <div class="metrics-grid">
      <div
        v-for="(metric, idx) in metrics"
        :key="metric.key"
        class="metric-card"
        :class="{ clickable: metric.link }"
        :style="{ '--accent': metric.iconColor, '--enter-delay': `${idx * 60}ms` }"
        ref="cardRefs"
        @mousemove="onCardMouseMove($event, idx)"
        @mouseleave="onCardMouseLeave(idx)"
        @click="metric.link && router.push(metric.link)"
      >
        <div class="card-shine" :style="cards[idx]?.shineStyle"></div>
        <div class="card-border-glow" :style="{ '--accent': metric.iconColor }"></div>
        <div class="metric-header">
          <div class="metric-icon" :style="{ background: metric.bgColor, color: metric.iconColor }">
            <n-icon size="20"><component :is="metric.icon" /></n-icon>
          </div>
        </div>
        <div class="metric-value">{{ metric.value }}</div>
        <div class="metric-label">{{ metric.label }}</div>
        <div class="metric-sub" v-if="metric.sub">{{ metric.sub }}</div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && metrics.length === 0" class="empty-state">
      <n-icon size="48" color="#94A3B8"><cloud-offline-outline /></n-icon>
      <p class="empty-title">无法连接后端服务</p>
      <p class="empty-desc">请确认后端已启动：python -m uvicorn main:app --port 8000</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, markRaw } from "vue";
import { useRouter } from "vue-router";
import { NIcon } from "naive-ui";
import {
  DocumentTextOutline,
  CloudOfflineOutline,
  TerminalOutline,
  ServerOutline,
} from "@vicons/ionicons5";
import { fetchPlugins, type PluginInfo } from "../api";
import { fetchMmlStats } from "../api/mml-manager";
import { fetchTables } from "../api/db-manager";

const router = useRouter();
const loading = ref(true);

interface Metric {
  key: string;
  label: string;
  value: string | number;
  sub?: string;
  icon: any;
  bgColor: string;
  iconColor: string;
  glowColor: string;
  link?: string;
}

const metrics = ref<Metric[]>([]);

// ── Hero mouse tracking ─────────────────────────────────────────────────────
const heroRef = ref<HTMLElement | null>(null);

const heroGlowStyle = ref<Record<string, string>>({});

function onHeroMouseMove(e: MouseEvent) {
  const el = heroRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  heroGlowStyle.value = {
    opacity: "1",
    background: `radial-gradient(480px circle at ${x}px ${y}px, rgba(37, 99, 235, 0.07), rgba(6, 182, 212, 0.03) 40%, transparent 70%)`,
  };
}
function onHeroMouseLeave() {
  heroGlowStyle.value = { opacity: "0" };
}

// ── Card mouse tracking (shine + 3D tilt) ───────────────────────────────────
const cardRefs = ref<HTMLElement[]>([]);

interface CardState {
  shineStyle: Record<string, string>;
  tiltX: number;
  tiltY: number;
}
const cards = reactive<Record<number, CardState>>({});

function onCardMouseMove(e: MouseEvent, idx: number) {
  const el = cardRefs.value[idx];
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const centerX = rect.width / 2;
  const centerY = rect.height / 2;

  // 3D tilt (max 6 degrees)
  const tiltY = ((x - centerX) / centerX) * 6;
  const tiltX = -((y - centerY) / centerY) * 6;

  // Shine position
  const shineStyle = {
    opacity: "1",
    background: `radial-gradient(320px circle at ${x}px ${y}px, rgba(37, 99, 235, 0.06), transparent 60%)`,
  };

  cards[idx] = { shineStyle, tiltX, tiltY };
  el.style.transform = `perspective(800px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) translateY(-4px)`;
}

function onCardMouseLeave(idx: number) {
  const el = cardRefs.value[idx];
  if (!el) return;
  if (cards[idx]) {
    cards[idx].shineStyle = { opacity: "0" };
  }
  el.style.transform = "perspective(800px) rotateX(0deg) rotateY(0deg) translateY(0)";
}

// ── Color palettes per module (light tech theme) ────────────────────────────
const pluginColorMap: Record<string, { bg: string; color: string; glow: string }> = {
  mml_manager:  { bg: "rgba(34, 197, 94, 0.1)",    color: "#16A34A", glow: "radial-gradient(ellipse at top left, rgba(34, 197, 94, 0.04), transparent 70%)" },
  db_manager:   { bg: "rgba(37, 99, 235, 0.1)",     color: "#2563EB", glow: "radial-gradient(ellipse at top left, rgba(37, 99, 235, 0.04), transparent 70%)" },
};

const pluginIconMap: Record<string, any> = {
  mml_manager: markRaw(DocumentTextOutline),
  db_manager: markRaw(ServerOutline),
};

async function buildMetrics(plugins: PluginInfo[]): Promise<Metric[]> {
  const result: Metric[] = [
    {
      key: "plugins",
      label: "功能模块",
      value: plugins.length,
      sub: `${plugins.length} 个模块已加载`,
      icon: markRaw(TerminalOutline),
      bgColor: "rgba(37, 99, 235, 0.08)",
      iconColor: "#2563EB",
      glowColor: "radial-gradient(ellipse at top left, rgba(37, 99, 235, 0.04), transparent 70%)",
    },
  ];

  let mmlStats: { file_count: number; ne_version_count: number } | null = null;
  try { mmlStats = await fetchMmlStats(); } catch { /* */ }

  let dbTableCount = 0;
  try { const tables = await fetchTables(); dbTableCount = tables.length; } catch { /* */ }

  for (const plugin of plugins) {
    const colors = pluginColorMap[plugin.name] || { bg: "rgba(37, 99, 235, 0.08)", color: "#2563EB", glow: "radial-gradient(ellipse at top left, rgba(37, 99, 235, 0.04), transparent 70%)" };

    const base = {
      key: plugin.name,
      label: plugin.menu_title,
      icon: pluginIconMap[plugin.name] || markRaw(TerminalOutline),
      bgColor: colors.bg,
      iconColor: colors.color,
      glowColor: colors.glow,
      link: plugin.path,
    };

    if (plugin.name === "mml_manager" && mmlStats) {
      result.push({ ...base, value: mmlStats.file_count, sub: `${mmlStats.ne_version_count} 个网元版本` });
    } else if (plugin.name === "db_manager") {
      result.push({ ...base, value: dbTableCount, sub: `${dbTableCount} 张数据表` });
    } else {
      result.push({ ...base, value: "--", sub: plugin.description });
    }
  }

  return result;
}

// ── Entrance animation ──────────────────────────────────────────────────────
let entranceTimer: ReturnType<typeof setTimeout> | null = null;

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    metrics.value = await buildMetrics(res.plugins);
  } catch (e) {
    console.error(e);
    metrics.value = [];
  } finally {
    loading.value = false;
  }
  // Stagger card entrance
  entranceTimer = setTimeout(() => {
    document.querySelectorAll(".metric-card").forEach((card, i) => {
      (card as HTMLElement).style.animationDelay = `${i * 60}ms`;
      card.classList.add("card-entered");
    });
  }, 80);
});

onUnmounted(() => {
  if (entranceTimer) clearTimeout(entranceTimer);
});
</script>

<style scoped>
.home-container {
  max-width: 960px;
  margin: 0 auto;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Hero Section
   ═══════════════════════════════════════════════════════════════════════════ */
.hero-section {
  position: relative;
  overflow: hidden;
  padding: 44px 48px 40px;
  background: linear-gradient(135deg, #FFFFFF 0%, #EEF2FF 40%, #E0F2FE 100%);
  border: 1px solid rgba(37, 99, 235, 0.08);
  border-radius: 20px;
  margin-bottom: 24px;
  transition: border-color 0.3s ease;
}
.hero-section:hover {
  border-color: rgba(37, 99, 235, 0.18);
}

/* Tech grid pattern */
.hero-grid-pattern {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(37, 99, 235, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(37, 99, 235, 0.035) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: radial-gradient(ellipse 70% 80% at 30% 50%, black, transparent);
  -webkit-mask-image: radial-gradient(ellipse 70% 80% at 30% 50%, black, transparent);
  pointer-events: none;
}

/* Mouse-following glow */
.hero-cursor-glow {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.4s ease;
}

/* Static ambient glow */
.hero-ambient-glow {
  position: absolute;
  top: -80px;
  right: -60px;
  width: 340px;
  height: 340px;
  background: radial-gradient(circle, rgba(6, 182, 212, 0.06) 0%, transparent 60%);
  pointer-events: none;
}

/* Corner decorations - subtle tech brackets */
.hero-corner {
  position: absolute;
  width: 24px;
  height: 24px;
  pointer-events: none;
}
.hero-corner::before,
.hero-corner::after {
  content: "";
  position: absolute;
  background: rgba(37, 99, 235, 0.2);
}
.hero-corner-tl { top: 16px; left: 16px; }
.hero-corner-tl::before { top: 0; left: 0; width: 12px; height: 1.5px; }
.hero-corner-tl::after  { top: 0; left: 0; width: 1.5px; height: 12px; }
.hero-corner-br { bottom: 16px; right: 16px; }
.hero-corner-br::before { bottom: 0; right: 0; width: 12px; height: 1.5px; }
.hero-corner-br::after  { bottom: 0; right: 0; width: 1.5px; height: 12px; }

/* Hero content */
.hero-content {
  position: relative;
  z-index: 1;
}

.hero-title {
  margin: 0 0 10px;
  line-height: 1;
}

/* Title gradient matches sidebar logo: #2563EB → #06B6D4 */
.hero-title-text {
  font-family: 'Exo 2', monospace;
  font-size: 38px;
  font-weight: 700;
  letter-spacing: -1.5px;
  background: linear-gradient(135deg, #2563EB 0%, #06B6D4 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  position: relative;
  display: inline-block;
}

/* Subtle shimmer on title */
.hero-title-text::after {
  content: "CoreMaster";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    105deg,
    transparent 30%,
    rgba(255, 255, 255, 0.6) 48%,
    rgba(255, 255, 255, 0.6) 52%,
    transparent 70%
  );
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  background-size: 200% 100%;
  animation: shimmer 4s ease-in-out infinite;
  pointer-events: none;
}

@keyframes shimmer {
  0%, 100% { background-position: 200% 0; }
  50% { background-position: -200% 0; }
}

.hero-desc {
  font-size: 15px;
  color: #64748B;
  line-height: 1.6;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* Badge inline with description */
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  background: rgba(37, 99, 235, 0.06);
  border: 1px solid rgba(37, 99, 235, 0.1);
  border-radius: 20px;
  font-size: 11px;
  font-family: 'Fira Code', monospace;
  color: #2563EB;
  letter-spacing: 0.5px;
}
.badge-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #22C55E;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.5);
  animation: pulse-dot 2.5s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { box-shadow: 0 0 4px rgba(34, 197, 94, 0.4); }
  50% { box-shadow: 0 0 10px rgba(34, 197, 94, 0.7); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Metrics Grid
   ═══════════════════════════════════════════════════════════════════════════ */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.metric-card {
  position: relative;
  overflow: hidden;
  padding: 20px;
  background: #FFFFFF;
  border: 1px solid #E2E8F0;
  border-radius: 14px;
  transition: transform 0.35s cubic-bezier(0.2, 0, 0, 1),
              box-shadow 0.35s cubic-bezier(0.2, 0, 0, 1),
              border-color 0.35s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  will-change: transform;

  /* Entrance animation */
  opacity: 0;
  transform: translateY(16px);
}
.metric-card.card-entered {
  animation: cardEnter 0.5s cubic-bezier(0.2, 0, 0, 1) forwards;
}
@keyframes cardEnter {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Cursor-tracking shine */
.card-shine {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s ease;
  border-radius: 14px;
  z-index: 1;
}

/* Border glow on hover */
.card-border-glow {
  position: absolute;
  inset: -1px;
  border-radius: 15px;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.35s ease;
  background: none;
  box-shadow: inset 0 0 0 1px var(--accent, #2563EB);
  z-index: 0;
}

.metric-card.clickable {
  cursor: pointer;
}

.metric-card.clickable:hover {
  border-color: transparent;
}
.metric-card.clickable:hover .card-border-glow {
  opacity: 1;
}
.metric-card.clickable:hover .card-shine {
  opacity: 1;
}

.metric-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  position: relative;
  z-index: 2;
}
.metric-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.3s ease;
}
.metric-card:hover .metric-icon {
  transform: scale(1.08);
}
.metric-value {
  font-family: 'Exo 2', monospace;
  font-size: 28px;
  font-weight: 700;
  color: #0F172A;
  margin-bottom: 4px;
  position: relative;
  z-index: 2;
}
.metric-label {
  font-size: 13px;
  color: #64748B;
  position: relative;
  z-index: 2;
}
.metric-sub {
  font-size: 12px;
  color: #94A3B8;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #F1F5F9;
  position: relative;
  z-index: 2;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Empty State
   ═══════════════════════════════════════════════════════════════════════════ */
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
  color: #475569;
}
.empty-desc {
  font-size: 13px;
  color: #94A3B8;
  font-family: 'Fira Code', monospace;
}
</style>
