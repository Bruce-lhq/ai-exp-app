import { expect, test, type Page, type Route } from "@playwright/test";

const schema = {
  fields: [
    { key: "lr", kind: "number", default: 0.01, has_default: true, help: "学习率" },
    { key: "optimizer", kind: "choice", default: "adamw", has_default: true, choices: ["adamw", "sgd"] },
    { key: "schedule", kind: "number_or_choice", default: "cosine", has_default: true, choices: ["cosine", "wsd"] },
    { key: "enabled", kind: "boolean", default: true, has_default: true },
  ],
  code: { kind: "working_tree", ref: null },
};

function validate(parameters: any) {
  const training = { lr: 0.01, optimizer: "adamw", schedule: "cosine", enabled: true, ...(parameters.training || parameters) };
  if (typeof training.lr === "string" && /[KMB]$/i.test(training.lr))
    training.lr = Number(training.lr.slice(0, -1)) * ({ k: 1e3, m: 1e6, b: 1e9 } as any)[training.lr.slice(-1).toLowerCase()];
  return { parameters: { training, runtime: parameters.runtime || { gpu_count: 8 } }, errors: [], warnings: [] };
}

async function baseRoutes(page: Page, handler: (route: Route, path: string) => Promise<boolean> | boolean) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await handler(route, path)) return;
    let body: any = [];
    if (path === "/api/connection") body = { connected: true };
    else if (path === "/api/runs") body = [];
    else if (path === "/api/queue") body = { runs: [], paused: false, revision: 0 };
    else if (path === "/api/history") body = [];
    else if (path === "/api/notifications") body = [];
    else if (path === "/api/analysis/series") body = { series: [], metrics: ["val_ppl"], warnings: [] };
    await route.fulfill({ json: body });
  });
}

