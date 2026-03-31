<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      :width="240"
      :collapsed-width="68"
      collapse-mode="width"
      :collapsed="collapsed"
      show-trigger
      :native-scrollbar="false"
      @collapse="collapsed = true"
      @expand="collapsed = false"
      style="background: #0f1117"
    >
      <!-- Logo -->
      <div class="sidebar-logo" :class="{ collapsed }">
        <div class="logo-icon">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <rect x="2" y="2" width="24" height="24" rx="6" fill="#2563EB"/>
            <path d="M9 10L14 7L19 10V18L14 21L9 18V10Z" stroke="white" stroke-width="1.5" fill="none"/>
            <circle cx="14" cy="14" r="2.5" fill="white"/>
          </svg>
        </div>
        <transition name="fade">
          <span v-if="!collapsed" class="logo-text">CoreMaster</span>
        </transition>
      </div>

      <!-- Menu -->
      <div class="menu-wrapper">
        <div v-if="!collapsed" class="menu-section-label">导航</div>
        <n-menu
          :collapsed="collapsed"
          :collapsed-width="68"
          :collapsed-icon-size="20"
          :options="menuOptions"
          :value="activeKey"
          :indent="24"
          @update:value="handleMenuClick"
        />
      </div>

      <!-- Bottom status -->
      <div class="sidebar-bottom" :class="{ collapsed }">
        <div class="status-dot"></div>
        <transition name="fade">
          <span v-if="!collapsed" class="status-text">{{ statusText }}</span>
        </transition>
      </div>
    </n-layout-sider>

    <!-- Main content -->
    <n-layout style="background: #13151a">
      <!-- Header -->
      <n-layout-header bordered style="height: 56px; padding: 0 28px; display: flex; align-items: center; justify-content: space-between; background: #16181f; border-color: #1e2028;">
        <div style="display: flex; align-items: center; gap: 12px;">
          <n-breadcrumb v-if="breadcrumbItems.length > 0">
            <n-breadcrumb-item v-for="item in breadcrumbItems" :key="item.path">
              {{ item.label }}
            </n-breadcrumb-item>
          </n-breadcrumb>
          <span v-else class="header-title">{{ currentTitle }}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 16px;">
          <n-tag :bordered="false" type="success" size="small" round>
            {{ pluginCount }} 插件已加载
          </n-tag>
        </div>
      </n-layout-header>

      <!-- Content -->
      <n-layout-content
        :native-scrollbar="false"
        content-style="padding: 28px;"
        style="background: #13151a"
      >
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from "vue";
import { useRouter, useRoute } from "vue-router";
import {
  NLayout, NLayoutSider, NLayoutHeader, NLayoutContent,
  NMenu, NTag, NBreadcrumb, NBreadcrumbItem,
} from "naive-ui";
import type { MenuOption } from "naive-ui";
import { fetchPlugins, type MenuItem } from "../api";
import {
  HomeOutline,
  DocumentTextOutline,
  GitCompareOutline,
  ScanOutline,
  CreateOutline,
  CheckmarkCircleOutline,
  TerminalOutline,
} from "@vicons/ionicons5";

const router = useRouter();
const route = useRoute();
const collapsed = ref(false);
const menus = ref<MenuItem[]>([]);
const pluginCount = ref(0);
const statusText = ref("服务运行中");

const activeKey = computed(() => {
  if (route.path === "/") return "home";
  return route.path;
});

const iconMap: Record<string, any> = {
  home: HomeOutline,
  document: DocumentTextOutline,
  diff: GitCompareOutline,
  graph: ScanOutline,
  generate: CreateOutline,
  validator: CheckmarkCircleOutline,
};

const currentTitle = computed(() => {
  const titleMap: Record<string, string> = { "/": "首页" };
  menus.value.forEach((m) => { titleMap[m.path] = m.title; });
  return titleMap[route.path] || "CoreMaster";
});

const breadcrumbItems = computed(() => {
  if (route.path === "/") return [];
  const items = [{ label: "首页", path: "/" }];
  const matched = menus.value.find((m) => m.path === route.path);
  if (matched) {
    items.push({ label: matched.title, path: matched.path });
  }
  return items;
});

const menuOptions = computed<MenuOption[]>(() => {
  const coreItems: MenuOption[] = [
    {
      label: "首页",
      key: "home",
      icon: () => h(HomeOutline),
    },
  ];

  const pluginItems: MenuOption[] = menus.value.map((m) => ({
    label: m.title,
    key: m.path,
    icon: () => h(iconMap[m.icon] || TerminalOutline),
  }));

  if (pluginItems.length > 0) {
    return [
      ...coreItems,
      { type: "divider", key: "d1" },
      { label: "功能模块", key: "plugin-group", icon: () => h(TerminalOutline), children: pluginItems },
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
    pluginCount.value = res.plugins.length;
  } catch (e) {
    statusText.value = "服务未连接";
    console.error("Failed to load plugins:", e);
  }
});
</script>

<style scoped>
.sidebar-logo {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
  border-bottom: 1px solid #1e2028;
  transition: padding 0.3s ease;
}
.sidebar-logo.collapsed {
  padding: 0;
  justify-content: center;
}
.logo-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}
.logo-text {
  font-family: 'Fira Code', monospace;
  font-size: 16px;
  font-weight: 700;
  color: #e2e8f0;
  letter-spacing: -0.5px;
  white-space: nowrap;
}

.menu-wrapper {
  padding: 8px 0;
}
.menu-section-label {
  padding: 16px 24px 8px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #475569;
}

.sidebar-bottom {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 44px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 8px;
  border-top: 1px solid #1e2028;
  transition: padding 0.3s ease;
}
.sidebar-bottom.collapsed {
  padding: 0;
  justify-content: center;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.4);
  flex-shrink: 0;
}
.status-text {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.header-title {
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
