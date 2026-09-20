"use strict";

const state = { meta: null, products: [], segments: [], labels: [],
  draft: { product_id: "", country: "CN", map: {} } };

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty */ }
  if (!res.ok) {
    const msg = typeof data === "object" && data ? (data.error || res.statusText) : res.statusText;
    throw Object.assign(new Error(typeof msg === "string" ? msg : "请求失败"), { data, status: res.status });
  }
  return data;
}

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtQty(n) { return (n || 0).toLocaleString("zh-CN"); }
function esc(s) { return String(s == null ? "" : s); }

function toast(msg, ms = 2600) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

// ---------- 弹窗 ----------
const modal = {
  open(title, bodyNode, onOk, okText) {
    document.getElementById("modal-title").textContent = title;
    const box = document.getElementById("modal-body");
    box.innerHTML = "";
    box.append(bodyNode);
    const ok = document.getElementById("modal-ok");
    ok.textContent = okText || "确认";
    ok.onclick = () => { if (onOk() !== false) modal.close(); };
    document.getElementById("modal-cancel").onclick = () => modal.close();
    document.getElementById("modal-close").onclick = () => modal.close();
    document.getElementById("modal").classList.remove("hidden");
  },
  close() { document.getElementById("modal").classList.add("hidden"); }
};

// ---------- 初始化 ----------
async function init() {
  state.meta = await api("GET", "/api/meta");
  await Promise.all([loadProducts(), loadSegments(), loadLabels()]);
  bindTabs();
  renderComposer();
  renderLabelsTable();
  renderSegments();
  renderProducts();
  renderAudit();

  document.getElementById("btn-reset").onclick = async () => {
    await api("GET", "/api/reset");
    await Promise.all([loadProducts(), loadSegments(), loadLabels()]);
    state.draft = { product_id: "", country: "CN", map: {} };
    renderComposer(); renderLabelsTable(); renderSegments(); renderProducts(); renderAudit();
    toast("演示数据已重置");
  };
  document.getElementById("btn-auto").onclick = autoPick;
  document.getElementById("btn-preview").onclick = () => doPreview(false);
  document.getElementById("btn-save-draft").onclick = () => saveLabel("draft");
  document.getElementById("btn-finalize").onclick = () => saveLabel("final");
  document.getElementById("seg-search").oninput = renderSegments;
  document.getElementById("seg-filter-type").onchange = renderSegments;
  document.getElementById("seg-filter-country").onchange = renderSegments;
  document.getElementById("btn-new-segment").onclick = openSegmentForm;
  document.getElementById("btn-new-product").onclick = openProductForm;
}

function bindTabs() {
  const typeSel = document.getElementById("seg-filter-type");
  state.meta.types.forEach(t => typeSel.append(h("option", { value: t }, state.meta.type_labels[t])));
  const cSel = document.getElementById("seg-filter-country");
  Object.entries(state.meta.markets).forEach(([k, v]) =>
    cSel.append(h("option", { value: k }, v.name)));
  document.querySelectorAll(".tab").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tabpanel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "audit") renderAudit();
    };
  });
}

async function loadProducts() { state.products = await api("GET", "/api/products"); }
async function loadSegments() { state.segments = await api("GET", "/api/segments"); }
async function loadLabels() { state.labels = await api("GET", "/api/labels"); }

// ---------- 拼版 ----------
function currentProduct() {
  return state.products.find(p => p.pid === state.draft.product_id) || state.products[0];
}

function renderComposer() {
  const pSel = document.getElementById("combo-product");
  pSel.innerHTML = "";
  state.products.forEach(p => pSel.append(h("option", { value: p.pid }, `${p.pid} ${p.name}（${p.spec}）`)));
  if (!state.draft.product_id && state.products[0]) state.draft.product_id = state.products[0].pid;
  pSel.value = state.draft.product_id;
  pSel.onchange = () => { state.draft.product_id = pSel.value; state.draft.map = {}; renderSlots(); };

  const cSel = document.getElementById("combo-country");
  cSel.innerHTML = "";
  Object.entries(state.meta.markets).forEach(([k, v]) =>
    cSel.append(h("option", { value: k }, v.name)));
  cSel.value = state.draft.country;
  const updateRule = () => {
    const rule = state.meta.markets[state.draft.country];
    document.getElementById("combo-rule").textContent = "市场规则：" + rule.allergen_note;
  };
  cSel.onchange = () => {
    state.draft.country = cSel.value; state.draft.map = {};
    updateRule(); renderSlots();
  };
  updateRule();
  renderSlots();
}