test("parameter workspace small actions survive a complete edit/import/export cycle", async ({ page }) => {
  const errors: string[] = [], displayUpdates: any[] = [], downloads: string[] = [];
  let presets = [
    { id: "source", name: "源码默认值", project_id: "p", parameters: validate({ training: {}, runtime: { gpu_count: 8 } }).parameters },
    { id: "saved", name: "wonn", project_id: "p", parameters: validate({ training: { lr: 0.02 }, runtime: { gpu_count: 4 } }).parameters },
  ];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("download", (download) => downloads.push(download.suggestedFilename()));
  const answers = ["学习率备注", "优化", "导入组", "新参数组", "项目备注名", "feature/ref"];
  page.on("dialog", async (dialog) => {
    if (dialog.type() === "confirm") await dialog.accept();
    else await dialog.accept(answers.shift() || "测试值");
  });
  await baseRoutes(page, async (route, path) => {
    if (path === "/api/projects") { await route.fulfill({ json: [{ id: "p", name: "s1llt", is_default: true }] }); return true; }
    if (path === "/api/projects/p/schema") { await route.fulfill({ json: schema }); return true; }
    if (path === "/api/projects/p/inspect") { await route.fulfill({ json: { branches: ["main", "dev"] } }); return true; }
    if (path === "/api/projects/p/presets") {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON();
        const item = { id: `new-${presets.length}`, project_id: "p", ...body };
        presets.push(item); await route.fulfill({ json: item });
      } else await route.fulfill({ json: presets });
      return true;
    }
    if (path === "/api/projects/p/presets/import") {
      const body = route.request().postDataJSON();
      const item = { id: "imported", project_id: "p", name: body.name, parameters: validate(body.document.parameters || body.document).parameters };
      presets.push(item); await route.fulfill({ json: { ...item, warnings: [] } }); return true;
    }
    if (/\/api\/projects\/p\/presets\/[^/]+$/.test(path)) {
      const id = path.split("/").pop()!;
      if (route.request().method() === "DELETE") presets = presets.filter((p) => p.id !== id);
      else presets = presets.map((p) => p.id === id ? { ...p, ...route.request().postDataJSON() } : p);
      await route.fulfill({ json: { id, ...(route.request().postDataJSON() || {}) } }); return true;
    }
    if (path === "/api/projects/p/editor-initial") { await route.fulfill({ json: validate({ training: {}, runtime: { gpu_count: 8 } }).parameters }); return true; }
    if (path === "/api/projects/p/parameter-display") {
      if (route.request().method() === "PATCH") displayUpdates.push(route.request().postDataJSON());
      await route.fulfill({ json: displayUpdates.at(-1) || {} }); return true;
    }
    if (path === "/api/projects/p/parameters/validate") { await route.fulfill({ json: validate(route.request().postDataJSON().parameters) }); return true; }
    if (path === "/api/projects/p") { await route.fulfill({ json: { id: "p", name: route.request().postDataJSON()?.name || "s1llt" } }); return true; }
    return false;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "配置实验", exact: true }).click();
  await expect(page.getByLabel("lr", { exact: true })).toHaveValue("0.01");
  await page.getByRole("button", { name: "wonn", exact: true }).click();
  await expect(page.getByLabel("GPU 卡数")).toHaveValue("4");
  await page.getByLabel("lr", { exact: true }).fill("2K");
  await page.getByLabel("optimizer", { exact: true }).selectOption("sgd");
  await page.getByLabel("schedule", { exact: true }).fill("12");
  await page.getByLabel("enabled", { exact: true }).selectOption("false");
  await page.getByRole("button", { name: "保存到当前参数组" }).click();
  await expect(page.getByText("参数组已保存", { exact: true })).toBeVisible();
  await page.getByTitle("修改显示备注；留空恢复原名").first().click();
  await page.getByRole("button", { name: "＋分类", exact: true }).first().click();
  await page.getByTitle("标星置顶").first().click();
  await expect.poll(() => displayUpdates.length).toBe(3);
  await page.getByPlaceholder("搜索参数、备注或标签").fill("学习率备注");
  await expect(page.getByRole("button", { name: "学习率备注", exact: true })).toBeVisible();
  await page.getByPlaceholder("搜索参数、备注或标签").fill("");
  await page.getByLabel("只看差异").check();
  await expect(page.getByLabel("lr", { exact: true })).toBeVisible();
  await page.getByLabel("只看差异").uncheck();
  await page.getByLabel("GPU 卡数").fill("2");
  await page.getByTitle("导出 JSON").first().click();
  await page.getByRole("button", { name: "导出 Markdown 参数表" }).click();
  const chooser = page.locator('input[type="file"]');
  await chooser.setInputFiles("tests/fixtures/preset.json");
  await expect(page.getByRole("button", { name: "导入组", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "另存为新参数组" }).click();
  await expect(page.getByRole("button", { name: "新参数组", exact: true })).toBeVisible();
  const newlySaved = page.locator(".preset").filter({ hasText: "新参数组" });
  await newlySaved.getByRole("button", { name: "新参数组", exact: true }).click();
  await newlySaved.getByTitle("删除参数组").click();
  await expect(newlySaved).toHaveCount(0);
  await expect(page.getByRole("button", { name: "保存到当前参数组" })).toBeDisabled();
  await page.getByRole("button", { name: "还原源码默认值" }).click();
  await expect(page.getByLabel("lr", { exact: true })).toHaveValue("0.01");
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await page.getByRole("button", { name: "选择 commit / 标签", exact: true }).click();
  await expect(page.getByLabel("代码版本")).toHaveValue("feature/ref");
  expect(downloads).toEqual(expect.arrayContaining(["源码默认值.json", "参数组.md"]));
  expect(errors).toEqual([]);
});

