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
        {
          path: "plugins/db-manager",
          name: "db-manager",
          component: () => import("../views/plugins/DbManager.vue"),
        },
        {
          path: "plugins/dependency-mining",
          name: "dependency-mining",
          component: () => import("../views/plugins/DependencyMining.vue"),
        },
      ],
    },
  ],
});

export default router;
