<template>
  <div style="padding: 16px 24px">
    <n-page-header title="图谱挖掘" subtitle="MML 命令参数依赖关系挖掘与图谱管理">
      <template #extra>
        <n-select
          v-model:value="selectedNeVersion"
          :options="neVersionOptions"
          placeholder="选择网元版本"
          style="width: 260px"
          @update:value="onNeVersionChange"
        />
      </template>
    </n-page-header>

    <n-tabs v-model:value="activeTab" type="card" style="margin-top: 16px" @update:value="onTabChange">
      <n-tab-pane name="files" tab="文件管理">
        <n-space vertical>
          <n-space>
            <n-button type="primary" :disabled="!selectedNeVersion || selectedFiles.length === 0" @click="handleStartMining">
              开始挖掘 ({{ selectedFiles.length }})
            </n-button>
            <n-tag v-if="currentJob" :type="jobStatusType">
              任务 #{{ currentJob.id }}: {{ currentJob.status }}
              ({{ currentJob.progress_current }}/{{ currentJob.progress_total }})
            </n-tag>
          </n-space>
          <n-data-table
            :columns="fileColumns"
            :data="files"
            :row-key="(r: FileMiningInfo) => r.file_entry_id"
            :loading="filesLoading"
          />
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="candidates" tab="候选管理">
        <n-space vertical>
          <n-space>
            <n-select
              v-model:value="candidateStatusFilter"
              :options="statusFilterOptions"
              placeholder="状态筛选"
              style="width: 160px"
              clearable
              @update:value="loadCandidates"
            />
            <n-button @click="loadCandidates">刷新</n-button>
          </n-space>
          <n-data-table
            :columns="candidateColumns"
            :data="candidates"
            :row-key="(r: Candidate) => r.id"
            :loading="candidatesLoading"
            :pagination="{ pageSize: 20 }"
          />
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="edges" tab="图谱边">
        <n-space vertical>
          <n-button @click="loadEdges">刷新</n-button>
          <n-data-table
            :columns="edgeColumns"
            :data="edges"
            :row-key="(r: GraphEdge) => r.id"
            :loading="edgesLoading"
            :pagination="{ pageSize: 20 }"
          />
        </n-space>
      </n-tab-pane>
    </n-tabs>

    <!-- Evidence Drawer -->
    <n-drawer v-model:show="showEvidence" :width="500">
      <n-drawer-content title="候选详情">
        <template v-if="selectedCandidate">
          <n-descriptions bordered :column="1" label-placement="left">
            <n-descriptions-item label="Ref命令">{{ selectedCandidate.ref_command }}</n-descriptions-item>
            <n-descriptions-item label="Ref参数">{{ selectedCandidate.ref_param }}</n-descriptions-item>
            <n-descriptions-item label="Def命令">{{ selectedCandidate.def_command }}</n-descriptions-item>
            <n-descriptions-item label="Def参数">{{ selectedCandidate.def_param }}</n-descriptions-item>
            <n-descriptions-item label="置信度">{{ selectedCandidate.confidence.toFixed(4) }}</n-descriptions-item>
            <n-descriptions-item label="状态">{{ selectedCandidate.status }}</n-descriptions-item>
          </n-descriptions>

          <n-divider>评分详情</n-divider>
          <n-descriptions bordered :column="1" label-placement="left" v-if="selectedCandidate.scores">
            <n-descriptions-item label="支持度">{{ selectedCandidate.scores.support.toFixed(4) }}</n-descriptions-item>
            <n-descriptions-item label="区分度">{{ selectedCandidate.scores.distinctiveness.toFixed(4) }}</n-descriptions-item>
            <n-descriptions-item label="顺序一致性">{{ selectedCandidate.scores.order_consistency.toFixed(4) }}</n-descriptions-item>
            <n-descriptions-item label="名称相关性">{{ selectedCandidate.scores.name_relevance.toFixed(4) }}</n-descriptions-item>
          </n-descriptions>

          <n-divider>证据</n-divider>
          <div v-if="selectedCandidate.evidence">
            <p>命中次数: {{ selectedCandidate.evidence.hit_count }}</p>
            <p>命中文件: {{ selectedCandidate.evidence.hit_file_count }} / {{ selectedCandidate.evidence.total_mined_files }}</p>
            <p>命中值: {{ selectedCandidate.evidence.hit_values?.join(', ') }}</p>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- Mark Non-Graph Modal -->
    <n-modal v-model:show="showMarkNonGraph">
      <n-card title="标记为非图谱依赖" style="width: 400px">
        <n-input v-model:value="nonGraphReason" type="textarea" placeholder="请输入原因" />
        <template #action>
          <n-space>
            <n-button @click="showMarkNonGraph = false">取消</n-button>
            <n-button type="warning" @click="confirmMarkNonGraph">确认</n-button>
          </n-space>
        </template>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from "vue";