test("history, notification, chart and table controls complete without a blank screen", async ({ page }) => {
  const errors: string[] = [], patched: any[] = [], parameterSaves: any[] = [];
  let history = [
    { id: "a", name: "基线备注", display_name: "raw-a", status: "completed", visibility: "visible", sync_status: "synced", source: { kind: "local", path: "/tmp/a" }, parameters: { training: { lr: 0.01, lambda: 0 }, runtime: { gpu_count: 8 } }, parameter_labels: { lr: "学习率" }, notes: "", tags: [] },
    { id: "b", name: "CA 备注", status: "stopped", visibility: "visible", sync_status: "synced", source: { kind: "local", path: "/tmp/b" }, parameters: { training: { lr: 0.02, lambda: 0.5 }, runtime: { gpu_count: 8 } }, parameter_labels: { lr: "学习率" }, notes: "旧备注", tags: ["ca"] },
  ];
  let templates = [{ id: "default", name: "默认模板", columns: [{ id: "name", kind: "name", title: "实验" }, { id: "lr", kind: "parameter", field: "lr", title: "学习率" }] }];
  page.on("pageerror", (error) => errors.push(error.message));
  const prompts = ["基线新名", "baseline, 对照", "新备注", "表格模板 2"];
  page.on("dialog", (dialog) => dialog.type() === "confirm" ? dialog.accept() : dialog.accept(prompts.shift() || "local"));
  await page.addInitScript(() => localStorage.setItem("analysis.ids", '["a","b"]'));
  await baseRoutes(page, async (route, path) => {
    if (path === "/api/history") { await route.fulfill({ json: history.filter((h: any) => h.visibility !== "removed") }); return true; }
    if (/\/api\/history\/[^/]+\/parameters$/.test(path)) { parameterSaves.push(route.request().postDataJSON()); await route.fulfill({ json: {} }); return true; }
    if (/\/api\/history\/[^/]+$/.test(path)) {
      const id = path.split("/").pop()!;
      if (route.request().method() === "DELETE") history = history.map((h) => h.id === id ? { ...h, visibility: "removed" } : h);
      else { const body = route.request().postDataJSON(); patched.push(body); history = history.map((h) => h.id === id ? { ...h, ...body, visibility: body.archived === true ? "archived" : body.archived === false ? "visible" : h.visibility } : h); }
      await route.fulfill({ json: history.find((h) => h.id === id) }); return true;
    }
    if (path.endsWith("/delete-preview")) { await route.fulfill({ json: { confirmation_token: "token", targets: ["/tmp/cache"] } }); return true; }
    if (path.endsWith("/delete-confirm")) { await route.fulfill({ json: { deleted: true } }); return true; }
    if (path === "/api/history/refresh") { await route.fulfill({ json: { warnings: [] } }); return true; }
    if (path === "/api/history/sync-running") { await route.fulfill({ json: { count: 2 } }); return true; }
    if (path === "/api/notifications") { await route.fulfill({ json: [{ id: "n", run_id: "run", title: "实验完成", body: "结果已缓存", read: false }] }); return true; }
    if (path === "/api/notifications/n/read") { await route.fulfill({ json: { read: true } }); return true; }
    if (path === "/api/runs") { await route.fulfill({ json: [{ id: "run", display_name: "运行备注名", status: "external_running", progress: "1.2B", remaining: "3h" }] }); return true; }
    if (path === "/api/runs/run/log") { await route.fulfill({ json: { text: "训练日志内容" } }); return true; }
    if (path === "/api/analysis/series") {
      const body = route.request().postDataJSON();
      await route.fulfill({ json: { series: (body.history_ids || []).map((id: string, index: number) => ({ id, name: id === "a" ? "基线备注" : id === "b" ? "CA 备注" : "运行备注名", points: [{ x: 1e9, y: 50 - index }, { x: 2e9, y: 40 - index }] })), metrics: ["val_ppl", "train_ppl", "R_min"], warnings: [] } }); return true;
    }
    if (path === "/api/templates") {
      if (route.request().method() === "POST") { const body = route.request().postDataJSON(); const t = { id: "custom", ...body }; templates.push(t); await route.fulfill({ json: t }); }
      else await route.fulfill({ json: templates });
      return true;
    }
    if (path.startsWith("/api/templates/")) { const body = route.request().postDataJSON(); templates = templates.map((t) => t.id === path.split("/").pop() ? { ...t, ...body } : t); await route.fulfill({ json: { id: path.split("/").pop(), ...body } }); return true; }
    if (path === "/api/analysis/table") {
      const body = route.request().postDataJSON();
      await route.fulfill({ json: { headers: body.columns.map((c: any) => c.title), rows: body.history_ids.map((id: string) => body.columns.map((c: any) => c.kind === "name" ? history.find((h) => h.id === id)?.name : c.kind === "parameter" ? (history.find((h) => h.id === id)?.parameters.training as Record<string, unknown>)[c.field] : c.kind === "notes" ? history.find((h) => h.id === id)?.notes : 42)), markdown: "| 实验 |\n| --- |\n| 基线备注 |", warnings: [] } }); return true;
    }
    return false;
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "运行监控" })).toBeVisible();
  await expect(page.getByText("运行备注名", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /运行备注名/ }).click();
  await expect(page.getByText("训练日志内容", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "实验通知" }).click();
  await page.getByRole("button", { name: /实验完成/ }).click();
  await expect(page.getByText("训练日志内容", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "历史管理", exact: true }).click();
  await page.getByRole("button", { name: "基线备注", exact: true }).click();
  await page.getByRole("button", { name: "＋添加标签", exact: true }).click();
  await page.getByRole("button", { name: "添加实验备注", exact: true }).click();
  await expect(page.getByRole("heading", { name: "基线新名" })).toBeVisible();
  await page.getByRole("button", { name: "全选历史" }).click();
  await expect(page.getByRole("button", { name: /导出所选 \(2\)/ })).toBeVisible();
  await page.getByPlaceholder("搜索实验名称、标签或备注").fill("baseline");
  await expect(page.getByRole("heading", { name: "基线新名" })).toBeVisible();
  await page.getByPlaceholder("搜索实验名称、标签或备注").fill("");
  await page.getByRole("button", { name: "归档隐藏" }).first().click();
  await page.getByLabel("显示已归档").check();
  await page.getByRole("button", { name: "恢复显示" }).click();
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await page.getByRole("button", { name: "拉取正在运行实验" }).click();

  await page.getByRole("button", { name: "画图与列表", exact: true }).click();
  await expect(page.getByRole("img", { name: "val_ppl 实验曲线" })).toBeVisible();
  await page.getByLabel("图标题", { exact: true }).fill("自定义标题");
  await page.getByRole("button", { name: "图表设置" }).click();
  await page.getByLabel("Y 轴标题").fill("Validation PPL");
  await page.getByLabel("指标", { exact: true }).selectOption("R_min");
  await page.getByRole("tab", { name: "列表", exact: true }).click();
  await page.getByLabel("Baseline").selectOption("a");
  await page.getByRole("button", { name: "编辑列与模板" }).click();
  await page.getByLabel("选择超参数列").selectOption("lambda");
  await page.getByRole("button", { name: "增加超参数列" }).click();
  await page.getByLabel("选择指标列").selectOption("R_min");
  await page.getByRole("button", { name: "增加指标与差值" }).click();
  await page.getByRole("button", { name: "备注列" }).click();
  await page.getByLabel("基线新名 学习率").fill("  任意字符串  ");
  await page.getByLabel("基线新名 学习率").press("Enter");
  await expect.poll(() => parameterSaves.at(-1)).toEqual({ field: "lr", value: "任意字符串" });
  await page.getByRole("button", { name: "另存新模板" }).click();
  await expect(page.getByText("表格模板已保存", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "复制 Markdown" }).click();
  await expect(page.getByText(/Markdown 已复制|自动复制不可用/)).toBeVisible();
  expect(patched).toEqual(expect.arrayContaining([{ name: "基线新名" }, { tags: ["baseline", "对照"] }, { notes: "新备注" }]));
  expect(errors).toEqual([]);
});

