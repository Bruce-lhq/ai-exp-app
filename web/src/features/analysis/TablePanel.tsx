import { useEffect, useState } from "react";
import { Copy, Download, Plus, Save, GripVertical } from "lucide-react";
import { api, download, items } from "../../app/api";
import { move } from "../parameters/values";
export type Column = {
  id: string;
  kind: string;
  field?: string;
  aggregate?: string;
  title: string;
  parent_id?: string;
  format?: any;
};
export function TablePanel({
  ids,
  history,
  notify,
}: {
  ids: string[];
  history: any[];
  notify: (s: string) => void;
}) {
  const [templates, setTemplates] = useState<any[]>([]),
    [template, setTemplate] = useState(""),
    [columns, setColumns] = useState<Column[]>([]),
    [baseline, setBaseline] = useState(""),
    [result, setResult] = useState<any>({
      headers: [],
      rows: [],
      markdown: "",
      warnings: [],
    }),
    [edit, setEdit] = useState(false),
    [drag, setDrag] = useState(0),
    [fallback, setFallback] = useState(false),
    [difference, setDifference] = useState(false),
    [parameterChoice, setParameterChoice] = useState("");
  const parameterFields = [...new Set(history.flatMap((h) => Object.keys(h.parameters?.training || h.parameters || {})))];
  const [rowOrder, setRowOrder] = useState<string[]>(ids), [rowDrag, setRowDrag] = useState(0);
  const orderedIds = baseline
    ? [baseline, ...rowOrder.filter((id) => id !== baseline)]
    : rowOrder;
  useEffect(() => {
    setRowOrder(ids);
  }, [JSON.stringify(ids)]);
  useEffect(() => {
    api("/api/templates")
      .then((x) => {
        const list = items(x);
        setTemplates(list);
        if (list[0]) {
          setTemplate(list[0].id);
          setColumns(list[0].columns);
        }
      })
      .catch((e) => notify(e.message));
  }, []);
  const effective = columns.filter(
    (c) =>
      !difference ||
      c.kind !== "parameter" ||
      new Set(
        history
          .filter((h) => ids.includes(h.id))
          .map((h) =>
            JSON.stringify(
              h.parameters?.training?.[c.field || ""] ??
                h.parameters?.[c.field || ""],
            ),
          ),
      ).size > 1,
  );
  useEffect(() => {
    let alive = true;
    if (!columns.length) return;
    api("/api/analysis/table", {
      history_ids: orderedIds,
      baseline_id: baseline || null,
      columns: effective,
    })
      .then((x) => {
        if (alive) setResult(x);
      })
      .catch((e) => notify(e.message));
    return () => {
      alive = false;
    };
  }, [JSON.stringify(orderedIds), baseline, JSON.stringify(effective)]);
  async function save(asNew: boolean) {
    try {
      const name = asNew
        ? prompt("新模板名称")
        : templates.find((t) => t.id === template)?.name;
      if (!name) return;
      const t = await api(
        asNew ? "/api/templates" : `/api/templates/${template}`,
        { name, columns },
        asNew ? "POST" : "PUT",
      );
      setTemplates(items(await api("/api/templates")));
      setTemplate(t.id || template);
      notify("表格模板已保存");
    } catch (e) {
      notify((e as Error).message);
    }
  }
  function update(id: string, change: Partial<Column>) {
    setColumns((cs) => cs.map((c) => (c.id === id ? { ...c, ...change } : c)));
  }
  function add(kind: string) {
    const field =
      kind === "metric"
        ? prompt("指标原始名称", "val_ppl")
        : null;
    if ((kind === "metric" || kind === "parameter") && !field) return;
    const id = crypto.randomUUID();
    const c: Column = {
      id,
      kind,
      field: field || undefined,
      aggregate: kind === "metric" ? "min" : undefined,
      title:
        field ||
        {
          notes: "备注",
          parameter_count: "参数量",
          parameter_delta: "相对 baseline 参数量",
        }[kind] ||
        kind,
    };
    setColumns((cs) => [
      ...cs,
      c,
      ...(kind === "metric"
        ? [
            {
              id: crypto.randomUUID(),
              kind: "metric_delta",
              parent_id: id,
              title: "△ vs baseline",
            },
          ]
        : []),
    ]);
  }
  function addParameter(field: string) {
    const owner = history.find((h) => h.parameter_labels?.[field] || h.parameters?.parameter_labels?.[field]);
    const title = owner?.parameter_labels?.[field] || owner?.parameters?.parameter_labels?.[field] || field;
    setColumns((cs) => [...cs, { id: crypto.randomUUID(), kind: "parameter", field, title }]);
  }
  return (
    <section className="panel table-panel">
      <div className="panel-heading">
        <div>
          <h3>实验列表</h3>
          <small className="muted">
            差值使用原始精度计算，列头改名不改变数据。
          </small>
        </div>
        <div className="row">
          <button
            disabled={!result.markdown}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(result.markdown);
                notify("Markdown 已复制");
              } catch {
                setFallback(true);
              }
            }}
          >
            <Copy size={14} />
            复制 Markdown
          </button>
          <button
            disabled={!result.markdown}
            onClick={() =>
              download(
                result.markdown,
                "实验对比.md",
                "text/markdown;charset=utf-8",
              )
            }
          >
            <Download size={14} />
            下载 .md
          </button>
        </div>
      </div>
      <div className="toolbar">
        <label>
          表格模板
          <select
            value={template}
            onChange={(e) => {
              setTemplate(e.target.value);
              setColumns(
                structuredClone(
                  templates.find((t) => t.id === e.target.value)?.columns || [],
                ),
              );
            }}
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Baseline
          <select
            value={baseline}
            onChange={(e) => {
              setBaseline(e.target.value);
              if (e.target.value) setRowOrder((current) => [e.target.value, ...current.filter((id) => id !== e.target.value)]);
            }}
          >
            <option value="">未选择</option>
            {history.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name || h.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={difference}
            onChange={(e) => setDifference(e.target.checked)}
          />
          超参数只看差异
        </label>
        <button onClick={() => setEdit(!edit)}>
          {edit ? "收起列设置" : "编辑列与模板"}
        </button>
      </div>
      {edit && (
        <div className="template-editor">
          {columns.map((c, i) => (
            <div
              className="column-editor"
              key={c.id}
              draggable
              onDragStart={() => setDrag(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => setColumns(move(columns, drag, i))}
            >
              <GripVertical size={14} />
              <label>
                列头
                <input
                  aria-label={`列头 ${c.field || c.kind}`}
                  value={c.title}
                  onChange={(e) => update(c.id, { title: e.target.value })}
                />
              </label>
              <small>{c.field || c.kind}</small>
              {c.kind === "metric" && (
                <select
                  aria-label="统计方式"
                  value={c.aggregate}
                  onChange={(e) => update(c.id, { aggregate: e.target.value })}
                >
                  <option value="min">min / best</option>
                  <option value="max">max</option>
                  <option value="final">final</option>
                </select>
              )}
              <select
                aria-label="数字格式"
                value={c.format?.type || "fixed"}
                onChange={(e) =>
                  update(c.id, {
                    format: { ...c.format, type: e.target.value },
                  })
                }
              >
                <option value="fixed">小数</option>
                <option value="scientific">科学计数</option>
                <option value="compact">K / M / B</option>
              </select>
              <input
                className="digits"
                aria-label="小数位数"
                type="number"
                min="0"
                max="12"
                value={c.format?.digits ?? 3}
                onChange={(e) =>
                  update(c.id, {
                    format: { ...c.format, digits: Number(e.target.value) },
                  })
                }
              />
              <button
                className="icon"
                aria-label="移除此列"
                onClick={() =>
                  setColumns((cs) =>
                    cs.filter((x) => x.id !== c.id && x.parent_id !== c.id),
                  )
                }
              >
                ×
              </button>
            </div>
          ))}
          <div className="toolbar">
            <select aria-label="选择超参数列" value={parameterChoice} onChange={(e) => { setParameterChoice(e.target.value); if (e.target.value) { addParameter(e.target.value); setParameterChoice(""); } }}>
              <option value="">选择超参数列</option>
              {parameterFields.map((field) => { const owner = history.find((h) => h.parameter_labels?.[field] || h.parameters?.parameter_labels?.[field]); return <option key={field} value={field}>{owner?.parameter_labels?.[field] || owner?.parameters?.parameter_labels?.[field] || field}</option>; })}
            </select>
            <button disabled={!parameterFields.length} onClick={() => parameterChoice && addParameter(parameterChoice)}>
              <Plus size={14} />
              增加超参数列
            </button>
            <button onClick={() => add("metric")}>指标与差值</button>
            <button onClick={() => add("notes")}>备注列</button>
            <button onClick={() => save(false)}>
              <Save size={14} />
              保存当前模板
            </button>
            <button onClick={() => save(true)}>另存新模板</button>
          </div>
        </div>
      )}
      {result.warnings?.length > 0 && (
        <p className="warning">
          {result.warnings.map((x: any) => x.message || x).join("；")}
        </p>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th aria-label="拖动排序" />
              {result.headers?.map((h: string, i: number) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows?.map((row: any[], i: number) => (
              <tr key={orderedIds[i] || i} draggable onDragStart={() => setRowDrag(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => setRowOrder(move(orderedIds, rowDrag, i))}>
                <td className="drag-cell"><GripVertical size={14} /></td>
                {row.map((cell: any, j: number) => (
                  <td key={j}>{cell ?? "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!ids.length && <p className="empty">勾选历史实验以生成对比表格。</p>}
      </div>
      {fallback && (
        <label>
          自动复制不可用，请选择并复制以下内容
          <textarea
            readOnly
            rows={8}
            value={result.markdown}
            onFocus={(e) => e.target.select()}
          />
        </label>
      )}
    </section>
  );
}
