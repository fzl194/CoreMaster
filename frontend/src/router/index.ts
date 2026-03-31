import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "../layouts/MainLayout.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: MainLayout,
      children: [
        {
          path: "",
          name: "home",
          component: () => import("../views/HomeView.vue"),
        },
        {
          path: "plugins/mml-manager",
          name: "mml-manager",
          component: () => import("../views/plugins/MmlManager.vue"),
        },
      ],
    },
  ],
});

export default router;
