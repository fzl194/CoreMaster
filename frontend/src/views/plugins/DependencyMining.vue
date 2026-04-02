<template>
  <div class="dep-mining-view">
    <!-- Header -->
    <n-page-header title="依赖挖掘" subtitle="MML 命令参数依赖关系发现与审核">
      <template #extra>
        <n-select
          v-model:value="selectedNeVersionId"
          :options="neVersionOptions"
          placeholder="选择网元版本"
          style="width: 280px"
          @update:value="handleNeVersionChange"
        />
      </template>
    </n-page-header>

    <!-- Main Layout: left file list + right tabbed candidates -->
    <n-layout has-sider style="margin-top: 16px; height: calc(100vh - 180px)">
      <n-layout-sider
        bordered
        :width="340"
        content-style="padding: 12px;"
        :native-scrollbar="false"
      >
        <n-space vertical :size="12">
          <n-space justify="space-between" align="center">
            <span style="font-weight: 600; font-size: 14px">文件列表</span>
            <n-space :size="6">
              <n-button
                type="primary"
                size="small"
                :loading="miningBusy"
                :disabled="!selectedNeVersionId || checkedFileIds.length === 0"
                @click="handleMineSelected"
              >
                挖掘选中
              </n-button>
              <n-button
                size="small"
                :loading="miningBusy"
                :disabled="!selectedNeVersionId || checkedFileIds.length === 0"
                @click="handleReMineSelected"
              >
                重新挖掘
              </n-button>
            </n-space>
          </n-space>

          <n-checkbox-group v-model:value="checkedFileIds" v-if="fileList.length > 0">
            <n-space vertical :size="4" style="width: 100%">
              <div
                v-for="f in fileList"
                :key="f.file_entry_id"
                class="file-row"
              >
                <n-checkbox :value="f.file_entry_id" :label="f.file_name" />
                <n-tag
                  :type="f.mined ? 'success' : 'default'"
                  size="small"
                  round
                >
                  {{ f.mined ? '已挖掘' : '未挖掘' }}
                </n-tag>
              </div>
            </n-space>
          </n-checkbox-group>
          <n-empty v-else description="请先选择网元版本" style="margin-top: 40px" />
        </n-space>
      </n-layout-sider>

      <n-layout-content content-style="padding: 0 16px;">
        <n-tabs v-model:value="activeTab" type="line" animated style="height: 100%">
          <!-- Tab 1: Candidate Pool -->
          <n-tab-pane name="pending" tab="候选池">
            <n-space :size="12" style="margin-bottom: 12px">
              <n-card size="small" style="min-width: 120px">
                <n-statistic label="待审核" :value="pendingCandidates.length" />
              </n-card>
              <n-card size="small" style="min-width: 120px">
                <n-statistic label="已拒绝" :value="rejectedCandidates.length" />
              </n-card>
            </n-space>
            <n-data-table
              :columns="pendingColumns"
              :data="pendingOrRejectedCandidates"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: Candidate) => row.id"
              striped
              size="small"
            />
          </n-tab-pane>

          <!-- Tab 2: Graph Library -->
          <n-tab-pane name="graph" tab="图谱库">
            <n-space :size="12" style="margin-bottom: 12px">
              <n-card size="small" style="min-width: 120px">
                <n-statistic label="图谱条目" :value="graphCandidates.length" />
              </n-card>
            </n-space>
            <n-data-table
              :columns="graphColumns"
              :data="graphCandidates"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: Candidate) => row.id"
              striped
              size="small"
            />
          </n-tab-pane>

          <!-- Tab 3: Non-Graph Library -->
          <n-tab-pane name="non_graph" tab="非图谱库">
            <n-space :size="12" style="margin-bottom: 12px">
              <n-card size="small" style="min-width: 120px">
                <n-statistic label="非图谱条目" :value="nonGraphCandidates.length" />
              </n-card>
            </n-space>
            <n-data-table
              :columns="nonGraphColumns"
              :data="nonGraphCandidates"
              :pagination="{ pageSize: 15 }"
              :row-key="(row: Candidate) => row.id"
              striped
              size="small"
            />
          </n-tab-pane>
        </n-tabs>
      </n-layout-content>
    </n-layout>

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
            <n-descriptions-item label="审核路由">
              <n-tag :type="routeTagType(selectedCandidate.review_route)" round size="small">
                {{ selectedCandidate.review_route ?? '-' }}
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
  NDescriptions, NDescriptionsItem, NDivider, NLayout,
  NLayoutSider, NLayoutContent, NTabs, NTabPane,
  NCheckbox, NCheckboxGroup, NEmpty,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import { fetchNeVersions, type NeVersion } from "../../api/mml-manager";
