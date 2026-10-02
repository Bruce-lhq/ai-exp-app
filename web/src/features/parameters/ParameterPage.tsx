import { useEffect, useState, useRef } from "react";
import {
  Star,
  GripVertical,
  FolderOpen,
  Play,
  Plus,
  Download,
  Upload,
  RotateCcw,
  Save,
} from "lucide-react";
import {
  api,
  download,
  items,
  type Field,
  type Parameters,
} from "../../app/api";
import { DirectoryPicker, Empty } from "../../app/ui";
import { displayNumber, move, parseValue, same } from "./values";
type Display = {
  order?: string[];
  aliases?: Record<string, string>;
  tags?: Record<string, string>;
  stars?: string[];
};
export function ParameterPage({
  notify,
  onRun,
  historical,
  onHistoricalLoaded,
}: {
  notify: (s: string) => void;
  onRun: () => void;
  historical?: Parameters | null;
  onHistoricalLoaded?: () => void;
}) {
  const [projects, setProjects] = useState<any[]>([]),
    [project, setProject] = useState(""),
    [schema, setSchema] = useState<Field[]>([]),
    [workersParameter, setWorkersParameter] = useState<string | undefined>(),
    [presets, setPresets] = useState<any[]>([]),
    [preset, setPreset] = useState(""),
    [params, setParams] = useState<Parameters>({
      training: {},
      runtime: { gpu_count: 1 },
    }),
    [display, setDisplay] = useState<Display>({}),
    [errors, setErrors] = useState<Record<string, string>>({}),
    [draft, setDraft] = useState<Record<string, string>>({}),
    [browse, setBrowse] = useState(false),
    [filter, setFilter] = useState(""),
    [difference, setDifference] = useState(false),
    [runName, setRunName] = useState(""),
    [busy, setBusy] = useState(false),
    [code, setCode] = useState(""),
    [refs, setRefs] = useState<string[]>([]),
    [drag, setDrag] = useState(""),
    [warning, setWarning] = useState("");
  const base = `/api/projects/${project}`;
  const [clean, setClean] = useState("");
  const [resume, setResume] = useState<Parameters['resume']>();
  const generation = useRef(0);
  const [loadedProject, setLoadedProject] = useState("");
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  const dirty = JSON.stringify(params) !== clean || Object.values(errors).some(Boolean);
  useEffect(() => {
    if (historical?.project_id && project && historical.project_id !== project) {
      setProject(historical.project_id);
      return;
    }
    if (!historical || !project || busy || loadedProject !== project) return;
    let alive = true;
    const training = historical.training || historical;
    const parameters = { training, runtime: historical.runtime || params.runtime };
    api(`${base}/parameters/validate`, { parameters }).then((result) => {
      if (!alive) return;
      const next = result.parameters;
      // Retain invalid imported values so they can be corrected instead of silently discarded.
      for (const error of result.errors || []) {
        if (error.field in training) next.training[error.field] = training[error.field];
      }
      setParams(next);
      // A flat args.json may contain an old checkpoint path, not a validated resume ticket.
      setResume(historical.training && historical.resume && typeof historical.resume === "object"
        && typeof historical.resume.ticket === "string" && typeof historical.resume.path === "string"
        ? historical.resume : undefined);
      if (historical.display_name) setRunName(historical.display_name);
      setDraft({});
      setErrors(Object.fromEntries((result.errors || []).map((error: any) => [error.field, error.message])));
      setWarning((result.warnings || []).map((w: any) => `${w.field ? w.field + '：' : ''}${w.message || w}`).join('；'));
      setPreset(""); setFilter(""); setDifference(false);
      onHistoricalLoaded?.();
      notify(result.errors?.length ? "历史参数已载入，请修正标出的不兼容值" : "历史实验参数已载入编辑区");
    }).catch((error) => { if (alive) notify(`参数载入失败：${error.message}`); });
    return () => { alive = false; };
  }, [historical, busy, schema, loadedProject, project]);
  useEffect(() => {
    let alive = true;
    setLoadError("");
    api("/api/projects")
      .then((d) => {
        if (!alive) return;
        const p = items(d);
        setProjects(p);
        setProject((current) => p.some((item) => item.id === current) ? current : p.find((item) => item.is_default)?.id || p[0]?.id || "");
      })
      .catch((e) => { if (alive) setLoadError(e.message); });
    return () => { alive = false; };
  }, [reload]);
  useEffect(() => {
    if (!project) return;
    setBusy(true);
    setResume(undefined);
    setLoadedProject("");
    setRefs([]);
    const requestGeneration = ++generation.current;
    let alive = true;
    (async () => {
      const s = await api(`${base}/schema`, { refresh: false });
      const [p, i, d] = await Promise.all([
        api(`${base}/presets`), api(`${base}/editor-initial`),
        api(`${base}/parameter-display`),
      ]);
      if (!alive || generation.current !== requestGeneration) return;
      setSchema(s.fields || []); setWorkersParameter(s.integration?.runtime?.workers_parameter); setPresets(items(p));
      const initial = {training:i.training || {}, runtime:i.runtime || {gpu_count:1}};
      setParams(initial); setClean(JSON.stringify(initial));
      setDisplay(d || {}); setDraft({}); setErrors({}); setPreset("");
      setLoadedProject(project);
      setCode(s.code?.ref || "");
      setWarning((s.warnings || []).map((x:any)=>x.message || x).join("；"));
    })().catch(e => {if(alive)setLoadError(e.message)}).finally(()=>{if(alive)setBusy(false)});
    api(`${base}/inspect`, {}, undefined, { background: true }).then((c) => {
      if (alive && generation.current === requestGeneration)
        setRefs((c.branches || c.refs || []).map((x: any) => typeof x === "string" ? x : x.name));
    }).catch(() => {});
    return () => {alive = false};
  }, [project, reload]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function validate() {
    const v = await api(`${base}/parameters/validate`, {
      parameters: params,
      code: { kind: code ? "ref" : "working_tree", ref: code || null },
    });
    if (v.errors?.length) {
      setErrors(
        Object.fromEntries(v.errors.map((x: any) => [x.field, x.message])),
      );
      throw new Error("请先修正参数错误");
    }
    setWarning((v.warnings || []).map((x: any) => x.message || x).join("；"));
    setParams(v.parameters);
    return v.parameters;
  }
  async function save(asNew: boolean) {
    const p = await validate();
    const name = asNew
      ? prompt("新参数组名称")
      : presets.find((x) => x.id === preset)?.name;
    if (!name) return;
    const saved = await api(
      asNew ? `${base}/presets` : `${base}/presets/${preset}`,
      { name, parameters: p },
      asNew ? "POST" : "PUT",
    );
    setPresets(items(await api(`${base}/presets`)));
    setPreset(saved.id); setClean(JSON.stringify(p)); setDraft({});
    notify("参数组已保存");
  }
  function load(p: any) {
    if (
      dirty &&
      !confirm("载入后将替换当前编辑区，是否继续？")
    )
      return;
    setParams(structuredClone(p.parameters));
    setResume(undefined);
    setClean(JSON.stringify(p.parameters));
    setPreset(p.id);
    setDraft({});
    setErrors({});
  }
  function changeDisplay(next: Display) {
    setDisplay(next);
    api(`${base}/parameter-display`, next, "PATCH").catch((e) =>
      notify(e.message),
    );
  }
  const sorted = [...schema]
    .sort((a, b) => {
      const star =
        Number(display.stars?.includes(b.key) || false) -
        Number(display.stars?.includes(a.key) || false);
      if (star) return star;
      const order = display.order || schema.map((f) => f.key);
      return order.indexOf(a.key) - order.indexOf(b.key);
    })
    .filter(
      (f) =>
        (!difference || !same(params.training[f.key], f.default)) &&
        `${f.key} ${display.aliases?.[f.key] || ""} ${display.tags?.[f.key] || ""}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
    );
  const invalid = loadedProject !== project || !!loadError || Object.values(errors).some(Boolean);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">CONFIGURE</span>
          <h1>配置实验</h1>
          <p>项目通过 workbench.project.json 定义启动命令、参数与指标文件。</p>
        </div>
        <button onClick={() => setBrowse(true)}>
          <Plus size={16} />
          添加云端项目
        </button>
      </div>
      {loadError && <div className="warning" role="alert">
        {loadError} <button onClick={() => { setLoadError(""); setReload((value) => value + 1); }}>重新加载配置</button>
      </div>}
      <section className="panel project-bar">
        <label>
          常用项目
          <select value={project} disabled={busy}
            onChange={(e) => {if(!dirty || confirm("切换项目将替换编辑区，是否继续？"))setProject(e.target.value)}}>
            <option value="">选择项目</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          代码版本
          <select
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              action(async () => {
                const s = await api(`${base}/schema`, {
                  code: {
                    kind: e.target.value ? "ref" : "working_tree",
                    ref: e.target.value || null,
                  },
                });
                setSchema(s.fields); setWorkersParameter(s.integration?.runtime?.workers_parameter);
                const v = await api(`${base}/parameters/validate`, { parameters: params });
                setWarning((v.warnings || []).map((w: any) => w.message || w).join("；"));
                setErrors(Object.fromEntries((v.errors || []).map((error: any) => [error.field, error.message])));
                if (!v.errors?.length) {
                  setParams(v.parameters);
                  setDraft({});
                }
              });
            }}
          >
            <option value="">当前工作目录（包含未提交修改）</option>
            {refs.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        {project && <button disabled={busy} onClick={()=>action(async()=>{
          const ref=prompt("输入分支、标签或 commit SHA",code); if(ref===null)return;
          const result=await api(`${base}/schema`,{code:{kind:ref?'ref':'working_tree',ref:ref||null}});
          setCode(ref); setSchema(result.fields); setWorkersParameter(result.integration?.runtime?.workers_parameter); if(ref&&!refs.includes(ref))setRefs([...refs,ref]);
          const v=await api(`${base}/parameters/validate`,{parameters:params});
          setWarning((v.warnings||[]).map((w:any)=>w.message||w).join('；'));
          setErrors(Object.fromEntries((v.errors||[]).map((e:any)=>[e.field,e.message])));
          if(!v.errors?.length){setParams(v.parameters);setDraft({})}
        })}>选择 commit / 标签</button>}
        {project && (
          <>
            <button
              onClick={() =>
                action(async () => {
                  const name = prompt(
                    "项目新名称",
                    projects.find((p) => p.id === project)?.name,
                  );
                  if (name) {
                    await api(base, { name }, "PATCH");
                    setProjects(items(await api("/api/projects")));
                  }
                })
              }
            >
              重命名
            </button>
            <button
              className="subtle"
              onClick={() =>
                action(async () => {
                  if (confirm("从常用区移除此项目？远端代码不会删除。")) {
                    await api(base, undefined, "DELETE");
                    const p = items(await api("/api/projects"));
                    setProjects(p);
                    setProject(p[0]?.id || "");
                  }
                })
              }
            >
              移除
            </button>
          </>
        )}
      </section>
      {!project ? (
        <Empty>
          <FolderOpen size={30} />
          <h3>添加你的第一个项目</h3>
          <p>浏览云端 GPU 目录，选择包含训练入口的代码目录。</p>
          <button className="primary" onClick={() => setBrowse(true)}>
            选择云端目录
          </button>
        </Empty>
      ) : (
        <>
          <div className="split">
            <aside className="panel preset-panel">
              <h3>参数组</h3>
              <p className="muted">载入到编辑区，原组保持不变。</p>
              {presets.map((p) => (
                <div
                  key={p.id}
                  className={`preset ${preset === p.id ? "selected" : ""}`}
                >
                  <button onClick={() => load(p)}>{p.name}</button>
                  <button
                    title="导出 JSON"
                    className="icon"
                    onClick={() =>
                      download(
                        JSON.stringify(p.parameters, null, 2),
                        `${p.name}.json`,
                        "application/json",
                      )
                    }
                  >
                    <Download size={14} />
                  </button>
                  <button
                    className="icon"
                    title="删除参数组"
                    onClick={() =>
                      action(async () => {
                        if (confirm(`删除参数组「${p.name}」？`)) {
                          await api(
                            `${base}/presets/${p.id}`,
                            undefined,
                            "DELETE",
                          );
                          if (preset === p.id) setPreset("");
                          setPresets(items(await api(`${base}/presets`)));
                        }
                      })
                    }
                  >
                    ×
                  </button>
                </div>
              ))}
              <label className="button file-button">
                <Upload size={15} />从 JSON 导入到应用
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file)
                      action(async () => {
                        const document = JSON.parse(await file.text());
                        const name = prompt(
                          "导入的参数组名称",
                          file.name.replace(/\.json$/, ""),
                        );
                        if (!name) return;
                        const r = await api(`${base}/presets/import`, {
                          name,
                          document,
                        });
                        setPresets(items(await api(`${base}/presets`)));
                        setWarning(
                          (r.warnings || [])
                            .map((x: any) => x.message || x)
                            .join("；"),
                        );
                        notify("参数组已导入应用，编辑区未改变");
                      });
                    e.target.value = "";
                  }}
                />
              </label>
              <button
                onClick={() => {
                  const rows = schema.map(
                    (f) =>
                      `| ${f.kind} | ${f.key} | ${JSON.stringify(params.training[f.key]) ?? "—"} |`,
                  );
                  download(
                    `| 类型 | 参数名称 | 默认值 |\n| --- | --- | --- |\n${rows.join("\n")}`,
                    "参数组.md",
                  );
                }}
              >
                <Download size={14} />
                导出 Markdown 参数表
              </button>
            </aside>
            <section className="panel editor">
              <div className="panel-heading">
                <div>
                  <h3>当前参数 {dirty && <span className="count">未保存修改</span>}</h3>
                  <span className="muted">
                    修改仅作用于编辑区 · 数值支持 K / M / B
                  </span>
                </div>
                <button
                  onClick={() => {
                    if (
                      confirm(
                        "将编辑区还原为所选源码的默认值？不会覆盖参数组。",
                      )
                    ) {
                      setResume(undefined);
                      setParams({
                        training: Object.fromEntries(
                          schema
                            .filter((f) => f.has_default)
                            .map((f) => [f.key, f.default]),
                        ),
                        runtime: params.runtime,
                      });
                      setDraft({});
                      setErrors({});
                      setPreset("");
                    }
                  }}
                >
                  <RotateCcw size={14} />
                  还原源码默认值
                </button>
              </div>
              <div className="toolbar">
                <input
                  placeholder="搜索参数、备注或标签"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <label className="check">
                  <input
                    type="checkbox"
                    checked={difference}
                    onChange={(e) => setDifference(e.target.checked)}
                  />
                  只看差异
                </label>

              </div>
              {warning && <p className="warning">{warning}</p>}
              {resume && <div className="toolbar">
                <label style={{ flex: 1 }}>resume（严格续跑）<input aria-label="resume" readOnly value={resume.path} style={{ width: '100%' }} /></label>
                <span>{typeof resume.tokens_seen === "number" ? `从 ${(resume.tokens_seen / 1e9).toFixed(3)}B 恢复` : typeof resume.step === "number" ? `从 step ${displayNumber(resume.step)} 恢复` : "从已验证的 checkpoint 恢复"}</span>
                <button onClick={() => setResume(undefined)}>取消续跑</button>
                <p className="muted">请核对代码项目。启动时校验原始训练参数与 GPU 数；结果写入新实验目录。</p>
              </div>}
              <div className="parameter-list">
                {!workersParameter && <label className="parameter">
                  <span>gpu_count · 使用 GPU 数</span>
                  <input
                    aria-label="GPU 卡数"
                    disabled={!!resume}
                    type="number"
                    min="1"
                    step="1"
                    value={params.runtime.gpu_count}
                    onChange={(e) => {
                      const value = Number(e.target.value);
                      if (Number.isSafeInteger(value) && value > 0)
                        setParams((p) => ({
                          ...p,
                          runtime: { gpu_count: value },
                        }));
                    }}
                  />
                </label>}
                {sorted.map((f) => (
                  <div
                    className={`parameter ${errors[f.key] ? "invalid" : ""}`}
                    key={f.key}
                    draggable
                    onDragStart={() => setDrag(f.key)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      const order = display.order || schema.map((x) => x.key);
                      changeDisplay({
                        ...display,
                        order: move(
                          order,
                          order.indexOf(drag),
                          order.indexOf(f.key),
                        ),
                      });
                    }}
                  >
                    <GripVertical size={15} className="grip" />
                    <button
                      className={`icon star ${display.stars?.includes(f.key) ? "active" : ""}`}
                      title="标星置顶"
                      onClick={() =>
                        changeDisplay({
                          ...display,
                          stars: display.stars?.includes(f.key)
                            ? display.stars.filter((x) => x !== f.key)
                            : [...(display.stars || []), f.key],
                        })
                      }
                    >
                      <Star size={15} />
                    </button>
                    <div className="parameter-name">
                      <button
                        title="修改显示备注；留空恢复原名"
                        onClick={() => {
                          const alias = prompt(
                            "显示备注（留空恢复原参数名）",
                            display.aliases?.[f.key] || "",
                          );
                          if (alias !== null)
                            changeDisplay({
                              ...display,
                              aliases: { ...display.aliases, [f.key]: alias },
                            });
                        }}
                      >
                        {display.aliases?.[f.key] || f.key}
                      </button>
                      <small title={f.help}>
                        {display.aliases?.[f.key] ? f.key : f.help || f.kind}
                      </small>
                    </div>
                    <div className="parameter-value">
                      {f.kind === "boolean" ? (
                        <select
                          aria-label={f.key}
                          value={String(params.training[f.key] ?? false)}
                          onChange={(e) =>
                            setParams((p) => ({
                              ...p,
                              training: {
                                ...p.training,
                                [f.key]: e.target.value === "true",
                              },
                            }))
                          }
                        >
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      ) : f.choices?.length && f.kind !== "number_or_choice" ? (
                        <select
                          aria-label={f.key}
                          value={String(params.training[f.key] ?? "")}
                          onChange={(e) =>
                            setParams((p) => ({
                              ...p,
                              training: {
                                ...p.training,
                                [f.key]: f.choices?.find(
                                  (x) => String(x) === e.target.value,
                                ),
                              },
                            }))
                          }
                        >
                          {f.choices.map((v) => (
                            <option key={displayNumber(v)} value={displayNumber(v)}>
                              {displayNumber(v)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <>
                          <input
                            aria-label={f.key}
                            list={
                              f.choices?.length ? `choices-${f.key}` : undefined
                            }
                            value={
                              draft[f.key] ??
                              displayNumber(params.training[f.key] ?? "")
                            }
                            onBlur={() => {
                              if (!errors[f.key]) setDraft((current) => { const next = { ...current }; delete next[f.key]; return next; });
                            }}
                            onChange={(e) => {
                              const text = e.target.value;
                              setDraft((d) => ({ ...d, [f.key]: text }));
                              try {
                                const value = parseValue(text, f);
                                setParams((p) => ({
                                  ...p,
                                  training: { ...p.training, [f.key]: value },
                                  runtime: f.key === workersParameter && typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? { gpu_count: value } : p.runtime,
                                }));
                                setErrors((p) => ({ ...p, [f.key]: "" }));
                              } catch (error) {
                                setErrors((p) => ({
                                  ...p,
                                  [f.key]: (error as Error).message,
                                }));
                              }
                            }}
                          />
                          {f.choices && (
                            <datalist id={`choices-${f.key}`}>
                              {f.choices.map((x) => (
                                <option value={typeof x === "number" ? displayNumber(x) : x} key={x} />
                              ))}
                            </datalist>
                          )}
                        </>
                      )}
                      {errors[f.key] && (
                        <small className="error">{errors[f.key]}</small>
                      )}
                    </div>
                    <button
                      className="tag"
                      onClick={() => {
                        const tag = prompt(
                          "自定义分类标签",
                          display.tags?.[f.key] || "",
                        );
                        if (tag !== null)
                          changeDisplay({
                            ...display,
                            tags: { ...display.tags, [f.key]: tag },
                          });
                      }}
                    >
                      {display.tags?.[f.key] || f.group || "＋分类"}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          </div>
          <section className="submit-bar">
            <div>
              <input
                aria-label="实验名称"
                placeholder="实验名称"
                value={runName}
                onChange={(e) => setRunName(e.target.value)}
              />
              <small>
                {code || "工作目录快照"} · {params.runtime.gpu_count} GPU ·{" "}
                {
                  schema.filter((f) => !same(params.training[f.key], f.default))
                    .length
                }{" "}
                项参数变化
              </small>
            </div>
            <button
              disabled={busy || invalid || !preset}
              onClick={() => action(() => save(false))}
            >
              <Save size={15} />
              保存到当前参数组
            </button>
            <button
              disabled={busy || invalid}
              onClick={() => action(() => save(true))}
            >
              另存为新参数组
            </button>
            {["queue", "start"].map((mode) => (
              <button
                className={mode === "start" ? "primary" : ""}
                key={mode}
                disabled={busy || invalid || !runName.trim()}
                onClick={() =>
                  action(async () => {
                    const parameters = await validate();
                    await api("/api/runs", {
                      project_id: project,
                      display_name: runName,
                      mode,
                      parameters,
                      resume_ticket: resume?.ticket,
                      code: {
                        kind: code ? "ref" : "working_tree",
                        ref: code || null,
                      },
                    });
                    notify(mode === "queue" ? "实验已加入队列" : "实验已提交");
                    onRun();
                  })
                }
              >
                {mode === "start" ? (
                  <>
                    <Play size={15} />
                    启动实验
                  </>
                ) : (
                  "加入队列"
                )}
              </button>
            ))}
          </section>
        </>
      )}
      {browse && (
        <DirectoryPicker
          onSelect={(path) =>
            action(async () => {
              const name = prompt(
                "项目名称",
                path.split("/").filter(Boolean).pop() || "训练项目",
              );
              if (!name) return;
              const p = await api("/api/projects", {
                name,
                remote_path: path,
              });
              setProjects(items(await api("/api/projects")));
              setProject(p.id);
              setBrowse(false);
            })
          }
          close={() => setBrowse(false)}
        />
      )}
    </>
  );
}