function slotVal(stype) {
  const v = state.draft.map[stype];
  return Array.isArray(v) ? v : (v ? [v] : []);
}
function setSlot(stype, sids) {
  if (MULTI.has(stype)) state.draft.map[stype] = sids;
  else state.draft.map[stype] = sids[0] || "";
  if (!state.draft.map[stype]) delete state.draft.map[stype];
}
const MULTI = new Set(["warning", "claim", "other"]);

async function renderSlots() {
  const product = currentProduct();
  const country = state.draft.country;
  const list = document.getElementById("slot-list");
  list.innerHTML = "";
  for (const stype of state.meta.types) {
    let cands = [];
    try {
      cands = await api("GET", `/api/labels/candidates?product=${product.pid}&country=${country}&type=${stype}`);
    } catch (e) { cands = []; }
    const selected = slotVal(stype);
    const multi = MULTI.has(stype);
    const select = h("select", { multiple: multi ? "" : null, size: multi ? Math.min(4, Math.max(2, cands.length)) : 1 });
    if (!multi && !selected.length) select.append(h("option", { value: "" }, "— 不使用 —"));
    cands.forEach(c => {
      const o = h("option", { value: c.sid, selected: selected.includes(c.sid) ? "" : null },
        `${c.sid} ${c.title} v${c.version}${c.status === "draft" ? "（未定稿）" : ""}`);
      select.append(o);
    });
    select.onchange = () => {
      const vals = Array.from(select.selectedOptions).map(o => o.value).filter(Boolean);
      setSlot(stype, vals);
      doPreview(true);
    };
    const pickedNote = selected.length
      ? h("span", { class: "cand-note" }, `已选 ${selected.length} 段`)
      : h("span", { class: "cand-note" }, cands.length ? `${cands.length} 个候选` : "无适用段落");
    const required = state.meta.required.includes(stype)
      ? h("span", { class: "req" }, "必备") : null;
    list.append(h("div", { class: "slot" },
      h("div", { class: "slot-head" }, h("span", { class: "t" }, state.meta.type_labels[stype], required), pickedNote),
      select));
  }
}

async function autoPick() {
  const product = currentProduct();
  const country = state.draft.country;
  const map = {};
  for (const stype of state.meta.types) {
    let cands = [];
    try {
      cands = await api("GET", `/api/labels/candidates?product=${product.pid}&country=${country}&type=${stype}`);
    } catch (e) { cands = []; }
    if (cands.length) {
      const best = cands[0];
      if (MULTI.has(stype)) map[stype] = [best.sid];
      else map[stype] = best.sid;
    }
  }
  state.draft.map = map;
  await renderSlots();
  doPreview(false);
}

let previewSilent = false;
async function doPreview(silent) {
  const product = currentProduct();
  const res = await api("POST", "/api/labels/preview", {
    product_id: product.pid, country: state.draft.country, segment_map: state.draft.map });
  renderPreviewResult(res, null);
  return res;
}