import {
  fetchCandidates as apiFetch,
  acceptCandidate as apiAccept,
  rejectCandidate as apiReject,
  mineFiles as apiMineFiles,
  reMineFile as apiReMineFile,
  fetchMiningStatus as apiFetchMiningStatus,
  markNonGraph as apiMarkNonGraph,
  revertCandidate as apiRevert,
  type Candidate,
  type FileMiningStatus,
} from "../../api/dependency-mining";

// ── State ────────────────────────────────────────────────────────────────

const neVersions = ref<NeVersion[]>([]);
const selectedNeVersionId = ref<number | null>(null);
const candidates = ref<Candidate[]>([]);
const fileList = ref<FileMiningStatus[]>([]);
const checkedFileIds = ref<number[]>([]);
const miningBusy = ref(false);
const showDrawer = ref(false);
const selectedCandidate = ref<Candidate | null>(null);
const activeTab = ref("pending");

// ── Computed ─────────────────────────────────────────────────────────────

const neVersionOptions = computed(() =>
  neVersions.value.map((nv) => ({
    label: `${nv.vendor} / ${nv.ne_type} / ${nv.version}`,
    value: nv.id,
  }))
);

const pendingCandidates = computed(() => candidates.value.filter((c) => c.status === "pending"));
const rejectedCandidates = computed(() => candidates.value.filter((c) => c.status === "rejected"));
const pendingOrRejectedCandidates = computed(() =>
  candidates.value.filter((c) => c.status === "pending" || c.status === "rejected")
);
const graphCandidates = computed(() => candidates.value.filter((c) => c.status === "graph"));
const nonGraphCandidates = computed(() => candidates.value.filter((c) => c.status === "non_graph"));

const drawerTitle = computed(() => {
  if (!selectedCandidate.value) return "";
  const c = selectedCandidate.value;
  return `${c.ref_command}.${c.ref_param} -> ${c.def_command}.${c.def_param}`;
});

// ── Helpers ──────────────────────────────────────────────────────────────

