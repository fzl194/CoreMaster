<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import type { GlobalThemeOverrides } from "naive-ui";
import { NConfigProvider, NMessageProvider } from "naive-ui";

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#2563EB",
    primaryColorHover: "#3B82F6",
    primaryColorPressed: "#1D4ED8",
    primaryColorSuppl: "#3B82F6",
    fontFamily: "'Fira Sans', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
    fontFamilyMono: "'Fira Code', 'Consolas', monospace",
    borderRadius: "8px",
    borderRadiusSmall: "6px",
    bodyColor: "#F0F4F8",
    cardColor: "#FFFFFF",
    modalColor: "#FFFFFF",
    popoverColor: "#FFFFFF",
    tableColor: "#FFFFFF",
    inputColor: "#FFFFFF",
    actionColor: "#F8FAFC",
    borderColor: "#E2E8F0",
    dividerColor: "#E2E8F0",
    textColor1: "#0F172A",
    textColor2: "#334155",
    textColor3: "#64748B",
  },
  Menu: {
    itemTextColorActive: "#2563EB",
    itemTextColorActiveHover: "#3B82F6",
    itemIconColorActive: "#2563EB",
    itemColorActive: "rgba(37, 99, 235, 0.08)",
    itemColorActiveHover: "rgba(37, 99, 235, 0.12)",
    itemTextColorChildActive: "#2563EB",
    itemIconColorChildActive: "#2563EB",
    itemTextColor: "#475569",
    itemTextColorHover: "#0F172A",
    itemIconColor: "#64748B",
    itemIconColorHover: "#334155",
  },
  Card: {
    borderRadius: "12px",
    color: "#FFFFFF",
    borderColor: "#E2E8F0",
  },
  Button: {
    borderRadiusMedium: "8px",
    borderRadiusSmall: "6px",
  },
  Tag: {
    borderRadius: "16px",
  },
  DataTable: {
    thColor: "#F8FAFC",
    thTextColor: "#475569",
    tdColor: "#FFFFFF",
    tdTextColor: "#334155",
    borderColor: "#E2E8F0",
    thColorHover: "#F1F5F9",
    tdColorHover: "#F8FAFC",
  },
  Tooltip: {
    color: "#0F172A",
    textColor: "#F8FAFC",
    borderRadius: "6px",
    fontSize: "13px",
  },
  Popover: {
    color: "#FFFFFF",
    textColor: "#334155",
    borderColor: "#E2E8F0",
    borderRadius: "8px",
  },
  Popconfirm: {
    color: "#FFFFFF",
    textColor: "#334155",
    borderColor: "#E2E8F0",
  },
};
</script>

<style>
/* Global reset */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  width: 100%;
  overflow: hidden;
}

body {
  font-family: 'Fira Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background: #F0F4F8;
}

/* Scrollbar styling - light tech theme */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(37, 99, 235, 0.15);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(37, 99, 235, 0.3);
}

/* Shared light data table overrides */
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