import {
  NPageHeader, NSelect, NTabs, NTabPane, NSpace, NButton, NDataTable, NTag,
  NDrawer, NDrawerContent, NDescriptions, NDescriptionsItem, NDivider, NModal,
  NCard, NInput, useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import {
  fetchFiles, fetchCandidates, fetchGraphEdges, acceptCandidate,
  rejectCandidate, markNonGraph, revertCandidate, startMining, fetchJob,
} from "../../api/graph-mining";
import type { FileMiningInfo, Candidate, GraphEdge, JobInfo } from "../../api/graph-mining";
import { fetchNeVersions } from "../../api/mml-manager";

const message = useMessage();

// State
const selectedNeVersion = ref<number | null>(null);
const neVersions = ref<{ id: number; vendor: string; ne_type: string; version: string }[]>([]);
const activeTab = ref("files");
const files = ref<FileMiningInfo[]>([]);
const filesLoading = ref(false);
const candidates = ref<Candidate[]>([]);
const candidatesLoading = ref(false);
const edges = ref<GraphEdge[]>([]);
const edgesLoading = ref(false);
const candidateStatusFilter = ref<string | null>(null);
const selectedFiles = ref<number[]>([]);
const currentJob = ref<JobInfo | null>(null);
const showEvidence = ref(false);
const selectedCandidate = ref<Candidate | null>(null);
const showMarkNonGraph = ref(false);
const markNonGraphTarget = ref<number | null>(null);
const nonGraphReason = ref("");

// Computed
const neVersionOptions = computed(() =>
  neVersions.value.map((nv) => ({
    label: `${nv.vendor} / ${nv.ne_type} / ${nv.version}`,
    value: nv.id,
  }))
);

const statusFilterOptions = [
  { label: "待审核", value: "pending" },
  { label: "已入图谱", value: "graph" },
  { label: "非图谱", value: "non_graph" },
  { label: "已拒绝", value: "rejected" },
  { label: "待人工审核", value: "ready_for_review" },
];

const jobStatusType = computed(() => {
  if (!currentJob.value) return "default";
  const s = currentJob.value.status;
  if (s === "completed") return "success";
  if (s === "failed" || s === "cancelled") return "error";
  if (s === "running") return "warning";
  return "default";
});

// File columns
const fileColumns = computed<DataTableColumns<FileMiningInfo>>(() => [
  { type: "selection", options: ["all", "none"] },
  { title: "文件名", key: "file_name" },
  { title: "大小", key: "file_size", width: 100 },
  { title: "命令数", key: "command_count", width: 100 },
  {
    title: "挖掘状态", key: "mining_status", width: 120,
    render: (row) => {
      const statusMap: Record<string, string> = {
        unmined: "未挖掘", queued: "排队中", running: "挖掘中",
        completed: "已完成", failed: "失败",
      };
      const typeMap: Record<string, string> = {
        unmined: "default", queued: "warning", running: "info",
        completed: "success", failed: "error",
      };
      return h(NTag, { size: "small", type: (typeMap[row.mining_status] || "default") as any }, {
        default: () => statusMap[row.mining_status] || row.mining_status,
      });
    },
  },
]);

// Candidate columns
const candidateColumns = computed<DataTableColumns<Candidate>>(() => [
  { title: "Ref命令", key: "ref_command", width: 140 },
  { title: "Ref参数", key: "ref_param", width: 120 },
  { title: "Def命令", key: "def_command", width: 140 },
  { title: "Def参数", key: "def_param", width: 120 },
  {
    title: "置信度", key: "confidence", width: 100, sorter: (a, b) => a.confidence - b.confidence,
    render: (row) => row.confidence.toFixed(4),
  },
  {
    title: "状态", key: "status", width: 100,
    render: (row) => {
      const typeMap: Record<string, string> = {
        pending: "warning", graph: "success", non_graph: "info", rejected: "error",
        ready_for_review: "warning",
      };
      return h(NTag, { size: "small", type: (typeMap[row.status] || "default") as any }, {
        default: () => row.status,
      });
    },
  },
  {
    title: "操作", key: "actions", width: 280,
    render: (row) => {
      const btns: any[] = [];
      btns.push(h(NButton, { size: "tiny", quaternary: true, onClick: () => showEvidenceDrawer(row) }, { default: () => "详情" }));
      if (row.status === "pending" || row.status === "ready_for_review") {
        btns.push(h(NButton, { size: "tiny", type: "success", quaternary: true, onClick: () => handleAccept(row.id) }, { default: () => "接受" }));
        btns.push(h(NButton, { size: "tiny", type: "error", quaternary: true, onClick: () => handleReject(row.id) }, { default: () => "拒绝" }));
        btns.push(h(NButton, { size: "tiny", type: "warning", quaternary: true, onClick: () => openMarkNonGraph(row.id) }, { default: () => "非图谱" }));
      }
      if (row.status === "graph" || row.status === "non_graph") {
        btns.push(h(NButton, { size: "tiny", quaternary: true, onClick: () => handleRevert(row.id) }, { default: () => "回退" }));
      }
      return h(NSpace, { size: 4 }, { default: () => btns });
    },
  },
]);

// Edge columns
const edgeColumns = computed<DataTableColumns<GraphEdge>>(() => [
  { title: "Ref命令", key: "ref_command", width: 140 },
  { title: "Ref参数", key: "ref_param", width: 120 },
  { title: "Def命令", key: "def_command", width: 140 },
  { title: "Def参数", key: "def_param", width: 120 },
  {
    title: "置信度", key: "confidence", width: 100,
    render: (row) => row.confidence.toFixed(4),
  },
  { title: "来源", key: "source", width: 80 },
  {
    title: "状态", key: "status", width: 80,
    render: (row) => h(NTag, { size: "small", type: row.status === "active" ? "success" : "default" }, { default: () => row.status }),
  },
  { title: "确认人", key: "confirmed_by", width: 100 },
]);

// Methods
async function loadNeVersions() {
  try {
    neVersions.value = await fetchNeVersions();
  } catch (e: any) {
    message.error("加载网元版本失败: " + e.message);
  }
}

async function onNeVersionChange() {
  if (!selectedNeVersion.value) return;
  await Promise.all([loadFiles(), loadCandidates(), loadEdges()]);
}

async function loadFiles() {
  if (!selectedNeVersion.value) return;
  filesLoading.value = true;
  try {
    files.value = await fetchFiles(selectedNeVersion.value);
  } catch (e: any) {
    message.error("加载文件列表失败: " + e.message);
  } finally {
    filesLoading.value = false;
  }
}

async function loadCandidates() {
  candidatesLoading.value = true;
  try {
    const params: Record<string, any> = {};
    if (selectedNeVersion.value) params.ne_version_id = selectedNeVersion.value;
    if (candidateStatusFilter.value) params.status = candidateStatusFilter.value;
    candidates.value = await fetchCandidates(params);
  } catch (e: any) {
    message.error("加载候选列表失败: " + e.message);
  } finally {
    candidatesLoading.value = false;
  }
}

async function loadEdges() {
  if (!selectedNeVersion.value) return;
  edgesLoading.value = true;
  try {
    edges.value = await fetchGraphEdges({ ne_version_id: selectedNeVersion.value });
  } catch (e: any) {
    message.error("加载图谱边失败: " + e.message);
  } finally {
    edgesLoading.value = false;
  }
}

function onTabChange() {
  if (activeTab.value === "files") loadFiles();
  else if (activeTab.value === "candidates") loadCandidates();
  else if (activeTab.value === "edges") loadEdges();
}

async function handleStartMining() {
  if (!selectedNeVersion.value || selectedFiles.value.length === 0) return;
  try {
    const result = await startMining(selectedFiles.value);
    message.success(`挖掘任务已创建: #${result.job_id}`);
    // Poll job status
    pollJob(result.job_id);
  } catch (e: any) {
    message.error("创建挖掘任务失败: " + e.message);
  }
}

async function pollJob(jobId: number) {
  const poll = async () => {
    try {
      const job = await fetchJob(jobId);
      currentJob.value = job;
      if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
        message.info(`任务 #${jobId} ${job.status}`);
        loadFiles();
        loadCandidates();
        loadEdges();
        return;
      }
      setTimeout(poll, 2000);
    } catch {
      // Stop polling on error
    }
  };
  poll();
}

