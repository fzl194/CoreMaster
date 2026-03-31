<template>
  <div class="mml-manager">
    <!-- ═══════════════════ Editor View ═══════════════════ -->
    <div v-if="editingFile" class="editor-view">
      <div class="editor-topbar">
        <n-button text @click="closeEditor" style="color: #94a3b8">
          <template #icon><n-icon><arrow-back-outline /></n-icon></template>
          返回
        </n-button>
        <span class="editor-filename">{{ editingFile.filename }}</span>
        <n-button type="primary" size="small" :loading="saving" @click="saveContent">
          保存
        </n-button>
      </div>
      <vue-monaco-editor
        v-model:value="editingFile.content"
        language="cpp"
        theme="vs-dark"
        :options="editorOptions"
        style="height: calc(100vh - 56px - 48px)"
      />
    </div>

    <!-- ═══════════════════ Main View ═══════════════════ -->
    <template v-else>
      <!-- Tabs -->
      <div class="tab-bar">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'files' }"
          @click="activeTab = 'files'"
        >文件管理</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'versions' }"
          @click="activeTab = 'versions'"
        >版本管理</button>
      </div>

      <!-- ──── Files Tab ──── -->
      <div v-if="activeTab === 'files'" class="tab-content">
        <div class="toolbar">
          <n-select
            v-model:value="fileFilter"
            :options="neVersionFilterOptions"
            placeholder="全部版本"
            clearable
            style="width: 260px"
            size="small"
          />
          <n-button type="primary" size="small" @click="showUploadModal = true">
            <template #icon><n-icon><cloud-upload-outline /></n-icon></template>
            上传文件
          </n-button>
        </div>

        <n-data-table
          :columns="fileColumns"
          :data="filteredFiles"
          :bordered="false"
          :row-key="(row: MmlFile) => row.id"
          size="small"
          class="dark-table"
        />

        <div v-if="filteredFiles.length === 0 && !filesLoading" class="empty-hint">
          <n-icon size="40" color="#334155"><document-text-outline /></n-icon>
          <p>暂无 MML 文件</p>
        </div>
      </div>

      <!-- ──── Versions Tab ──── -->
      <div v-if="activeTab === 'versions'" class="tab-content">
        <div class="toolbar">
          <n-button type="primary" size="small" @click="showAddVersionModal = true">
            <template #icon><n-icon><add-outline /></n-icon></template>
            新增版本
          </n-button>
        </div>

        <n-data-table
          :columns="versionColumns"
          :data="neVersions"
          :bordered="false"
          :row-key="(row: NeVersion) => row.id"
          size="small"
          class="dark-table"
        />
      </div>
    </template>

    <!-- ═══════════════════ Upload Modal ═══════════════════ -->
    <n-modal
      v-model:show="showUploadModal"
      preset="card"
      title="上传 MML 文件"
      style="width: 520px; max-width: 90vw"
      :mask-closable="false"
    >
      <n-form ref="uploadFormRef" label-placement="left" label-width="80">
        <n-form-item label="目标版本" required>
          <n-select
            v-model:value="uploadVersionId"
            :options="neVersionSelectOptions"
            placeholder="选择网元版本"
            size="small"
          />
        </n-form-item>
        <n-form-item label="文件">
          <n-upload
            ref="uploadRef"
            :default-upload="false"
            :max="20"
            multiple
            accept=".mml,.txt"
            @change="handleUploadChange"
          >
            <n-upload-dragger style="background: #1a1d27; border-color: #1e2028">
              <div style="padding: 20px 0; text-align: center; color: #64748b">
                <n-icon size="32"><cloud-upload-outline /></n-icon>
                <p style="margin-top: 8px">点击或拖拽文件到此处</p>
                <p style="font-size: 12px; color: #475569">支持 .mml .txt 文件，可多选</p>
              </div>
            </n-upload-dragger>
          </n-upload>
        </n-form-item>
        <div v-if="selectedFiles.length > 0" class="selected-files">
          <span class="selected-label">已选择 {{ selectedFiles.length }} 个文件</span>
        </div>
      </n-form>
      <template #action>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button size="small" @click="showUploadModal = false">取消</n-button>
          <n-button
            type="primary"
            size="small"
            :loading="uploading"
            :disabled="!uploadVersionId || selectedFiles.length === 0"
            @click="doUpload"
          >上传</n-button>
        </div>
      </template>
    </n-modal>

    <!-- ═══════════════════ Add Version Modal ═══════════════════ -->
    <n-modal
      v-model:show="showAddVersionModal"
      preset="card"
      title="新增网元版本"
      style="width: 440px; max-width: 90vw"
      :mask-closable="false"
    >
      <n-form ref="versionFormRef" label-placement="left" label-width="80">
        <n-form-item label="NE 类型" required>
          <n-input v-model:value="newVersion.ne_type" placeholder="例如: ENODEB" size="small" />
        </n-form-item>
        <n-form-item label="版本号" required>
          <n-input v-model:value="newVersion.version" placeholder="例如: V100R019C10" size="small" />
        </n-form-item>
        <n-form-item label="厂商">
          <n-input v-model:value="newVersion.vendor" placeholder="例如: Huawei (可选)" size="small" />
        </n-form-item>
      </n-form>
      <template #action>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button size="small" @click="showAddVersionModal = false">取消</n-button>
          <n-button
            type="primary"
            size="small"
            :loading="creatingVersion"
            :disabled="!newVersion.ne_type || !newVersion.version"
            @click="doCreateVersion"
          >创建</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from "vue";
