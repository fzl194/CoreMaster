<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      :width="220"
      :collapsed-width="64"
      collapse-mode="width"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="logo">
        <span v-if="!collapsed">CoreMaster</span>
        <span v-else>CM</span>
      </div>
      <n-menu
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
        :value="activeKey"
        @update:value="handleMenuClick"
      />
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="height: 48px; padding: 0 20px; display: flex; align-items: center; justify-content: space-between;">
        <span style="font-weight: 500">{{ currentTitle }}</span>
      </n-layout-header>
      <n-layout-content style="padding: 20px">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from "vue";
import { useRouter, useRoute } from "vue-router";
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu } from "naive-ui";
import type { MenuOption } from "naive-ui";
import { fetchPlugins, type MenuItem } from "../api";
import {
  DocumentTextOutline,
  GitCompareOutline,
  ScanOutline,
  CreateOutline,
  CheckmarkCircleOutline,
} from "@vicons/ionicons5";

const router = useRouter();
const route = useRoute();
const collapsed = ref(false);
const menus = ref<MenuItem[]>([]);
const activeKey = ref("home");

const iconMap: Record<string, any> = {
  document: DocumentTextOutline,
  diff: GitCompareOutline,
  graph: ScanOutline,
  generate: CreateOutline,
  validator: CheckmarkCircleOutline,
};

const titleMap = computed(() => {
  const map: Record<string, string> = { home: "首页" };
  menus.value.forEach((m) => {
    map[m.path] = m.title;
  });
  return map;
});

const currentTitle = computed(() => {
  return titleMap.value[route.path] || route.path;
});

const menuOptions = computed<MenuOption[]>(() => {
  const coreItems: MenuOption[] = [
    {
      label: "首页",
      key: "home",
      icon: () => h(DocumentTextOutline),
    },
  ];

  const pluginItems: MenuOption[] = menus.value.map((m) => ({
    label: m.title,
    key: m.path,
    icon: () => h(iconMap[m.icon] || DocumentTextOutline),
  }));

  if (pluginItems.length > 0) {
    return [
      ...coreItems,
      { type: "divider", key: "d1" },
      ...pluginItems,
    ];
  }
  return coreItems;
});

function handleMenuClick(key: string) {
  if (key === "home") {
    router.push("/");
  } else {
    router.push(key);
  }
}

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    menus.value = res.menus;
  } catch (e) {
    console.error("Failed to load plugins:", e);
  }
});
</script>

<style scoped>
.logo {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: #18a058;
  border-bottom: 1px solid var(--n-border-color);
}
</style>
