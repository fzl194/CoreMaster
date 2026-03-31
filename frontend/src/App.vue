<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-notification-provider>
        <router-view />
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { darkTheme, type GlobalThemeOverrides } from "naive-ui";
import { NConfigProvider, NMessageProvider, NNotificationProvider } from "naive-ui";

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
  },
  Menu: {
    itemTextColorActive: "#2563EB",
    itemTextColorActiveHover: "#3B82F6",
    itemIconColorActive: "#2563EB",
    itemColorActive: "rgba(37, 99, 235, 0.08)",
    itemColorActiveHover: "rgba(37, 99, 235, 0.12)",
    itemTextColorChildActive: "#2563EB",
    itemIconColorChildActive: "#2563EB",
  },
  Card: {
    borderRadius: "12px",
  },
  Button: {
    borderRadiusMedium: "8px",
    borderRadiusSmall: "6px",
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
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
