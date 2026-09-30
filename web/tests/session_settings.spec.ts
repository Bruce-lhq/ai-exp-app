import { expect, test } from "@playwright/test";

test("plots and tables recover after a local service restart without losing history selection", async ({ page }) => {
  let expired = false, renewals = 0;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("analysis.ids", '["cached"]'));
  await page.route("**/", async (route) => {
    if (route.request().isNavigationRequest()) return route.continue();
    renewals++;
    expired = false;
    await route.fulfill({ contentType: "text/html", body: "<html></html>" });
  });
  await page.route("**/api/**", async (route) => {
    if (expired) return route.fulfill({ status: 403, json: { detail: "请从应用首页打开工作台" } });
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === "/api/settings/local") body = { configured: true, local_settings: {} };
    if (path === "/api/connection") body = { connected: false };
    if (path === "/api/queue") body = { runs: [], paused: false };
    if (path === "/api/history") body = [{ id: "cached", name: "缓存实验" }];
    if (path === "/api/templates") body = [{ id: "default", name: "默认模板", columns: [{ id: "name", kind: "name", title: "实验" }] }];
    if (path === "/api/analysis/series") body = { series: [{ id: "cached", name: "缓存实验", points: [{ x: 1e9, y: 42 }, { x: 2e9, y: 35 }] }], warnings: [] };
    if (path === "/api/analysis/table") body = { headers: ["实验"], rows: [["缓存实验"]], markdown: "|实验|", warnings: [] };
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  await expect(page.getByText("GPU 未连接", { exact: true })).toBeVisible();
  expired = true;
  await page.getByRole("button", { name: "画图与列表", exact: true }).click();
  await expect(page.getByRole("img", { name: "val_ppl 实验曲线" })).toBeVisible();
  await page.getByRole("tab", { name: "列表", exact: true }).click();
  await expect(page.getByRole("cell", { name: "缓存实验", exact: true })).toBeVisible();
  expect(renewals).toBeGreaterThan(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("analysis.ids") || "[]"))).toEqual(["cached"]);
  expect(errors).toEqual([]);
});

test("first setup can be deferred for offline analysis and reopened to save local settings", async ({ page }) => {
  let saved: any;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === "/api/queue") body = { runs: [], paused: false };
    if (path === "/api/analysis/series") body = { series: [], warnings: [] };
    if (path === "/api/settings/local") {
      if (route.request().method() === "PUT") saved = route.request().postDataJSON();
      body = { configured: !!saved, local_settings: saved || { ssh_alias: "gpu", remote_root: "~/ai-exp", remote_python: "python3", remote_agent: "~/ai-exp/agent.pyz", remote_projects_root: "/", remote_import_root: "/", local_import_root: "~/gpu_downloads" } };
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  await expect(page.getByRole("dialog", { name: "设置工作空间" })).toBeVisible();
  await page.getByRole("button", { name: "稍后设置，使用本地数据" }).click();
  await page.getByRole("button", { name: "画图与列表", exact: true }).click();
  await expect(page.getByRole("heading", { name: "画图与列表", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "工作空间设置", exact: true }).click();
  await page.getByLabel("云端实验目录", { exact: true }).fill(" /workspace/runs/ ");
  await page.getByLabel("云端数据目录", { exact: true }).fill(" /workspace/data ");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(saved.remote_runs_root).toBe("/workspace/runs/");
  expect(saved.remote_data_root).toBe("/workspace/data");
  await page.getByRole("button", { name: "工作空间设置", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "工作空间设置" })).toBeVisible();
  await expect(page.getByLabel("云端实验目录", { exact: true })).toHaveValue("/workspace/runs/");
});
