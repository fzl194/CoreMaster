<template>
  <div class="mml-manager">
    <!-- ═══════════════════ Editor View ═══════════════════ -->
    <div v-if="editingFile" class="editor-view">
      <div class="editor-topbar">
        <n-button text @click="closeEditor" style="color: #64748B">
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
        theme="vs"
        :options="editorOptions"
        style="height: calc(100vh - 56px - 48px)"
      />
    </div>

    <!-- ═══════════════════ Main View (File Manager) ═══════════════════ -->
    <template v-else>
      <!-- Toolbar: breadcrumb + action buttons -->
      <div class="toolbar">
        <div class="breadcrumb">
          <span
            class="breadcrumb-item"
            :class="{ clickable: true }"
            @click="navigateToBreadcrumb(-1)"
          >根目录</span>
          <template v-for="(seg, idx) in breadcrumbs" :key="seg.id">
            <span class="breadcrumb-sep">&gt;</span>
            <span
              class="breadcrumb-item clickable"
              @click="navigateToBreadcrumb(idx)"
            >{{ seg.name }}</span>
          </template>
        </div>
        <div class="toolbar-actions">
          <n-button size="small" @click="showNewFolderModal = true">
            <template #icon><n-icon><folder-outline /></n-icon></template>
            新建文件夹
          </n-button>
          <n-button type="primary" size="small" @click="showUploadModal = true">
            <template #icon><n-icon><cloud-upload-outline /></n-icon></template>
            上传文件
          </n-button>
        </div>
      </div>

      <!-- Data table -->
      <n-data-table
        v-if="displayEntries.length > 0"
        :columns="entryColumns"
        :data="displayEntries"
        :bordered="false"
        :row-key="(row: FileEntry) => row.id === -1 ? '__parent__' : String(row.id)"
        :row-props="entryRowProps"
        size="small"
        class="light-table"
      />

      <div v-if="displayEntries.length === 0 && !entriesLoading" class="empty-hint">
        <n-icon size="40" color="#94A3B8"><document-text-outline /></n-icon>
        <p>当前目录为空</p>
      </div>
    </template>

    <!-- ═══════════════════ New Folder Modal ═══════════════════ -->
    <n-modal
      v-model:show="showNewFolderModal"
      preset="card"
      title="新建文件夹"
      style="width: 400px; max-width: 90vw"
      :mask-closable="false"
    >
      <n-input
        v-model:value="newFolderName"
        placeholder="请输入文件夹名称"
        size="small"
        @keyup.enter="doCreateFolder"
      />
      <template #action>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button size="small" @click="showNewFolderModal = false">取消</n-button>
          <n-button
            type="primary"
            size="small"
            :disabled="!newFolderName.trim()"
            @click="doCreateFolder"
          >创建</n-button>
        </div>
      </template>
    </n-modal>

    <!-- ═══════════════════ Upload Modal ═══════════════════ -->
    <n-modal
      v-model:show="showUploadModal"
      preset="card"
      title="上传文件"
      style="width: 600px; max-width: 90vw"
      :mask-closable="false"
    >
      <n-form label-placement="left" label-width="100">
        <n-form-item label="统一网元版本">
          <n-select
            v-model:value="globalVersionId"
            :options="neVersionSelectOptions"
            placeholder="选择网元版本（应用到全部文件）"
            size="small"
            @update:value="onGlobalVersionChange"
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
            <n-upload-dragger style="background: #F8FAFC; border-color: #E2E8F0">
              <div style="padding: 20px 0; text-align: center; color: #64748B">
                <n-icon size="32"><cloud-upload-outline /></n-icon>
                <p style="margin-top: 8px">点击或拖拽文件到此处</p>
                <p style="font-size: 12px; color: #94A3B8">支持 .mml .txt 文件，可多选</p>
              </div>
            </n-upload-dragger>
          </n-upload>
        </n-form-item>
      </n-form>

      <!-- File list with per-file version selector -->
      <div v-if="uploadFileList.length > 0" class="upload-file-list">
        <div class="upload-file-header">
          <span>文件名</span>
          <span>网元版本</span>
          <span style="width: 60px; text-align: center">操作</span>
        </div>
        <div v-for="(item, idx) in uploadFileList" :key="idx" class="upload-file-row">
          <span class="upload-file-name">{{ item.file.name }}</span>
          <n-select
            v-model:value="item.neVersionId"
            :options="neVersionSelectOptions"
            placeholder="选择版本"
            size="tiny"
            style="min-width: 180px"
          />
          <n-button
            text
            size="tiny"
            quaternary
            @click="removeUploadFile(idx)"
            style="width: 60px; justify-content: center"
          >
            <template #icon><n-icon size="16" color="#EF4444"><trash-outline /></n-icon></template>
          </n-button>
        </div>
      </div>

      <template #action>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button size="small" @click="showUploadModal = false">取消</n-button>
          <n-button
            type="primary"
            size="small"
            :loading="uploading"
            :disabled="!canSubmitUpload"
            @click="doUpload"
          >上传</n-button>
        </div>
      </template>
    </n-modal>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick, h } from "vue";