function renderPreviewResult(res, label) {
  const alerts = document.getElementById("preview-alerts");
  alerts.innerHTML = "";
  const sheet = document.getElementById("label-preview");
  sheet.innerHTML = "";
  const badge = document.getElementById("preview-badge");
  badge.innerHTML = "";
  const statusLine = document.getElementById("preview-status");

  if (res.blocks && res.blocks.length) {
    alerts.append(h("div", { class: "alert block" },
      h("b", {}, "⛔ 拼版被拦下，以下冲突解决前不能定稿："),
      h("ul", {}, res.blocks.map(b => h("li", {}, b)))));
  }
  if (res.warnings && res.warnings.length) {
    alerts.append(h("div", { class: "alert warn" },
      h("b", {}, "⚠ 需人工核对："),
      h("ul", {}, res.warnings.map(b => h("li", {}, b)))));
  }
  if (!res.blocks?.length && !res.warnings?.length && res.rows?.length) {
    alerts.append(h("div", { class: "alert ok" }, "✅ 无冲突，段落均已定稿，可以定稿拼版"));
  }

  if (label) {
    if (label.status === "draft") badge.append(h("span", { class: "tag draft" }, "草稿"));
    else badge.append(h("span", { class: "tag final" }, "已定稿"));
  }
  const hasDraft = (res.rows || []).some(r => r.status === "draft");
  if (hasDraft) badge.append(h("span", { class: "tag draft" }, "含未定稿段落"));

  for (const row of (res.rows || [])) {
    const isName = row.type === "product_name";
    let textHtml = esc(row.rendered);
    if (row.type === "ingredients" && state.draft.country === "EU") {
      textHtml = textHtml.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    }
    const textNode = h("p", { class: "lb-text" + (isName ? " lb-title" : "") });
    textNode.innerHTML = textHtml;
    if (row.status === "draft") textNode.append(h("span", { class: "draft-flag" }, "未定稿"));
    sheet.append(h("div", {},
      h("div", { class: "lb-type" }, row.type_label + " · " + row.sid + " v" + row.version),
      textNode));
  }
  const canFinal = res.rows?.length > 0 && !res.blocks?.length && !hasDraft;
  document.getElementById("btn-finalize").disabled = !canFinal;
  document.getElementById("btn-save-draft").disabled = !res.rows?.length;
  statusLine.textContent = canFinal ? "" : (hasDraft ? "含未定稿段落，仅可存草稿" :
    (res.blocks?.length ? "有阻断冲突" : ""));
}

async function saveLabel(mode) {
  const product = currentProduct();
  let res;
  try {
    res = await api("POST", "/api/labels", {
      product_id: product.pid, country: state.draft.country,
      segment_map: state.draft.map, reason: mode === "final" ? "定稿拼版" : "存草稿" });
  } catch (e) {
    if (e.status === 409 && e.data?.blocks) {
      renderPreviewResult({ blocks: e.data.blocks, warnings: e.data.warnings || [], rows: [] }, null);
      toast("有冲突，已拦下：" + e.data.blocks[0]);
    } else toast(e.message);
    return;
  }
  await loadLabels();
  renderLabelsTable();
  toast(mode === "final" ? `标签 ${res.lid} 已定稿` : `草稿 ${res.lid} 已保存`);
}

function renderLabelsTable() {
  const tb = document.querySelector("#label-table tbody");
  tb.innerHTML = "";
  for (const l of state.labels) {
    tb.append(h("tr", {},
      h("td", {}, h("b", {}, l.lid)),
      h("td", {}, l.product),
      h("td", {}, l.market),
      h("td", {}, h("span", { class: "tag " + l.status }, l.status === "final" ? "已定稿" : "草稿")),
      h("td", {}, l.blocks.length ? h("span", { class: "tag recall" }, l.blocks.length + " 处冲突")
        : (l.warnings.length ? h("span", { class: "tag patch" }, l.warnings.length + " 条提醒") : "—")),
      h("td", {}, fmtTime(l.updated_at)),
      h("td", {},
        h("button", { onclick: () => openLabelView(l) }, "整份预览"),
        l.status === "draft" ? " " : null,
        l.status === "draft"
          ? h("button", { onclick: () => finalizeLabel(l) }, "定稿") : null)));
  }
}

async function finalizeLabel(l) {
  try {
    const res = await api("POST", `/api/labels/${l.lid}/finalize`, { reason: "检查无误后定稿" });
    await loadLabels(); renderLabelsTable();
    toast(`标签 ${res.lid} 已定稿`);
  } catch (e) {
    const detail = e.data;
    let msg = e.message;
    if (detail?.missing) msg = "必备段落不全：" + detail.missing.join("；");
    if (detail?.blocks) msg = "冲突未解决：" + detail.blocks.join("；");
    if (detail?.drafts) msg = "仍有未定稿段落：" + detail.drafts.join("、");
    toast(msg, 4000);
  }
}

function openLabelView(l) {
  renderPreviewResult({ blocks: l.blocks, warnings: l.warnings, rows: l.rows }, l);
  // 切到拼版面的预览
  document.querySelector('.tab[data-tab="labels"]').click();
}