import {
  NButton, NSelect, NDataTable, NModal, NForm, NFormItem, NInput,
  NUpload, NIcon, NPopconfirm, useMessage,
} from "naive-ui";
import type { DataTableColumns, UploadFileInfo } from "naive-ui";
import {
  DocumentTextOutline,
  CloudUploadOutline,
  AddOutline,
  DownloadOutline,
  CreateOutline,
  TrashOutline,
  ArrowBackOutline,
} from "@vicons/ionicons5";
import { VueMonacoEditor } from "@guolao/vue-monaco-editor";
import {
  fetchNeVersions,
  createNeVersion,
  deleteNeVersion,
  fetchFiles,
  getFileContent,
  updateFileContent,
  deleteFile,
  uploadFiles,
  getFileDownloadUrl,
  type NeVersion,
  type MmlFile,
} from "../../api/mml-manager";

const message = useMessage();

// ── State ───────────────────────────────────────────────────────────────────

const activeTab = ref<"files" | "versions">("files");
const neVersions = ref<NeVersion[]>([]);
const files = ref<MmlFile[]>([]);
const filesLoading = ref(false);
const fileFilter = ref<number | null>(null);

// Editor
const editingFile = ref<{ id: number; filename: string; content: string } | null>(null);
const saving = ref(false);

// Upload modal
const showUploadModal = ref(false);
const uploadVersionId = ref<number | null>(null);
const selectedFiles = ref<File[]>([]);
const uploading = ref(false);

// Add version modal
const showAddVersionModal = ref(false);
const newVersion = ref({ ne_type: "", version: "", vendor: "" });
const creatingVersion = ref(false);

// ── Editor options ──────────────────────────────────────────────────────────

const editorOptions = {
  minimap: { enabled: true },
  fontSize: 14,
  fontFamily: "'Fira Code', monospace",
  scrollBeyondLastLine: false,
  automaticLayout: true,
};

// ── Computed ────────────────────────────────────────────────────────────────

const neVersionFilterOptions = computed(() =>
  neVersions.value.map((v) => ({
    label: `${v.vendor || "—"} / ${v.ne_type} / ${v.version}`,
    value: v.id,
  })),
);

const neVersionSelectOptions = computed(() =>
  neVersions.value.map((v) => ({
    label: `${v.vendor || "—"} / ${v.ne_type} / ${v.version}`,
    value: v.id,
  })),
);