test("directory import, remove, permanent delete and damaged browser cache stay recoverable", async ({ page }) => {
  const errors: string[] = [], imports: any[] = [], confirmations: any[] = [];
  let history: any[] = [{ id: "local", name: "本地实验", status: "completed", visibility: "visible", sync_status: "synced", source: { kind: "local", path: "/tmp/source" }, parameters: { training: { lr: 1 } } }];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.type() === "prompt" ? dialog.accept("local") : dialog.accept());
  await page.addInitScript(() => {
    localStorage.setItem("analysis.ids", "broken json");
    localStorage.setItem("analysis.settings", "{");
    localStorage.setItem("analysis.appearance", "not-json");
  });
  await baseRoutes(page, async (route, path) => {
    if (path === "/api/history") { await route.fulfill({ json: history.filter((h) => h.visibility !== "removed") }); return true; }
    if (path === "/api/local/browse" || path === "/api/remote/browse") {
      const body = route.request().postDataJSON();
      await route.fulfill({ json: { path: body.path, entries: [{ name: "child", path: `${body.path.replace(/\/$/, "")}/child`, is_dir: true }] } }); return true;
    }
    if (path === "/api/history/import") {
      const body = route.request().postDataJSON(); imports.push(body);
      const item = { id: `import-${imports.length}`, name: body.path?.split("/").pop() || "同步实验", status: "imported", visibility: "visible", sync_status: "synced", source: typeof body.source === "object" ? body.source : { kind: body.source, path: body.path }, parameters: {} };
      history = [...history.filter((h) => h.source?.path !== item.source.path), item];
      await route.fulfill({ json: item }); return true;
    }
    if (path.endsWith("/delete-preview")) { await route.fulfill({ json: { confirmation_token: "safe-token", targets: ["/tmp/cache/local"] } }); return true; }
    if (path.endsWith("/delete-confirm")) {
      confirmations.push(route.request().postDataJSON());
      const id = path.split("/").at(-2); history = history.map((h) => h.id === id ? { ...h, visibility: "removed" } : h);
      await route.fulfill({ json: { deleted: true } }); return true;
    }
    if (/\/api\/history\/[^/]+$/.test(path) && route.request().method() === "DELETE") {
      const id = path.split("/").pop(); history = history.map((h) => h.id === id ? { ...h, visibility: "removed" } : h);
      await route.fulfill({ json: { visibility: "removed" } }); return true;
    }
    if (path === "/api/templates") { await route.fulfill({ json: [] }); return true; }
    return false;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "画图与列表", exact: true }).click();
  await expect(page.getByRole("heading", { name: "画图与列表" })).toBeVisible();
  await expect(page.getByText("选择实验，开始对比")).toBeVisible();

  await page.getByRole("button", { name: "历史管理", exact: true }).click();
  await page.getByRole("button", { name: "从本地导入" }).click();
  await expect(page.getByLabel("目录路径")).toHaveValue("/Users/your-user/gpu_downloads/");
  await page.getByLabel("目录路径").fill("/tmp/source-2");
  await page.getByRole("button", { name: "打开", exact: true }).click();
  await page.getByRole("button", { name: "选择此目录" }).click();
  await expect.poll(() => imports.at(-1)).toEqual({ source: "local", path: "/tmp/source-2", alias: "gpu" });

  await page.getByRole("button", { name: "从云端导入" }).click();
  await expect(page.getByLabel("目录路径")).toHaveValue("/your_exp/runs/");
  await page.getByRole("button", { name: "选择此目录" }).click();
  await expect.poll(() => imports.at(-1)).toEqual({ source: "remote", path: "/your_exp/runs/", alias: "gpu" });

  const original = page.locator(".history-card").filter({ hasText: "本地实验" });
  await original.getByRole("button", { name: "从历史移除" }).click();
  await expect(original).toHaveCount(0);
  const imported = page.locator(".history-card").filter({ hasText: "source-2" });
  await imported.getByTitle("永久删除缓存文件").click();
  await expect(page.getByRole("dialog", { name: "永久删除文件" })).toBeVisible();
  await page.getByRole("button", { name: "确认永久删除" }).click();
  await expect.poll(() => confirmations).toEqual([{ confirmation_token: "safe-token" }]);
  await expect(imported).toHaveCount(0);
  expect(errors).toEqual([]);
});