// ---------- 段落库 ----------
function renderSegments() {
  const q = document.getElementById("seg-search").value.trim().toLowerCase();
  const ft = document.getElementById("seg-filter-type").value;
  const fc = document.getElementById("seg-filter-country").value;
  const box = document.getElementById("segment-cards");
  box.innerHTML = "";
  const rows = state.segments.filter(s =>
    (!q || [s.sid, s.title, s.text].join(" ").toLowerCase().includes(q)) &&
    (!ft || s.type === ft) &&
    (!fc || !s.countries.length || s.countries.includes(fc)));
  for (const s of rows) {
    const tags = [
      h("span", { class: "tag type" }, state.meta.type_labels[s.type]),
      h("span", { class: "tag v" }, "v" + s.version),
      h("span", { class: "tag " + s.status }, s.status === "final" ? "已定稿" : "未定稿"),
    ];
    const scope = [];
    scope.push("市场：" + (s.countries.length ? s.countries.map(c => state.meta.markets[c]?.name || c).join("/") : "全部"));
    scope.push("品类：" + (s.categories.length ? s.categories.join("/") : "全部"));
    scope.push("规格：" + (s.specs.length ? s.specs.join("/") : "全部"));
    scope.push("指定产品：" + (s.products.length ? s.products.join("、") : "不限"));
    box.append(h("div", { class: "card" },
      h("h4", {}, h("span", {}, s.sid + " " + s.title), h("span", {}, ...tags)),
      h("div", { class: "meta" }, scope.join(" · ") + (s.mutex_group ? " · 互斥组：" + s.mutex_group : "")),
      h("div", { class: "text" }, s.text),
      h("div", { class: "actions" },
        h("button", { onclick: () => openRevise(s) }, "改这段（先看影响）"),
        h("button", { onclick: () => openSegmentVersions(s) }, "旧版本"),
        s.status === "draft"
          ? h("button", { onclick: () => markFinal(s) }, "标记定稿") : null)));
  }
  if (!rows.length) box.append(h("p", { class: "placeholder" }, "没有匹配的段落"));
}

async function markFinal(s) {
  try {
    await api("POST", `/api/segments/${s.sid}/revise`, {
      status: "final", confirmed: true, reason: "段落定稿", actor: "合规员" });
    await loadSegments(); renderSegments();
    toast(s.sid + " 已定稿");
  } catch (e) { toast(e.message); }
}

// ---------- 新建段落表单 ----------
function openSegmentForm() {
  const allP = state.products;
  const body = h("div", {},
    formGrid([
      fld("标题", input("f-title")),
      fld("类型", (() => {
        const sel = h("select", { id: "f-type" });
        state.meta.types.forEach(t => sel.append(h("option", { value: t }, state.meta.type_labels[t])));
        return sel;
      })()),
      fld("适用市场（可多选，空=全部）", (() => {
        const sel = multiSelect("f-countries", Object.entries(state.meta.markets).map(([k, v]) => [k, v.name]));
        return sel;
      })()),
      fld("适用产品（空=所有适用市场内产品）", (() => {
        const sel = multiSelect("f-products", allP.map(p => [p.pid, p.pid + " " + p.name]));
        return sel;
      })()),
      fld("互斥组（相同互斥组不可同版，留空不设）", input("f-mutex")),
      fld("语言", (() => {
        const sel = h("select", { id: "f-lang" });
        sel.append(h("option", { value: "zh" }, "中文"), h("option", { value: "en" }, "英文"));
        return sel;
      })())]),
    fld("正文 / 标准说法", (() => { const t = h("textarea", { id: "f-text" }); return t; })()),
    fld("状态", (() => {
      const sel = h("select", { id: "f-status" });
      sel.append(h("option", { value: "draft" }, "未定稿（拼版会标出来）"),
                 h("option", { value: "final" }, "已定稿"));
      return sel;
    })()),
    fld("变更/创建原因", input("f-reason", "示例：欧盟新法要求……")));
  modal.open("新建标准段落", body, async () => {
    const text = document.getElementById("f-text").value.trim();
    const title = document.getElementById("f-title").value.trim();
    if (!title || !text) { toast("标题和正文必填"); return false; }
    try {
      await api("POST", "/api/segments", {
        title, text,
        type: document.getElementById("f-type").value,
        countries: selectedValues("f-countries"),
        products: selectedValues("f-products"),
        mutex_group: document.getElementById("f-mutex").value.trim() || null,
        lang: document.getElementById("f-lang").value,
        status: document.getElementById("f-status").value,
        reason: document.getElementById("f-reason").value.trim() || "新建段落"
      });
      await loadSegments(); renderSegments();
      toast("段落已创建");
    } catch (e) { toast(e.message); return false; }
  }, "创建段落");
}