async function handleAccept(id: number) {
  try {
    await acceptCandidate(id, "user");
    message.success("已接受");
    loadCandidates();
    loadEdges();
  } catch (e: any) {
    message.error("接受失败: " + e.message);
  }
}

async function handleReject(id: number) {
  try {
    await rejectCandidate(id, "user");
    message.success("已拒绝");
    loadCandidates();
  } catch (e: any) {
    message.error("拒绝失败: " + e.message);
  }
}

function openMarkNonGraph(id: number) {
  markNonGraphTarget.value = id;
  nonGraphReason.value = "";
  showMarkNonGraph.value = true;
}

async function confirmMarkNonGraph() {
  if (!markNonGraphTarget.value) return;
  try {
    await markNonGraph(markNonGraphTarget.value, nonGraphReason.value || "", "user");
    message.success("已标记为非图谱");
    showMarkNonGraph.value = false;
    loadCandidates();
  } catch (e: any) {
    message.error("标记失败: " + e.message);
  }
}

async function handleRevert(id: number) {
  try {
    await revertCandidate(id, "user");
    message.success("已回退");
    loadCandidates();
    loadEdges();
  } catch (e: any) {
    message.error("回退失败: " + e.message);
  }
}

function showEvidenceDrawer(candidate: Candidate) {
  selectedCandidate.value = candidate;
  showEvidence.value = true;
}

onMounted(() => {
  loadNeVersions();
});
</script>
