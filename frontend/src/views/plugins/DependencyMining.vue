<template>
  <div class="dep-mining-view">
    <!-- Header -->
    <n-page-header title="依赖挖掘" subtitle="MML 命令参数依赖关系发现与审核">
      <template #extra>
        <n-space align="center">
          <n-select
            v-model:value="selectedNeVersionId"
            :options="neVersionOptions"
            placeholder="选择网元版本"
            style="width: 280px"
            @update:value="handleNeVersionChange"
          />
          <n-button
            type="primary"
            :loading="generating"
            :disabled="!selectedNeVersionId"
            @click="handleGenerate"
          >
            提取 & 生成
          </n-button>
          <n-button :disabled="!selectedNeVersionId" @click="loadCandidates">
            刷新列表
          </n-button>
        </n-space>
      </template>
    </n-page-header>

    <!-- Stats -->
    <n-grid :cols="4" :x-gap="12" :y-gap="12" style="margin-top: 16px">
      <n-gi>
        <n-card size="small"><n-statistic label="候选总数" :value="candidates.length" /></n-card>
      </n-gi>
      <n-gi>
        <n-card size="small"><n-statistic label="已通过" :value="acceptedCount" /></n-card>
      </n-gi>
      <n-gi>
        <n-card size="small"><n-statistic label="待审核" :value="pendingCount" /></n-card>
      </n-gi>
      <n-gi>
        <n-card size="small"><n-statistic label="已拒绝" :value="rejectedCount" /></n-card>
      </n-gi>
    </n-grid>

    <!-- Filter Tags -->
    <n-space style="margin-top: 16px; margin-bottom: 12px">
      <n-tag
        v-for="f in statusFilters"
        :key="f.value"
        :type="activeFilter === f.value ? 'primary' : 'default'"
        style="cursor: pointer"
        round
        @click="activeFilter = f.value"
      >
        {{ f.label }} ({{ f.value === 'all' ? candidates.length : candidates.filter(c => c.status === f.value).length }})
      </n-tag>
    </n-space>

    <!-- Table -->
    <n-data-table
      :columns="columns"
      :data="filteredCandidates"
      :pagination="{ pageSize: 20 }"
      :row-key="(row: Candidate) => row.id"
      striped
    />

    <!-- Evidence Drawer -->
    <n-drawer v-model:show="showDrawer" :width="520" placement="right">
      <n-drawer-content :title="drawerTitle" closable>
        <template v-if="selectedCandidate">
          <n-descriptions bordered :column="1" label-style="width: 120px">
            <n-descriptions-item label="引用命令">{{ selectedCandidate.ref_command }}</n-descriptions-item>
            <n-descriptions-item label="引用参数">{{ selectedCandidate.ref_param }}</n-descriptions-item>
            <n-descriptions-item label="定义命令">{{ selectedCandidate.def_command }}</n-descriptions-item>
            <n-descriptions-item label="定义参数">{{ selectedCandidate.def_param }}</n-descriptions-item>
            <n-descriptions-item label="置信度">
              <n-tag :type="confidenceType(selectedCandidate.confidence)" round>
                {{ (selectedCandidate.confidence * 100).toFixed(1) }}%
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="状态">{{ selectedCandidate.status }}</n-descriptions-item>
          </n-descriptions>

          <n-divider>评分明细</n-divider>
          <n-grid :cols="2" :x-gap="8" :y-gap="8">
            <n-gi><n-statistic label="支持度" :value="pct(selectedCandidate.scores.support)" /></n-gi>
            <n-gi><n-statistic label="区分度" :value="pct(selectedCandidate.scores.distinctiveness)" /></n-gi>
            <n-gi><n-statistic label="顺序一致性" :value="pct(selectedCandidate.scores.order_consistency)" /></n-gi>
            <n-gi><n-statistic label="名称相关度" :value="pct(selectedCandidate.scores.name_relevance)" /></n-gi>
          </n-grid>

          <n-divider>证据</n-divider>
          <p>命中脚本数：{{ selectedCandidate.evidence.hit_count }} / {{ selectedCandidate.evidence.total_scripts }}</p>
          <p style="margin-top: 8px">匹配值：</p>
          <n-space size="small">
            <n-tag v-for="v in selectedCandidate.evidence.hit_values.slice(0, 15)" :key="v" size="small">{{ v }}</n-tag>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from "vue";