function input(id, ph) { return h("input", { type: "text", id, placeholder: ph || "" }); }
function fld(label, control) {
  return h("div", { class: "form-row" }, h("label", {}, label), control);
}
function formGrid(fields) { return h("div", { class: "form-grid" }, ...fields); }
function multiSelect(id, options) {
  const sel = h("select", { id, multiple: "", size: Math.min(5, options.length) });
  options.forEach(([v, label]) => sel.append(h("option", { value: v }, label)));
  return sel;
}
function selectedValues(id) {
  return Array.from(document.getElementById(id).selectedOptions).map(o => o.value);
}

// ---------- 修订向导 ----------
async function openRevise(seg) {
  let impact;
  try {
    impact = await api("GET", `/api/impact/${seg.sid}`);
  } catch (e) { toast(e.message); return; }

  const actionLabels = { recall: "必须召回", patch: "贴补丁覆盖", reprint: "下次改印" };
  const newText = h("textarea", { id: "rv-text" });
  newText.value = seg.text;
  const reason = input("rv-reason", "必填：例如「EU 1169 修订案要求……」");

  const body = h("div", {});
  body.append(h("div", { class: "alert warn" },
    h("b", {}, `《${seg.title}》（${state.meta.type_labels[seg.type]}，v${seg.version}）被 ${impact.totals.labels} 份已定稿标签引用，涉及 ${impact.totals.products} 个产品。`),
    document.createTextNode("动手前请核对在印/在途数量，并逐标签选择处置方式。")));

  body.append(h("div", { class: "impact-summary" },
    kpi("涉及标签", impact.totals.labels + " 份"),
    kpi("涉及产品", impact.totals.products + " 个"),
    kpi("已印数量", fmtQty(impact.totals.printed)),
    kpi("在途数量", fmtQty(impact.totals.intransit)),
    kpi("预估处置成本", "¥" + fmtQty(impact.totals.est_cost))));

  const decisionSelects = {};
  if (impact.items.length) {
    const trs = impact.items.map(i => {
      const sel = h("select", {});
      ["recall", "patch", "reprint"].forEach(a =>
        sel.append(h("option", { value: a, selected: a === i.action ? "" : null }, actionLabels[a])));
      sel.onchange = () => updateCost();
      decisionSelects[i.lid] = { sel, item: i };
      return h("tr", {},
        h("td", {}, i.lid), h("td", {}, i.product), h("td", {}, state.meta.markets[i.country].name),
        h("td", {}, fmtQty(i.printed_qty)), h("td", {}, fmtQty(i.intransit_qty)),
        h("td", {}, h("span", { class: "tag " + i.action }, actionLabels[i.action]),
          " ", document.createTextNode(i.action_reason)),
        h("td", {}, sel));
    });
    body.append(h("table", {},
      h("thead", {}, h("tr", {}, ["标签", "产品", "市场", "已印", "在途", "系统建议", "最终处置"].map(x => h("th", {}, x)))),
      h("tbody", {}, ...trs)));
  } else {
    body.append(h("p", { class: "placeholder" }, "当前没有任何已定稿标签引用该段落，修改不影响已印/在途包装。"));
  }

  const costLine = h("p", { class: "rule-note" }, "");
  const UNIT = { recall: 0.55, patch: 0.08, reprint: 0 };
  function updateCost() {
    let total = 0;
    for (const [lid, { sel, item }] of Object.entries(decisionSelects)) {
      total += (item.printed_qty + item.intransit_qty) * UNIT[sel.value];
    }
    costLine.textContent = "按所选处置预估成本：¥" + fmtQty(Math.round(total * 100) / 100) +
      "（召回 0.55/件 · 贴补 0.08/件 · 改印不计入处置成本）";
  }
  updateCost();
  body.append(costLine);

  const newStatus = h("select", { id: "rv-status" });
  newStatus.append(h("option", { value: "final" }, "改完仍定稿"),
                   h("option", { value: "draft" }, "改为未定稿（引用标签会退回草稿）"));
  body.append(formGrid([fld("新正文", newText), fld("修改后状态", newStatus)]));
  body.append(fld("修改原因（必填，会进入审计）", reason));

  const ack = h("input", { type: "checkbox", id: "rv-ack" });
  const ackLabel = h("label", { class: "choice", style: "margin:8px 0;font-size:13px" },
    ack, "我已核对受影响产品、在印/在途数量及召回成本");
  body.append(ackLabel);

  modal.open(`改段落：${seg.sid}`, body, null, "确认修改并通知各标签");
  const okBtn = document.getElementById("modal-ok");
  okBtn.disabled = true;
  ack.onchange = () => { okBtn.disabled = !ack.checked; };
  okBtn.onclick = async () => {
    if (!reason.value.trim()) { toast("必须填写修改原因"); return; }
    const decisions = {};
    for (const [lid, { sel }] of Object.entries(decisionSelects)) decisions[lid] = sel.value;
    try {
      const res = await api("POST", `/api/segments/${seg.sid}/revise`, {
        text: newText.value, status: newStatus.value,
        reason: reason.value.trim(), actor: "合规员",
        confirmed: true, decisions });
      modal.close();
      await loadSegments(); await loadLabels();
      renderSegments(); renderLabelsTable();
      toast(`${seg.sid} 已升至 v${res.segment.version}，同步 ${res.propagated.length} 份标签` +
        (res.demoted.length ? `，${res.demoted.length} 份退回草稿` : ""), 4000);
    } catch (e) { toast(e.message); }
  };
}