const filteredFiles = computed(() => {
  if (fileFilter.value === null) return files.value;
  return files.value.filter((f) => f.ne_version_id === fileFilter.value);
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ── Data loading ────────────────────────────────────────────────────────────

async function loadNeVersions() {
  try {
    neVersions.value = await fetchNeVersions();
  } catch {
    message.error("加载网元版本失败");
  }
}

async function loadFiles() {
  filesLoading.value = true;
  try {
    files.value = await fetchFiles();
  } catch {
    message.error("加载文件列表失败");
  } finally {
    filesLoading.value = false;
  }
}

// ── File Columns ────────────────────────────────────────────────────────────

const fileColumns = computed<DataTableColumns<MmlFile>>(() => [
  {
    title: "文件名",
    key: "filename",
    ellipsis: { tooltip: true },
    render(row) {
      return h("span", { style: "font-family: 'Fira Code', monospace; color: #e2e8f0" }, row.filename);
    },
  },
  {
    title: "网元版本",
    key: "ne_version",
    render(row) {
      const label = `${row.vendor || "—"} / ${row.ne_type} / ${row.ne_version}`;
      return h("span", { style: "color: #94a3b8" }, label);
    },
  },
  {
    title: "大小",
    key: "file_size",
    width: 100,
    render(row) {
      return h("span", { style: "font-family: 'Fira Code', monospace; color: #94a3b8" }, formatSize(row.file_size));
    },
  },
  {
    title: "上传时间",
    key: "created_at",
    width: 150,
    render(row) {
      return h("span", { style: "color: #64748b" }, formatDate(row.created_at));
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 120,
    render(row) {
      return h("div", { style: "display: flex; gap: 4px" }, [
        h(
          NButton,
          { text: true, size: "tiny", quaternary: true, onClick: () => downloadFile(row) },
          { icon: () => h(NIcon, { size: 16, color: "#94a3b8" }, () => h(DownloadOutline)) },
        ),
        h(
          NButton,
          { text: true, size: "tiny", quaternary: true, onClick: () => openEditor(row), loading: editingBusyId.value === row.id },
          { icon: () => h(NIcon, { size: 16, color: "#94a3b8" }, () => h(CreateOutline)) },
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => doDeleteFile(row) },
          {
            trigger: () =>
              h(
                NButton,
                { text: true, size: "tiny", quaternary: true },
                { icon: () => h(NIcon, { size: 16, color: "#94a3b8" }, () => h(TrashOutline)) },
              ),
            default: () => `确定删除 ${row.filename}?`,
          },
        ),
      ]);
    },
  },
]);

const editingBusyId = ref<number | null>(null);

// ── Version Columns ─────────────────────────────────────────────────────────

const versionColumns = computed<DataTableColumns<NeVersion>>(() => [
  {
    title: "厂商",
    key: "vendor",
    width: 120,
    render(row) {
      return h("span", { style: "color: #e2e8f0" }, row.vendor || "—");
    },
  },
  {
    title: "NE 类型",
    key: "ne_type",
    render(row) {
      return h("span", { style: "font-family: 'Fira Code', monospace; color: #e2e8f0" }, row.ne_type);
    },
  },
  {
    title: "版本",
    key: "version",
    render(row) {
      return h("span", { style: "font-family: 'Fira Code', monospace; color: #94a3b8" }, row.version);
    },
  },
  {
    title: "文件数",
    key: "file_count",
    width: 80,
    render(row) {
      const count = files.value.filter((f) => f.ne_version_id === row.id).length;
      return h("span", { style: "font-family: 'Fira Code', monospace; color: #94a3b8" }, String(count));
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 80,
    render(row) {
      const hasFiles = files.value.some((f) => f.ne_version_id === row.id);
      if (hasFiles) {
        return h(
          NPopconfirm,
          {},
          {
            trigger: () =>
              h(
                NButton,
                { text: true, size: "tiny", quaternary: true },
                { icon: () => h(NIcon, { size: 16, color: "#94a3b8" }, () => h(TrashOutline)) },
              ),
            default: () => "该版本下仍有文件，请先删除所有关联文件。",
          },
        );
      }
      return h(
        NPopconfirm,
        { onPositiveClick: () => doDeleteVersion(row) },
        {
          trigger: () =>
            h(
              NButton,
              { text: true, size: "tiny", quaternary: true },
              { icon: () => h(NIcon, { size: 16, color: "#94a3b8" }, () => h(TrashOutline)) },
            ),
          default: () => `确定删除版本 ${row.ne_type} ${row.version}?`,
        },
      );
    },
  },
]);

// ── Actions ─────────────────────────────────────────────────────────────────

function downloadFile(row: MmlFile) {
  window.open(getFileDownloadUrl(row.id), "_blank");
}

async function openEditor(row: MmlFile) {
  editingBusyId.value = row.id;
  try {
    const content = await getFileContent(row.id);
    editingFile.value = { id: row.id, filename: row.filename, content };
  } catch {
    message.error("加载文件内容失败");
  } finally {
    editingBusyId.value = null;
  }
}

function closeEditor() {
  editingFile.value = null;
}

async function saveContent() {
  if (!editingFile.value) return;
  saving.value = true;
  try {
    await updateFileContent(editingFile.value.id, editingFile.value.content);
    message.success("保存成功");
  } catch {
    message.error("保存失败");
  } finally {
    saving.value = false;
  }
}

async function doDeleteFile(row: MmlFile) {
  try {
    await deleteFile(row.id);
    message.success("删除成功");
    await loadFiles();
  } catch {
    message.error("删除失败");
  }
}

async function doDeleteVersion(row: NeVersion) {
  try {
    await deleteNeVersion(row.id);
    message.success("版本已删除");
    await Promise.all([loadNeVersions(), loadFiles()]);
  } catch (err: any) {
    const msg = err?.response?.data?.detail || "删除版本失败";
    message.error(msg);
  }
}

// ── Upload ──────────────────────────────────────────────────────────────────

function handleUploadChange({ fileList }: { fileList: UploadFileInfo[] }) {
  selectedFiles.value = fileList
    .map((f) => f.file)
    .filter((f): f is File => f != null);
}

async function doUpload() {
  if (!uploadVersionId.value || selectedFiles.value.length === 0) return;
  uploading.value = true;
  try {
    const res = await uploadFiles(uploadVersionId.value, selectedFiles.value);
    message.success(`成功上传 ${res.count} 个文件`);
    showUploadModal.value = false;
    uploadVersionId.value = null;
    selectedFiles.value = [];
    await loadFiles();
  } catch {
    message.error("上传失败");
  } finally {
    uploading.value = false;
  }
}

// ── Create Version ──────────────────────────────────────────────────────────

async function doCreateVersion() {
  if (!newVersion.value.ne_type || !newVersion.value.version) return;
  creatingVersion.value = true;
  try {
    await createNeVersion({
      ne_type: newVersion.value.ne_type,
      version: newVersion.value.version,
      vendor: newVersion.value.vendor || undefined,
    });
    message.success("版本创建成功");
    showAddVersionModal.value = false;
    newVersion.value = { ne_type: "", version: "", vendor: "" };
    await loadNeVersions();
  } catch (err: any) {
    const msg = err?.response?.data?.detail || "创建版本失败";
    message.error(msg);
  } finally {
    creatingVersion.value = false;
  }
}

// ── Init ────────────────────────────────────────────────────────────────────

onMounted(() => {
  Promise.all([loadNeVersions(), loadFiles()]);
});
</script>

<style scoped>
.mml-manager {
  min-height: 100%;
}

/* ── Tab bar ──────────────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border-bottom: 1px solid #1e2028;
}
.tab-btn {
  padding: 8px 20px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #64748b;
  font-size: 14px;
  font-family: 'Fira Sans', sans-serif;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tab-btn.active {
  color: #2563EB;
  border-bottom-color: #2563EB;
}
.tab-btn:hover:not(.active) {
  color: #94a3b8;
}

/* ── Tab content ──────────────────────────────────────────────────────────── */
.tab-content {
  /* nothing extra needed */
}

/* ── Toolbar ──────────────────────────────────────────────────────────────── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

/* ── Empty hint ───────────────────────────────────────────────────────────── */
.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48px 0;
  color: #475569;
  font-size: 14px;
  gap: 8px;
}

/* ── Selected files ───────────────────────────────────────────────────────── */
.selected-files {
  margin-top: 4px;
}
.selected-label {
  font-size: 12px;
  color: #64748b;
  font-family: 'Fira Code', monospace;
}

/* ── Editor view ──────────────────────────────────────────────────────────── */
.editor-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  margin: -28px;
}
.editor-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 48px;
  padding: 0 20px;
  background: #16181f;
  border-bottom: 1px solid #1e2028;
  flex-shrink: 0;
}
.editor-filename {
  flex: 1;
  font-family: 'Fira Code', monospace;
  font-size: 14px;
  color: #e2e8f0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<style>
/* Global overrides for dark data table inside MmlManager */
.dark-table .n-data-table-th {
  background: #16181f !important;
  color: #64748b !important;
  border-color: #1e2028 !important;
  font-size: 12px;
  font-family: 'Fira Sans', sans-serif;
}
.dark-table .n-data-table-td {
  background: #13151a !important;
  border-color: #1e2028 !important;
}
.dark-table .n-data-table-tr:hover .n-data-table-td {
  background: #1a1d27 !important;
}
</style>