function confidenceType(conf: number): "success" | "warning" | "error" {
  if (conf >= 0.85) return "success";
  if (conf >= 0.5) return "warning";
  return "error";
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function routeTagType(route: string | null): "success" | "warning" | "error" | "default" {
  if (route === "auto") return "success";
  if (route === "llm") return "warning";
  if (route === "manual") return "error";
  return "default";
}

function routeLabel(route: string | null): string {
  if (route === "auto") return "auto";
  if (route === "llm") return "LLM";
  if (route === "manual") return "人工";
  return route ?? "-";
}

// ── Table Columns ────────────────────────────────────────────────────────

const pendingColumns: DataTableColumns<Candidate> = [
  { title: "引用命令", key: "ref_command", width: 120 },
  { title: "引用参数", key: "ref_param", width: 110 },
  { title: "定义命令", key: "def_command", width: 120 },
  { title: "定义参数", key: "def_param", width: 110 },
  {
    title: "置信度",
    key: "confidence",
    width: 90,
    sorter: (a: Candidate, b: Candidate) => a.confidence - b.confidence,
    defaultSortOrder: "descend",
    render(row: Candidate) {
      return h(NTag, { type: confidenceType(row.confidence), round: true, size: "small" }, () =>
        `${(row.confidence * 100).toFixed(1)}%`
      );
    },
  },
  {
    title: "审核路由",
    key: "review_route",
    width: 90,
    render(row: Candidate) {
      return h(NTag, { type: routeTagType(row.review_route), round: true, size: "small" }, () =>
        routeLabel(row.review_route)
      );
    },
  },
  {
    title: "状态",
    key: "status",
    width: 80,
    render(row: Candidate) {
      const label = row.status === "pending" ? "待审核" : "已拒绝";
      const type = row.status === "pending" ? "warning" : "default";
      return h(NTag, { type, round: true, size: "small" }, () => label);
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 240,
    render(row: Candidate) {
      const btns = [
        h(NButton, { size: "small", quaternary: true, onClick: () => openDrawer(row) }, { default: () => "详情" }),
      ];
      if (row.status === "pending") {
        btns.push(
          h(NButton, { size: "small", type: "success", onClick: () => handleAccept(row) }, { default: () => "通过" }),
          h(NButton, { size: "small", type: "error", onClick: () => handleReject(row) }, { default: () => "拒绝" }),
          h(NButton, { size: "small", type: "warning", onClick: () => handleMarkNonGraph(row) }, { default: () => "标记非图谱" }),
        );
      } else if (row.status === "rejected") {
        btns.push(
          h(NButton, { size: "small", type: "success", onClick: () => handleAccept(row) }, { default: () => "通过" }),
          h(NButton, { size: "small", type: "warning", onClick: () => handleMarkNonGraph(row) }, { default: () => "标记非图谱" }),
        );
      }
      return h(NSpace, { size: 4 }, { default: () => btns });
    },
  },
];

const graphColumns: DataTableColumns<Candidate> = [
  { title: "引用命令", key: "ref_command", width: 120 },
  { title: "引用参数", key: "ref_param", width: 110 },
  { title: "定义命令", key: "def_command", width: 120 },
  { title: "定义参数", key: "def_param", width: 110 },
  {
    title: "置信度",
    key: "confidence",
    width: 90,
    render(row: Candidate) {
      return h(NTag, { type: confidenceType(row.confidence), round: true, size: "small" }, () =>
        `${(row.confidence * 100).toFixed(1)}%`
      );
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 150,
    render(row: Candidate) {
      return h(NSpace, { size: 4 }, {
        default: () => [
          h(NButton, { size: "small", quaternary: true, onClick: () => openDrawer(row) }, { default: () => "详情" }),
          h(NButton, { size: "small", type: "warning", onClick: () => handleRevert(row) }, { default: () => "回退" }),
        ],
      });
    },
  },
];

const nonGraphColumns: DataTableColumns<Candidate> = [
  { title: "引用命令", key: "ref_command", width: 120 },
  { title: "引用参数", key: "ref_param", width: 110 },
  { title: "定义命令", key: "def_command", width: 120 },
  { title: "定义参数", key: "def_param", width: 110 },
  {
    title: "标记原因",
    key: "non_graph_reason",
    width: 150,
    ellipsis: { tooltip: true },
    render(row: Candidate) {
      return row.non_graph_reason ?? "-";
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 150,
    render(row: Candidate) {
      return h(NSpace, { size: 4 }, {
        default: () => [
          h(NButton, { size: "small", quaternary: true, onClick: () => openDrawer(row) }, { default: () => "详情" }),
          h(NButton, { size: "small", type: "warning", onClick: () => handleRevert(row) }, { default: () => "回退" }),
        ],
      });
    },
  },
];

// ── Actions ──────────────────────────────────────────────────────────────

async function handleNeVersionChange(): Promise<void> {
  if (!selectedNeVersionId.value) return;
  checkedFileIds.value = [];
  activeTab.value = "pending";
  await Promise.all([loadCandidates(), loadFileList()]);
}

async function loadCandidates(): Promise<void> {
  if (!selectedNeVersionId.value) return;
  try {
    candidates.value = await apiFetch({ ne_version_id: selectedNeVersionId.value });
  } catch (e) {
    console.error("Failed to load candidates:", e);
  }
}

async function loadFileList(): Promise<void> {
  if (!selectedNeVersionId.value) return;
  try {
    fileList.value = await apiFetchMiningStatus(selectedNeVersionId.value);
  } catch (e) {
    console.error("Failed to load mining status:", e);
  }
}

async function handleMineSelected(): Promise<void> {
  if (!selectedNeVersionId.value || checkedFileIds.value.length === 0) return;
  miningBusy.value = true;
  try {
    await apiMineFiles(checkedFileIds.value);
    await Promise.all([loadCandidates(), loadFileList()]);
  } catch (e) {
    console.error("Mine files failed:", e);
  } finally {
    miningBusy.value = false;
  }
}

async function handleReMineSelected(): Promise<void> {
  if (!selectedNeVersionId.value || checkedFileIds.value.length === 0) return;
  miningBusy.value = true;
  try {
    // Re-mine each selected file that has already been mined
    for (const fileId of checkedFileIds.value) {
      await apiReMineFile(fileId);
    }
    await Promise.all([loadCandidates(), loadFileList()]);
  } catch (e) {
    console.error("Re-mine failed:", e);
  } finally {
    miningBusy.value = false;
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

async function handleMarkNonGraph(candidate: Candidate): Promise<void> {
  const reason = window.prompt("标记原因:", "管理员标记");
  if (!reason) return;
  try {
    await apiMarkNonGraph(candidate.id, reason, "admin");
    await loadCandidates();
  } catch (e) {
    console.error("Mark non-graph failed:", e);
  }
}

async function handleRevert(candidate: Candidate): Promise<void> {
  try {
    await apiRevert(candidate.id, "admin");
    await loadCandidates();
  } catch (e) {
    console.error("Revert failed:", e);
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
  max-width: 1600px;
}
.file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
}
</style>