import {
  NButton, NSelect, NDataTable, NModal, NForm, NFormItem,
  NUpload, NUploadDragger, NIcon, NPopconfirm, NInput, useMessage,
} from "naive-ui";
import type { DataTableColumns, UploadFileInfo } from "naive-ui";
import {
  DocumentTextOutline,
  FolderOutline,
  CloudUploadOutline,
  DownloadOutline,
  CreateOutline,
  TrashOutline,
  ArrowBackOutline,
} from "@vicons/ionicons5";
import { VueMonacoEditor } from "@guolao/vue-monaco-editor";
import {
  fetchNeVersions,
  fetchEntries,
  fetchEntryPath,
  createFolder,
  deleteEntry,
  getFileContent,
  updateFileContent,
  uploadFiles,
  getFileDownloadUrl,
  type NeVersion,
  type FileEntry,
  type PathSegment,
} from "../../api/mml-manager";

const message = useMessage();

// ── State ───────────────────────────────────────────────────────────────────

const neVersions = ref<NeVersion[]>([]);
const entries = ref<FileEntry[]>([]);
const entriesLoading = ref(false);

// Navigation
const currentParentId = ref<number | null>(null);
const breadcrumbs = ref<PathSegment[]>([]);

// Editor
const editingFile = ref<{ id: number; filename: string; content: string } | null>(null);
const saving = ref(false);

// New folder modal
const showNewFolderModal = ref(false);
const newFolderName = ref("");

// Upload modal
const showUploadModal = ref(false);
const globalVersionId = ref<number | null>(null);
const uploadFileList = ref<{ file: File; neVersionId: number | null }[]>([]);
const uploading = ref(false);
const uploadRef = ref<any>(null);

// Reset upload state when modal opens
watch(showUploadModal, (val) => {
  if (val) {
    globalVersionId.value = null;
    uploadFileList.value = [];
    nextTick(() => {
      uploadRef.value?.clear?.();
    });
  }
});

// ── Editor options ──────────────────────────────────────────────────────────

const editorOptions = {
  minimap: { enabled: true },
  fontSize: 14,
  fontFamily: "'Fira Code', monospace",
  scrollBeyondLastLine: false,
  automaticLayout: true,
};

// ── Computed ────────────────────────────────────────────────────────────────

const neVersionSelectOptions = computed(() =>
  neVersions.value.map((v) => ({
    label: `${v.vendor || "—"} / ${v.ne_type} / ${v.version}`,
    value: v.id,
  })),
);

/** Prepend a ".." row when not at root */
const displayEntries = computed(() => {
  if (currentParentId.value !== null) {
    const parentRow: FileEntry = {
      id: -1,
      parent_id: null,
      name: "..",
      type: "folder",
      ne_version_id: null,
      file_size: 0,
      description: null,
      created_at: "",
      updated_at: "",
      vendor: null,
      ne_type: null,
      version: null,
    };
    return [parentRow, ...entries.value];
  }
  return entries.value;
});