function kpi(label, value) {
  return h("div", { class: "kpi" }, label + " ", h("b", {}, value));
}

// ---------- 旧版本 ----------
async function openSegmentVersions(seg) {
  let data;
  try { data = await api("GET", `/api/segments/${seg.sid}`); } catch (e) { toast(e.message); return; }
  const body = h("div", {});
  body.append(h("div", { class: "alert ok" },
    `当前 v${data.segment.version}：${data.segment.text}`));
  if (!data.versions.length) {
    body.append(h("p", { class: "placeholder" }, "还没有历史版本。"));
  } else {
    data.versions.forEach(v => {
      body.append(h("div", { class: "audit-item" },
        h("div", { class: "a-head" }, `v${v.version}`, h("span", { class: "a-time" }, "归档于 " + fmtTime(v.archived_at) + " · " + v.actor)),
        h("div", {}, v.text),
        h("div", { class: "a-reason" }, "原因：" + (v.reason || "—"))));
    });
  }
  modal.open(`旧版本备查：${seg.sid}`, body, null, "关闭");
  document.getElementById("modal-ok").onclick = () => modal.close();
}

// ---------- 产品 ----------
function renderProducts() {
  const tb = document.querySelector("#product-table tbody");
  tb.innerHTML = "";
  for (const p of state.products) {
    tb.append(h("tr", {},
      h("td", {}, h("b", {}, p.pid)),
      h("td", {}, p.name),
      h("td", {}, p.category),
      h("td", {}, p.spec),
      h("td", {}, fmtQty(p.printed_qty)),
      h("td", {}, fmtQty(p.intransit_qty)),
      h("td", {}, "¥" + p.unit_cost)));
  }
}