import {
  NPageHeader, NSelect, NButton, NSpace, NDataTable, NTag,
  NGrid, NGi, NStatistic, NCard, NDrawer, NDrawerContent,
  NDescriptions, NDescriptionsItem, NDivider,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import { fetchNeVersions, type NeVersion } from "../../api/mml-manager";
import {
  generateCandidates as apiGenerate,
  fetchCandidates as apiFetch,
  acceptCandidate as apiAccept,
  rejectCandidate as apiReject,
  type Candidate,
} from "../../api/dependency-mining";

// ── State ────────────────────────────────────────────────────────────────

const neVersions = ref<NeVersion[]>([]);
const selectedNeVersionId = ref<number | null>(null);
const candidates = ref<Candidate[]>([]);
const generating = ref(false);
const showDrawer = ref(false);
const selectedCandidate = ref<Candidate | null>(null);
const activeFilter = ref("all");

// ── Computed ─────────────────────────────────────────────────────────────

const neVersionOptions = computed(() =>
  neVersions.value.map((nv) => ({
    label: `${nv.vendor} / ${nv.ne_type} / ${nv.version}`,
    value: nv.id,
  }))
);

const acceptedCount = computed(() => candidates.value.filter((c) => c.status === "accepted").length);
const pendingCount = computed(() => candidates.value.filter((c) => c.status !== "accepted" && c.status !== "rejected").length);
const rejectedCount = computed(() => candidates.value.filter((c) => c.status === "rejected").length);

const filteredCandidates = computed(() => {
  if (activeFilter.value === "all") return candidates.value;
  return candidates.value.filter((c) => c.status === activeFilter.value);
});

const drawerTitle = computed(() => {
  if (!selectedCandidate.value) return "";
  const c = selectedCandidate.value;
  return `${c.ref_command}.${c.ref_param} → ${c.def_command}.${c.def_param}`;
});

const statusFilters = [
  { label: "全部", value: "all" },
  { label: "待审核", value: "pending" },
  { label: "已通过", value: "accepted" },
  { label: "已拒绝", value: "rejected" },
];

// ── Helpers ──────────────────────────────────────────────────────────────

function confidenceType(conf: number): "success" | "warning" | "error" {
  if (conf >= 0.85) return "success";
  if (conf >= 0.5) return "warning";
  return "error";
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function statusTag(status: string): { type: "success" | "warning" | "error" | "default"; label: string } {
  const map: Record<string, { type: "success" | "warning" | "error" | "default"; label: string }> = {
    auto_passed: { type: "success", label: "高置信度" },
    llm_review: { type: "warning", label: "LLM审核" },
    man_review: { type: "error", label: "人工审核" },
    accepted: { type: "success", label: "已通过" },
    rejected: { type: "default", label: "已拒绝" },
    pending: { type: "warning", label: "待审核" },
  };
  return map[status] ?? { type: "default" as const, label: status };
}

// ── Table Columns ────────────────────────────────────────────────────────

const columns: DataTableColumns<Candidate> = [
  { title: "引用命令", key: "ref_command", width: 130 },
  { title: "引用参数", key: "ref_param", width: 120 },
  { title: "定义命令", key: "def_command", width: 130 },
  { title: "定义参数", key: "def_param", width: 120 },
  {
    title: "置信度",
    key: "confidence",
    width: 100,
    sorter: (a: Candidate, b: Candidate) => a.confidence - b.confidence,
    defaultSortOrder: "descend",
    render(row: Candidate) {
      return h(NTag, { type: confidenceType(row.confidence), round: true, size: "small" }, () =>
        `${(row.confidence * 100).toFixed(1)}%`
      );
    },
  },
  {
    title: "状态",
    key: "status",
    width: 110,
    render(row: Candidate) {
      const info = statusTag(row.status);
      return h(NTag, { type: info.type, round: true, size: "small" }, () => info.label);
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 200,
    render(row: Candidate) {
      const btns = [
        h(NButton, { size: "small", quaternary: true, onClick: () => openDrawer(row) }, { default: () => "详情" }),
      ];
      if (row.status !== "accepted" && row.status !== "rejected") {
        btns.push(
          h(NButton, { size: "small", type: "success", onClick: () => handleAccept(row) }, { default: () => "通过" }),
          h(NButton, { size: "small", type: "error", onClick: () => handleReject(row) }, { default: () => "拒绝" }),
        );
      }
      return h(NSpace, { size: 4 }, { default: () => btns });
    },
  },
];

// ── Actions ──────────────────────────────────────────────────────────────

async function handleNeVersionChange(): Promise<void> {
  if (selectedNeVersionId.value) {
    await loadCandidates();
  }
}

async function loadCandidates(): Promise<void> {
  if (!selectedNeVersionId.value) return;
  try {
    candidates.value = await apiFetch({ ne_version_id: selectedNeVersionId.value });
  } catch (e) {
    console.error("Failed to load candidates:", e);
  }
}

async function handleGenerate(): Promise<void> {
  if (!selectedNeVersionId.value) return;
  generating.value = true;
  try {
    const result = await apiGenerate(selectedNeVersionId.value);
    candidates.value = result.candidates;
  } catch (e) {
    console.error("Generation failed:", e);
  } finally {
    generating.value = false;
  }
}

function openDrawer(candidate: Candidate): void {
  selectedCandidate.value = candidate;
  showDrawer.value = true;
}

async function handleAccept(candidate: Candidate): Promise<void> {
  try {
    await apiAccept(candidate.id, "admin");
    await loadCandidates();
  } catch (e) {
    console.error("Accept failed:", e);
  }
}

async function handleReject(candidate: Candidate): Promise<void> {
  try {
    await apiReject(candidate.id, "admin");
    await loadCandidates();
  } catch (e) {
    console.error("Reject failed:", e);
  }
}

onMounted(async () => {
  try {
    neVersions.value = await fetchNeVersions();
  } catch (e) {
    console.error("Failed to load NE versions:", e);
  }
});
</script>

<style scoped>
.dep-mining-view {
  max-width: 1400px;
}
</style>
