<template>
  <n-card title="CoreMaster">
    <n-space vertical>
      <n-text>核心网 MML 配置管理平台</n-text>
      <n-text depth="3">从左侧菜单选择功能模块</n-text>
      <n-divider />
      <n-h3>已加载插件</n-h3>
      <n-grid :cols="3" :x-gap="12" :y-gap="12">
        <n-gi v-for="plugin in plugins" :key="plugin.name">
          <n-card size="small" hoverable>
            <n-text>{{ plugin.name }}</n-text>
            <template #footer>
              <n-text depth="3">{{ plugin.description }}</n-text>
            </template>
          </n-card>
        </n-gi>
      </n-grid>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { NCard, NSpace, NText, NDivider, NH3, NGrid, NGi } from "naive-ui";
import { fetchPlugins, type PluginInfo } from "../api";

const plugins = ref<PluginInfo[]>([]);

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    plugins.value = res.plugins;
  } catch (e) {
    console.error(e);
  }
});
</script>