const canSubmitUpload = computed(() => {
  return (
    uploadFileList.value.length > 0 &&
    uploadFileList.value.every((item) => item.neVersionId !== null)
  );
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Data loading ────────────────────────────────────────────────────────────

async function loadNeVersions() {
  try {
    neVersions.value = await fetchNeVersions();
  } catch {
    message.error("加载网元版本失败");
  }
}

async function loadEntries() {
  entriesLoading.value = true;
  try {
    entries.value = await fetchEntries(currentParentId.value);
  } catch {
    message.error("加载目录内容失败");
  } finally {
    entriesLoading.value = false;
  }
}

// ── Navigation ──────────────────────────────────────────────────────────────

async function navigateInto(folder: FileEntry) {
  breadcrumbs.value.push({ id: folder.id, name: folder.name });
  currentParentId.value = folder.id;
  await loadEntries();
}

async function navigateUp() {
  breadcrumbs.value.pop();
  if (breadcrumbs.value.length === 0) {
    currentParentId.value = null;
  } else {
    currentParentId.value = breadcrumbs.value[breadcrumbs.value.length - 1].id;
  }
  await loadEntries();
}

async function navigateToBreadcrumb(index: number) {
  // index === -1 means root
  if (index === -1) {
    breadcrumbs.value = [];
    currentParentId.value = null;
  } else {
    breadcrumbs.value = breadcrumbs.value.slice(0, index + 1);
    currentParentId.value = breadcrumbs.value[breadcrumbs.value.length - 1].id;
  }
  await loadEntries();
}

// ── Table Columns ───────────────────────────────────────────────────────────

const editingBusyId = ref<number | null>(null);

const entryColumns = computed<DataTableColumns<FileEntry>>(() => [
  {
    title: "名称",
    key: "name",
    ellipsis: { tooltip: true },
    render(row) {
      const isParent = row.id === -1;
      const isFolder = isParent || row.type === "folder";
      const icon = isFolder ? FolderOutline : DocumentTextOutline;
      const color = isFolder ? "#2563EB" : "#0F172A";
      const label = isParent ? ".." : row.name;
      return h(
        "span",
        { style: `display: inline-flex; align-items: center; gap: 6px; font-family: 'Fira Code', monospace; color: ${color}; cursor: pointer` },
        [
          h(NIcon, { size: 18 }, () => h(icon)),
          h("span", null, label),
        ],
      );
    },
  },
  {
    title: "类型",
    key: "type",
    width: 90,
    render(row) {
      const isParent = row.id === -1;
      if (isParent) return h("span", { style: "color: #64748B" }, "文件夹");
      return row.type === "folder"
        ? h("span", { style: "color: #64748B" }, "文件夹")
        : h("span", { style: "color: #64748B" }, "文件");
    },
  },
  {
    title: "网元",
    key: "vendor",
    width: 120,
    render(row) {
      return h("span", { style: "color: #64748B" }, row.vendor ?? "—");
    },
  },
  {
    title: "版本",
    key: "version",
    width: 120,
    render(row) {
      return h("span", { style: "color: #64748B" }, row.version ?? "—");
    },
  },
  {
    title: "大小",
    key: "file_size",
    width: 100,
    render(row) {
      if (row.type === "folder") return h("span", { style: "color: #94A3B8" }, "—");
      return h("span", { style: "font-family: 'Fira Code', monospace; color: #64748B" }, formatSize(row.file_size));
    },
  },
  {
    title: "操作",
    key: "actions",
    width: 140,
    render(row) {
      const isParent = row.id === -1;
      if (isParent) return h("span", { style: "color: #94A3B8" }, "—");
      if (row.type === "folder") {
        return h(
          NPopconfirm,
          { onPositiveClick: () => doDeleteEntry(row) },
          {
            trigger: () =>
              h(
                NButton,
                { text: true, size: "tiny", quaternary: true },
                {
                  icon: () => h(NIcon, { size: 16, color: "#64748B" }, () => h(TrashOutline)),
                  default: () => "删除",
                },
              ),
            default: () => `确定删除文件夹「${row.name}」?`,
          },
        );
      }
      // File actions: download / edit / delete
      return h("div", { style: "display: flex; gap: 4px" }, [
        h(
          NButton,
          { text: true, size: "tiny", quaternary: true, onClick: () => downloadFile(row) },
          {
            icon: () => h(NIcon, { size: 16, color: "#64748B" }, () => h(DownloadOutline)),
          },
        ),
        h(
          NButton,
          { text: true, size: "tiny", quaternary: true, onClick: () => openEditor(row), loading: editingBusyId.value === row.id },
          {
            icon: () => h(NIcon, { size: 16, color: "#64748B" }, () => h(CreateOutline)),
          },
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => doDeleteEntry(row) },
          {
            trigger: () =>
              h(
                NButton,
                { text: true, size: "tiny", quaternary: true },
                { icon: () => h(NIcon, { size: 16, color: "#64748B" }, () => h(TrashOutline)) },
              ),
            default: () => `确定删除「${row.name}」?`,
          },
        ),
      ]);
    },
  },
]);

// ── Row double-click handling ───────────────────────────────────────────────

function handleRowDblClick(row: FileEntry) {
  const isParent = row.id === -1;
  if (isParent) {
    navigateUp();
  } else if (row.type === "folder") {
    navigateInto(row);
  } else {
    openEditor(row);
  }
}

// Patch: NDataTable does not have a native row-dblclick event in the same way.
// We need to use the `row-props` approach to attach dblclick handlers.
const entryRowProps = computed(() => (row: FileEntry) => ({
  ondblclick: () => handleRowDblClick(row),
  style: "cursor: pointer",
}));

// ── Actions ─────────────────────────────────────────────────────────────────

function downloadFile(row: FileEntry) {
  window.open(getFileDownloadUrl(row.id), "_blank");
}

async function openEditor(row: FileEntry) {
  editingBusyId.value = row.id;
  try {
    const content = await getFileContent(row.id);
    editingFile.value = { id: row.id, filename: row.name, content };
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

async function doDeleteEntry(row: FileEntry) {
  try {
    await deleteEntry(row.id);
    message.success("删除成功");
    await loadEntries();
  } catch {
    message.error("删除失败");
  }
}

// ── New Folder ──────────────────────────────────────────────────────────────

async function doCreateFolder() {
  const name = newFolderName.value.trim();
  if (!name) return;
  try {
    await createFolder(name, currentParentId.value);
    message.success("文件夹创建成功");
    showNewFolderModal.value = false;
    newFolderName.value = "";
    await loadEntries();
  } catch {
    message.error("创建文件夹失败");
  }
}

// ── Upload ──────────────────────────────────────────────────────────────────

function handleUploadChange({ fileList }: { fileList: UploadFileInfo[] }) {
  const files = fileList
    .map((f) => f.file)
    .filter((f): f is File => f != null);

  // Preserve existing neVersionId assignments for files that remain
  const existingMap = new Map<string, number | null>();
  for (const item of uploadFileList.value) {
    existingMap.set(item.file.name, item.neVersionId);
  }

  uploadFileList.value = files.map((file) => ({
    file,
    neVersionId: existingMap.get(file.name) ?? globalVersionId.value ?? null,
  }));
}

function removeUploadFile(index: number) {
  uploadFileList.value.splice(index, 1);
}

function onGlobalVersionChange(val: number | null) {
  if (val !== null) {
    for (const item of uploadFileList.value) {
      item.neVersionId = val;
    }
  }
}

async function doUpload() {
  if (!canSubmitUpload.value) return;
  uploading.value = true;
  try {
    const files = uploadFileList.value.map((item) => ({
      file: item.file,
      neVersionId: item.neVersionId!,
    }));
    await uploadFiles(currentParentId.value, files);
    message.success(`成功上传 ${files.length} 个文件`);
    showUploadModal.value = false;
    uploadFileList.value = [];
    globalVersionId.value = null;
    await loadEntries();
  } catch {
    message.error("上传失败");
  } finally {
    uploading.value = false;
  }
}

// ── Init ────────────────────────────────────────────────────────────────────

onMounted(() => {
  Promise.all([loadNeVersions(), loadEntries()]);
});
</script>

<style scoped>
.mml-manager {
  min-height: 100%;
}

/* ── Toolbar ──────────────────────────────────────────────────────────────── */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 12px;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: 'Fira Sans', sans-serif;
  font-size: 13px;
  color: #475569;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

.breadcrumb-item {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.breadcrumb-item.clickable {
  cursor: pointer;
  color: #2563EB;
}

.breadcrumb-item.clickable:hover {
  text-decoration: underline;
}

.breadcrumb-sep {
  color: #94A3B8;
  margin: 0 2px;
  flex-shrink: 0;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ── Empty hint ───────────────────────────────────────────────────────────── */
.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48px 0;
  color: #94A3B8;
  font-size: 14px;
  gap: 8px;
}

/* ── Upload file list ─────────────────────────────────────────────────────── */
.upload-file-list {
  margin-top: 8px;
  border: 1px solid #E2E8F0;
  border-radius: 6px;
  overflow: hidden;
}

.upload-file-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #F8FAFC;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  gap: 12px;
}

.upload-file-header span:first-child {
  flex: 1;
}

.upload-file-header span:nth-child(2) {
  min-width: 180px;
}

.upload-file-row {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-top: 1px solid #F1F5F9;
  gap: 12px;
}

.upload-file-name {
  flex: 1;
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  color: #0F172A;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  background: #FFFFFF;
  border-bottom: 1px solid #E2E8F0;
  flex-shrink: 0;
}
.editor-filename {
  flex: 1;
  font-family: 'Fira Code', monospace;
  font-size: 14px;
  color: #0F172A;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<style>
/* Global overrides for light data table */
.light-table .n-data-table-th {
  background: #F8FAFC !important;
  color: #475569 !important;
  border-color: #E2E8F0 !important;
  font-size: 12px;
  font-family: 'Fira Sans', sans-serif;
  font-weight: 600;
}
.light-table .n-data-table-td {
  background: #FFFFFF !important;
  border-color: #F1F5F9 !important;
}
.light-table .n-data-table-tr:hover .n-data-table-td {
  background: #F8FAFC !important;
}
</style>