function openProductForm() {
  const body = formGrid([
    fld("产品名称", input("p-name")),
    fld("品类", input("p-cat", "麦片")),
    fld("包装规格", input("p-spec", "500g 袋装")),
    fld("已印数量", Object.assign(h("input", { type: "number", id: "p-printed", value: "0" }), {})),
    fld("在途数量", h("input", { type: "number", id: "p-intransit", value: "0" })),
    fld("单标成本(元)", h("input", { type: "number", id: "p-cost", value: "0.1", step: "0.01" })),
  ]);
  modal.open("新建产品", body, async () => {
    const name = document.getElementById("p-name").value.trim();
    const cat = document.getElementById("p-cat").value.trim();
    const spec = document.getElementById("p-spec").value.trim();
    if (!name || !cat || !spec) { toast("名称/品类/规格必填"); return false; }
    try {
      await api("POST", "/api/products", {
        name, category: cat, spec,
        category_en: cat, spec_en: spec,
        printed_qty: Number(document.getElementById("p-printed").value || 0),
        intransit_qty: Number(document.getElementById("p-intransit").value || 0),
        unit_cost: Number(document.getElementById("p-cost").value || 0.1)
      });
      await loadProducts(); renderProducts(); renderComposer();
      toast("产品已创建");
    } catch (e) { toast(e.message); return false; }
  }, "创建");
}

// ---------- 审计 ----------
const ACTION_LABELS = {
  segment_create: "新建段落", segment_revise: "修订段落",
  label_create: "拼版标签", label_finalize: "标签定稿",
  segments_reviewed: "段落审核"
};
async function renderAudit() {
  const list = await api("GET", "/api/audit");
  const box = document.getElementById("audit-list");
  box.innerHTML = "";
  for (const a of list) {
    const node = h("div", { class: "audit-item" },
      h("div", { class: "a-head" },
        ACTION_LABELS[a.action] || a.action,
        h("span", { class: "a-time" }, fmtTime(a.ts) + " · " + a.actor +
          (a.sid ? " · " + a.sid : "") + (a.lid ? " · " + a.lid : ""))),
      h("div", { class: "a-reason" }, "原因：" + (a.reason || "—")));
    if (a.impact && a.impact.length) {
      const trs = a.impact.map(i => h("tr", {},
        h("td", {}, i.lid), h("td", {}, i.product), h("td", {}, i.country),
        h("td", {}, fmtQty(i.printed_qty)), h("td", {}, fmtQty(i.intransit_qty)),
        h("td", {}, h("span", { class: "tag " + (i.chosen || i.recommended) },
          ({ recall: "召回", patch: "贴补丁", reprint: "改印" })[i.chosen || i.recommended]))));
      node.append(h("table", {},
        h("thead", {}, h("tr", {}, ["标签", "产品", "市场", "已印", "在途", "处置"].map(x => h("th", {}, x)))),
        h("tbody", {}, ...trs)));
    }
    if (a.detail && a.detail.old_version) {
      node.append(h("div", { class: "a-reason" },
        `版本 v${a.detail.old_version} → v${a.detail.new_version}；同步标签：${(a.detail.propagated || []).join("、") || "无"}`));
    }
    box.append(node);
  }
}

init()
  .then(() => {
    const demo = new URLSearchParams(location.search).get("demo");
    if (demo === "autopick") setTimeout(() => autoPick(), 300);
    if (demo === "segments") {
      setTimeout(() => document.querySelector('.tab[data-tab="segments"]').click(), 300);
    }
    if (demo === "revise") {
      setTimeout(() => {
        document.querySelector('.tab[data-tab="segments"]').click();
        setTimeout(() => {
          const seg = state.segments.find(s => s.sid === "S-WARN-NUT-CN");
          openRevise(seg);
        }, 400);
      }, 300);
    }
    if (demo === "audit") {
      setTimeout(() => document.querySelector('.tab[data-tab="audit"]').click(), 300);
    }
    if (demo === "eu") {
      setTimeout(() => {
        document.getElementById("combo-country").value = "EU";
        document.getElementById("combo-country").dispatchEvent(new Event("change"));
        setTimeout(() => autoPick(), 300);
      }, 300);
    }
    if (demo === "conflict") {
      setTimeout(async () => {
        state.draft.map = {
          product_name: "S-PN-MUESLI", ingredients: "S-ING-MUESLI",
          storage: "S-STORE-DRY", manufacturer: "S-MFR-CN",
          claim: ["S-CLAIM-NONGMO", "S-CLAIM-GMO"],
          warning: ["S-WARN-NUT-CN", "S-WARN-NUT-CN-STRICT"]
        };
        await renderSlots();
        doPreview(false);
      }, 400);
    }
  })
  .catch(e => toast("初始化失败：" + e.message, 6000));
