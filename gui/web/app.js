/* watermarks-remover GUI — front end.
   Talks to the local server only; every action maps to a skill script call. */

(() => {
"use strict";

// ---------------------------------------------------------------- session

const url = new URL(location.href);
const urlToken = url.searchParams.get("t");
if (urlToken) {
  sessionStorage.setItem("wm-token", urlToken);
  history.replaceState({}, "", url.pathname);
}
const TOKEN = sessionStorage.getItem("wm-token") || "";

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-WM-Token": TOKEN },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({ error: `Server returned ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
  return data;
}

async function upload(file) {
  const res = await fetch("/api/upload", {
    method: "POST",
    headers: {
      "X-WM-Token": TOKEN,
      "X-WM-Filename": encodeURIComponent(file.name),
      "Content-Type": "application/octet-stream",
    },
    body: file,
  });
  const data = await res.json().catch(() => ({ error: `Server returned ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
  return data;
}

async function download(path, fallbackName) {
  const res = await fetch(path, { headers: { "X-WM-Token": TOKEN } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const disp = res.headers.get("Content-Disposition") || "";
  const match = /filename="([^"]+)"/.exec(disp);
  const href = URL.createObjectURL(blob);
  const a = el("a", { href, download: match ? match[1] : fallbackName || "download" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 4000);
}

// ---------------------------------------------------------------- helpers

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat(3)) {
    if (kid == null || kid === false || kid === "") continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function bytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

let toastTimer = null;
function toast(message, bad) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("bad", !!bad);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, bad ? 7000 : 3200);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard");
  } catch {
    const ta = el("textarea", { class: "offscreen" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    try { document.execCommand("copy"); toast("Copied to clipboard"); }
    catch { toast("Could not copy — select the text manually", true); }
    ta.remove();
  }
}

function verdictBand(state, title, sub) {
  return el("div", { class: `verdict ${state}` },
    el("p", { class: "verdict-title", text: title }),
    sub ? el("p", { class: "verdict-sub", text: sub }) : null);
}

function readout(pairs) {
  return el("div", { class: "readout" },
    pairs.filter(Boolean).map(([k, v]) =>
      el("div", { class: "readout-cell" },
        el("span", { class: "readout-k", text: k }),
        el("span", { class: "readout-v", text: String(v) }))));
}

function emptyState(title, sub, action) {
  return el("div", { class: "empty" },
    el("p", { class: "empty-title", text: title }),
    sub ? el("p", { class: "empty-sub", text: sub }) : null,
    action || null);
}

// Plain-language names for the mark categories, used by the legend and table.
const KIND_LABEL = {
  strip: "Invisible",
  bidi: "Text direction",
  tag_chars: "Tag characters",
  variation_selector: "Variation selector",
  zwj_family: "Zero-width",
  space: "Look-alike space",
  confusable: "Look-alike letter",
  other_cf: "Other invisible",
};

function revealNode(reveal) {
  const wrap = el("div", { class: "reveal-area" });
  if (!reveal || !reveal.segments.length) {
    wrap.append(el("span", { class: "muted", text: "Nothing to show." }));
    return wrap;
  }
  for (const seg of reveal.segments) {
    if (seg.t === "text") {
      wrap.append(document.createTextNode(seg.v));
    } else {
      wrap.append(el("span", {
        class: `mark k-${seg.kind}`,
        title: `${seg.cp} · ${seg.label}`,
        text: seg.v,
      }));
      if (seg.sub) wrap.append(document.createTextNode(seg.sub));
    }
  }
  if (reveal.truncated) {
    wrap.append(el("p", { class: "muted", text: "… preview truncated." }));
  }
  return wrap;
}

function legendNode(hits) {
  const kinds = [...new Set(hits.map((h) => h.kind))];
  if (!kinds.length) return null;
  return el("div", { class: "legend" },
    el("span", { class: "label", text: "Legend" }),
    kinds.map((k) => el("span", { class: "legend-item" },
      el("span", { class: `mark k-${k} legend-swatch`, text: "abc" }),
      el("span", { text: KIND_LABEL[k] || k }))));
}

function hitsTable(hits) {
  return el("table", { class: "hit-table" },
    el("thead", {}, el("tr", {},
      el("th", { text: "Code point" }),
      el("th", { text: "Count" }),
      el("th", { text: "Category" }),
      el("th", { text: "What it is" }))),
    el("tbody", {}, hits.map((h) => el("tr", {},
      el("td", { class: "hit-cp", text: h.codepoint }),
      el("td", { class: "hit-count", text: h.count }),
      el("td", {}, el("span", { class: `tag t-${h.kind}`, text: KIND_LABEL[h.kind] || h.kind })),
      el("td", {},
        el("div", { class: "hit-what", text: h.label }),
        h.help ? el("div", { class: "hit-help", text: h.help }) : null)))));
}

// ---------------------------------------------------------------- chrome

function showView(name) {
  $$(".rail-item").forEach((b) => {
    const on = b.dataset.view === name;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.dataset.view === name));
  $("#stage").scrollTop = 0;
  if (name === "setup") loadSetup();
  if (name === "guide") loadDocs();
}

$("#rail").addEventListener("click", (e) => {
  const item = e.target.closest(".rail-item");
  if (item) showView(item.dataset.view);
});

const savedTheme = localStorage.getItem("wm-theme");
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
$("#themeBtn").addEventListener("click", () => {
  const current = document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("wm-theme", next);
});

const keysModal = $("#keysModal");
const toggleKeys = (show) => { keysModal.hidden = !show; };
$("#keysBtn").addEventListener("click", () => toggleKeys(true));
$("#keysClose").addEventListener("click", () => toggleKeys(false));
keysModal.addEventListener("click", (e) => { if (e.target === keysModal) toggleKeys(false); });

const VIEW_ORDER = ["files", "text", "rewrite", "setup", "guide"];

document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")
    || document.activeElement?.isContentEditable;

  if (e.key === "Escape") { toggleKeys(false); return; }
  if (typing) return;

  if (e.key === "?" ) { toggleKeys(true); e.preventDefault(); return; }
  if (!e.ctrlKey && !e.metaKey && /^[1-5]$/.test(e.key)) {
    showView(VIEW_ORDER[Number(e.key) - 1]);
    e.preventDefault();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
    showView("files");
    $("#browseBtn").click();
    e.preventDefault();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    if (files.length) { $("#cleanAllBtn").click(); e.preventDefault(); }
    return;
  }
  if (e.key.toLowerCase() === "r" && $(".view.is-active")?.dataset.view === "text") {
    const next = textMode === "edit" ? "reveal" : "edit";
    $(`#textModeSeg .seg-btn[data-mode="${next}"]`).click();
    e.preventDefault();
  }
});

// ---------------------------------------------------------------- 01 files

const files = [];
let activeKey = null;
let keySeq = 0;
let filter = "all";
let scanQueue = Promise.resolve();

const opts = () => ({
  as: $("#optAs").value,
  aggressive: $("#optAggressive").checked,
  aggressive_homoglyphs: $("#optAggressiveClean").checked,
  nfkc: $("#optNfkc").checked,
  keep_non_ai_metadata: $("#optKeepMeta").checked,
  synthid: $("#optSynthid").checked,
  scrub_document_text: $("#optScrubDoc").checked,
  convert_nbsp: $("#optConvertNbsp").checked,
});

const visible = () => files.filter((f) =>
  filter === "all"
  || (filter === "found" && (f.status === "found" || f.status === "error"))
  || (filter === "clean" && (f.status === "clean" || f.status === "done")));

const CHIP = {
  busy: ["chip-busy", "scanning"],
  found: ["chip-found", "marks"],
  clean: ["chip-clean", "clean"],
  error: ["chip-error", "error"],
  done: ["chip-done", "cleaned"],
  working: ["chip-busy", "cleaning"],
};

function renderSummary() {
  const wrap = $("#summary");
  wrap.hidden = files.length === 0;
  if (!files.length) return;

  const marks = files.filter((f) => f.status === "found").length;
  const cleaned = files.filter((f) => f.status === "done").length;
  const errors = files.filter((f) => f.status === "error").length;
  const scanning = files.filter((f) => f.status === "busy" || f.status === "working").length;

  const stat = (n, cls, noun) =>
    el("span", { class: `stat ${cls}` }, el("b", { text: n }), ` ${noun}`);

  $("#summaryStats").replaceChildren(...[
    stat(files.length, "", files.length === 1 ? "file" : "files"),
    marks ? stat(marks, "stat-found", "with marks") : null,
    cleaned ? stat(cleaned, "stat-ok", "cleaned") : null,
    errors ? stat(errors, "stat-found", "failed") : null,
    scanning ? stat(scanning, "muted", "working") : null,
  ].filter(Boolean));

  $("#downloadAllBtn").hidden = !files.some((f) => f.clean && f.clean.download_id);
}

function renderList() {
  const list = $("#fileList");
  const rows = visible();
  $("#filesSplit").hidden = files.length === 0;
  renderSummary();

  if (!rows.length) {
    list.replaceChildren(el("li", { class: "list-empty", text: "No files match this filter." }));
    return;
  }

  list.replaceChildren(...rows.map((f) => {
    const [chipClass, chipText] = CHIP[f.status] || CHIP.busy;
    return el("li", {
      class: `file-row${f.key === activeKey ? " is-active" : ""}`,
      role: "option",
      "aria-selected": f.key === activeKey ? "true" : "false",
      "data-key": f.key,
      onclick: () => select(f.key),
    },
      el("div", { class: "file-name" },
        el("div", { class: "file-title", text: f.name }),
        el("span", { class: "file-sub", text: `${bytes(f.size)}${f.local ? " · on disk" : ""}` })),
      el("span", { class: `chip ${chipClass}`, text: chipText }));
  }));
}

function select(key) {
  activeKey = key;
  renderList();
  renderDetail();
}

function moveSelection(delta) {
  const rows = visible();
  if (!rows.length) return;
  const i = rows.findIndex((f) => f.key === activeKey);
  const next = rows[Math.max(0, Math.min(rows.length - 1, (i < 0 ? 0 : i + delta)))];
  if (next) select(next.key);
}

$("#fileList").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { moveSelection(1); e.preventDefault(); }
  else if (e.key === "ArrowUp") { moveSelection(-1); e.preventDefault(); }
  else if (e.key === "Enter") {
    const f = files.find((x) => x.key === activeKey);
    if (f) cleanOne(f);
    e.preventDefault();
  }
});

$("#filterSeg").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  filter = btn.dataset.filter;
  $$("#filterSeg .seg-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
  const rows = visible();
  if (!rows.some((f) => f.key === activeKey)) activeKey = rows.length ? rows[0].key : null;
  renderList();
  renderDetail();
});

function detailActions(f) {
  const row = el("div", { class: "detail-actions" });
  const cleanBtn = el("button", {
    class: "btn btn-primary",
    text: f.clean ? "Clean again" : "Clean this file",
    onclick: () => cleanOne(f, cleanBtn),
  });
  row.append(cleanBtn);

  if (f.clean && f.clean.download_id) {
    row.append(el("button", {
      class: "btn",
      text: "Download result",
      onclick: () => download(`/api/download?id=${encodeURIComponent(f.clean.download_id)}`,
        f.clean.output_name).catch((e) => toast(e.message, true)),
    }));
  }
  row.append(el("button", {
    class: "btn btn-quiet",
    text: "Remove",
    onclick: () => {
      const i = files.indexOf(f);
      if (i >= 0) files.splice(i, 1);
      if (activeKey === f.key) activeKey = files.length ? files[0].key : null;
      renderList();
      renderDetail();
    },
  }));
  return row;
}

// The remedy belongs next to the finding. Burying it in Advanced options is
// exactly how a document-text hit goes unnoticed.
function remedyNode(f, tr, inBody) {
  if (!inBody) return null;
  const done = f.cleanOpts || {};
  const spaces = tr.hits.some((h) => h.kind === "space");

  if (!done.scrub_document_text) {
    return el("div", { class: "inline-action" },
      el("p", { text: f.clean
        ? "Cleaning removed metadata only — these are still in the text."
        : "Cleaning removes metadata only. These live in the document text itself." }),
      el("div", { class: "inline-action-row" },
        el("button", {
          class: "btn btn-sm btn-primary",
          text: "Strip these from the document text",
          onclick: (e) => cleanOne(f, e.currentTarget, { scrub_document_text: true }),
        }),
        spaces ? el("label", { class: "check inline" },
          el("input", { type: "checkbox", id: `nbsp-${f.key}` }),
          el("span", { text: "also convert no-break spaces" })) : null));
  }

  if (spaces && !done.convert_nbsp) {
    return el("div", { class: "inline-action" },
      el("p", { text: "What is left are no-break spaces, kept because they are "
        + "usually deliberate typography. Converting them changes how the document wraps." }),
      el("div", { class: "inline-action-row" },
        el("button", {
          class: "btn btn-sm",
          text: "Convert them to plain spaces too",
          onclick: (e) => cleanOne(f, e.currentTarget,
            { scrub_document_text: true, convert_nbsp: true }),
        })));
  }
  return null;
}

function renderDetail() {
  const panel = $("#detail");
  const f = files.find((x) => x.key === activeKey);
  panel.replaceChildren();

  if (!f) {
    panel.append(emptyState("Nothing selected",
      files.length ? "Pick a file on the left." : "Drop a file above to scan it."));
    return;
  }

  panel.append(el("div", { class: "detail-head" },
    el("h2", { class: "detail-title", text: f.name }),
    el("p", { class: "detail-path", text: f.displayPath || f.name })));

  if (f.status === "busy" || f.status === "working") {
    panel.append(el("div", { class: "skeleton" },
      el("div", { class: "sk-band" }),
      el("div", { class: "sk-line" }),
      el("div", { class: "sk-line short" })));
    return;
  }
  if (f.status === "error") {
    panel.append(verdictBand("error", "Could not read this file", f.error));
    panel.append(detailActions(f));
    return;
  }

  const r = f.report || {};
  const kindWord = { text: "Plain text", image: "Image", container: "Document" }[r.kind] || r.kind;
  const tr = r.text_report;
  const inBody = r.text_source === "document body";

  if (f.clean) {
    const c = f.clean;
    panel.append(verdictBand(
      c.residual ? "error" : "clean",
      c.residual ? "Cleaned, but signals remain" : "Cleaned",
      c.saved_to_disk ? `Saved to ${c.output}` : "Ready to download."));
  } else {
    panel.append(r.clean
      ? verdictBand("clean", "Nothing found",
          "No provenance metadata and no hidden characters.")
      : verdictBand("found", "Marks found",
          "This file carries provenance metadata or hidden characters."));
  }

  panel.append(readout([
    ["Kind", kindWord],
    ["Format", r.format || "—"],
    ["Size", bytes(f.size)],
    r.kind !== "text" ? ["C2PA", r.has_c2pa ? "yes" : "no"] : null,
    r.kind !== "text" ? ["AI metadata", r.has_ai_metadata ? "yes" : "no"] : null,
    tr ? ["Hidden chars", tr.suspicious_total] : null,
  ]));

  if (f.clean && f.clean.actions && f.clean.actions.length) {
    panel.append(el("div", { class: "detail-section" },
      el("h3", { text: "What was done" }),
      el("ul", { class: "findings" }, f.clean.actions.map((a) => el("li", { text: a })))));
  }

  if (r.findings && r.findings.length) {
    panel.append(el("div", { class: "detail-section" },
      el("h3", { text: "Metadata findings" }),
      el("ul", { class: "findings" }, r.findings.map((x) => el("li", { text: x })))));
  }

  if (tr && tr.hits.length) {
    panel.append(el("div", { class: "detail-section" },
      el("h3", { text: inBody
        ? `Hidden characters inside the document text — ${tr.suspicious_total} total`
        : `Hidden characters — ${tr.suspicious_total} total` }),
      legendNode(tr.hits),
      hitsTable(tr.hits),
      remedyNode(f, tr, inBody)));
    panel.append(el("div", { class: "detail-section" },
      el("h3", { text: inBody ? "In context (document text)" : "In context" }),
      revealNode(tr.reveal)));
  }

  if (r.synthid) {
    panel.append(el("div", { class: "detail-section" },
      el("h3", { text: "SynthID score" }),
      el("pre", { class: "result-body", text: JSON.stringify(r.synthid, null, 2) })));
  }

  const toolNotes = [];
  for (const [name, info] of Object.entries(r.tools || {})) {
    if (!info || typeof info !== "object") continue;
    if (!info.available) { toolNotes.push(`${name}: not installed`); continue; }
    if (info.error) { toolNotes.push(`${name}: ${info.error}`); continue; }
    if (name === "c2patool") toolNotes.push(`c2patool: ${info.has_manifest ? "manifest found" : "no manifest"}`);
    if (name === "exiftool" && info.interesting_lines) {
      toolNotes.push(...info.interesting_lines.map((l) => `exiftool: ${l.trim()}`));
    }
  }
  if (toolNotes.length) {
    panel.append(el("details", { class: "detail-section fold" },
      el("summary", {}, el("h3", { text: "External tools" })),
      el("ul", { class: "findings plain" }, toolNotes.slice(0, 40).map((t) => el("li", { text: t })))));
  }

  panel.append(detailActions(f));
}

async function inspectOne(f) {
  f.status = "busy";
  renderList();
  if (f.key === activeKey) renderDetail();
  try {
    const o = opts();
    const report = await api("/api/inspect", {
      file: f.ref, aggressive: o.aggressive, as: o.as, synthid: o.synthid,
    });
    f.report = report;
    f.displayPath = report.display_path;
    f.local = report.local;
    f.status = report.clean ? "clean" : "found";
    f.error = null;
  } catch (e) {
    f.status = "error";
    f.error = e.message;
  }
  renderList();
  if (f.key === activeKey) renderDetail();
}

async function cleanOne(f, button, override) {
  if (f.status === "working") return;
  const o = { ...opts(), ...(override || {}) };
  const nbspBox = $(`#nbsp-${f.key}`);
  if (override && nbspBox && override.convert_nbsp == null) o.convert_nbsp = nbspBox.checked;
  const save = $("#optSave").value;

  const label = button ? button.textContent : null;
  if (button) { button.disabled = true; button.textContent = "Working…"; }
  const previous = f.status;
  f.status = "working";
  renderList();

  try {
    f.clean = await api("/api/clean", {
      file: f.ref,
      as: o.as,
      nfkc: o.nfkc,
      aggressive_homoglyphs: o.aggressive_homoglyphs,
      keep_non_ai_metadata: o.keep_non_ai_metadata,
      synthid: o.synthid,
      scrub_document_text: o.scrub_document_text,
      convert_nbsp: o.convert_nbsp,
      save: f.local ? save : "download",
    });
    f.cleanOpts = o;
    f.status = "done";
    if (f.clean.download_id) {
      const after = await api("/api/inspect", {
        file: { id: f.clean.download_id }, aggressive: o.aggressive, as: o.as,
      });
      after.display_path = f.displayPath;
      f.report = after;
    }
  } catch (e) {
    f.status = previous;
    toast(e.message, true);
  } finally {
    if (button) { button.disabled = false; if (label) button.textContent = label; }
  }
  renderList();
  renderDetail();
}

function addFiles(entries) {
  const fresh = entries.map((entry) => {
    const f = {
      key: ++keySeq,
      name: entry.name,
      size: entry.size,
      local: !!entry.local,
      displayPath: entry.path || entry.name,
      ref: { id: entry.id },
      status: "busy",
    };
    files.push(f);
    return f;
  });
  if (activeKey == null && fresh.length) activeKey = fresh[0].key;
  renderList();
  renderDetail();
  // Serialised so a 50-file drop cannot open 50 sockets at once.
  scanQueue = scanQueue.then(async () => {
    for (const f of fresh) await inspectOne(f);
  });
  return scanQueue;
}

const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => {
  e.preventDefault();
  dropzone.classList.add("is-over");
}));
["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => {
  e.preventDefault();
  if (ev === "dragleave" && dropzone.contains(e.relatedTarget)) return;
  dropzone.classList.remove("is-over");
}));
dropzone.addEventListener("drop", async (e) => {
  const dropped = Array.from(e.dataTransfer.files || []);
  if (!dropped.length) return;
  const added = [];
  for (const file of dropped) {
    try {
      added.push(await upload(file));
    } catch (err) {
      toast(`${file.name}: ${err.message}`, true);
    }
  }
  if (added.length) addFiles(added);
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

$("#browseBtn").addEventListener("click", async () => {
  try {
    const res = await api("/api/pick", { mode: "files", title: "Choose files to check" });
    if (!res.available) {
      toast(res.error || "No native file dialog here — drag files in instead.", true);
      return;
    }
    if (res.files.length) addFiles(res.files);
  } catch (e) {
    toast(e.message, true);
  }
});

$("#clearBtn").addEventListener("click", () => {
  files.length = 0;
  activeKey = null;
  renderList();
  renderDetail();
});

$("#cleanAllBtn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  const targets = files.filter((f) => f.status !== "error");
  if (!targets.length) { toast("Nothing to clean"); return; }
  btn.disabled = true;
  const bar = $("#progressBar");
  $("#progress").hidden = false;
  let done = 0;
  for (const f of targets) {
    await cleanOne(f, null);
    done += 1;
    bar.style.width = `${Math.round((done / targets.length) * 100)}%`;
  }
  $("#progress").hidden = true;
  bar.style.width = "0%";
  btn.disabled = false;
  toast(`Cleaned ${plural(done, "file", "files")}`);
});

$("#downloadAllBtn").addEventListener("click", () => {
  const ids = files.filter((f) => f.clean && f.clean.download_id).map((f) => f.clean.download_id);
  if (!ids.length) return;
  download(`/api/download-all?ids=${ids.map(encodeURIComponent).join(",")}`, "cleaned-files.zip")
    .catch((err) => toast(err.message, true));
});

for (const id of ["#optAggressive", "#optAs"]) {
  $(id).addEventListener("change", () => {
    scanQueue = scanQueue.then(async () => {
      for (const f of files) if (f.status !== "error") await inspectOne(f);
    });
  });
}

// ---------------------------------------------------------------- 02 text

const textInput = $("#textInput");
let textReport = null;
let textMode = "edit";
let textTimer = null;
let textSeq = 0;

function renderText() {
  const value = textInput.value;
  $("#textMeta").textContent = `${value.length.toLocaleString()} characters`;

  const verdict = $("#textVerdict");
  const hitsWrap = $("#textHits");
  const legendWrap = $("#textLegend");
  const revealWrap = $("#revealArea");

  if (!value) {
    verdict.hidden = true;
    hitsWrap.hidden = true;
    legendWrap.hidden = true;
    revealWrap.replaceChildren();
    return;
  }
  if (!textReport) return;

  verdict.hidden = false;
  verdict.className = `verdict ${textReport.clean ? "clean" : "found"}`;
  verdict.replaceChildren(
    el("p", {
      class: "verdict-title",
      text: textReport.clean
        ? "Nothing hidden in here"
        : `${plural(textReport.suspicious_total, "hidden character", "hidden characters")} found`,
    }),
    el("p", {
      class: "verdict-sub",
      text: textReport.clean
        ? "No invisible or look-alike characters. Statistical watermarks are invisible to this check — see Rewrite."
        : "Switch to Reveal (or press R) to see exactly where they sit.",
    }));

  const hasHits = textReport.hits.length > 0;
  hitsWrap.hidden = !hasHits;
  legendWrap.hidden = !hasHits;
  if (hasHits) {
    hitsWrap.replaceChildren(hitsTable(textReport.hits));
    const lg = legendNode(textReport.hits);
    legendWrap.replaceChildren(...(lg ? lg.childNodes : []));
  }

  revealWrap.replaceChildren(...revealNode(textReport.reveal).childNodes);
}

async function inspectTextNow() {
  const value = textInput.value;
  if (!value) { textReport = null; renderText(); return; }
  const seq = ++textSeq;
  try {
    const report = await api("/api/text/inspect", {
      text: value, aggressive: $("#textAggressive").checked,
    });
    if (seq !== textSeq) return;  // a newer keystroke already won
    textReport = report;
  } catch (e) {
    if (seq !== textSeq) return;
    toast(e.message, true);
    textReport = null;
  }
  renderText();
}

textInput.addEventListener("input", () => {
  $("#textMeta").textContent = `${textInput.value.length.toLocaleString()} characters`;
  clearTimeout(textTimer);
  textTimer = setTimeout(inspectTextNow, 350);
});
$("#textAggressive").addEventListener("change", inspectTextNow);

$("#textModeSeg").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  textMode = btn.dataset.mode;
  $$("#textModeSeg .seg-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
  textInput.hidden = textMode !== "edit";
  $("#revealArea").hidden = textMode !== "reveal";
});

$("#textCleanBtn").addEventListener("click", async (e) => {
  if (!textInput.value) { toast("Paste some text first"); return; }
  const btn = e.currentTarget;
  btn.disabled = true;
  try {
    const res = await api("/api/text/clean", {
      text: textInput.value,
      nfkc: $("#textNfkc").checked,
      aggressive_homoglyphs: $("#textAggressive").checked,
      aggressive: $("#textAggressive").checked,
    });
    textInput.value = res.text;
    textSeq += 1;
    textReport = res.report;
    renderText();
    const s = res.stats;
    toast(s.removed_count || s.replaced_count
      ? `Removed ${s.removed_count}, replaced ${s.replaced_count}`
      : "Nothing needed removing");
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
});

$("#textCopyBtn").addEventListener("click", () => copyText(textInput.value));
$("#textClearBtn").addEventListener("click", () => {
  textInput.value = "";
  textSeq += 1;
  textReport = null;
  renderText();
});
$("#textDownloadBtn").addEventListener("click", async () => {
  if (!textInput.value) { toast("Nothing to save"); return; }
  try {
    const res = await api("/api/text/save", { text: textInput.value, name: "cleaned.txt" });
    await download(`/api/download?id=${encodeURIComponent(res.download_id)}`, res.name);
  } catch (e) {
    toast(e.message, true);
  }
});

// ---------------------------------------------------------------- 03 rewrite

const DEFAULT_URLS = {
  ollama: "http://127.0.0.1:11434",
  "openai-compatible": "http://127.0.0.1:8080/v1",
};

function syncRewriteControls() {
  const backend = $("#rwBackend").value;
  const strength = $("#rwStrength").value;
  $("#rwLangRow").hidden = strength !== "backtranslate";
  $("#rwModelBox").hidden = backend === "print-prompt";
  $("#rwKeyRow").hidden = backend !== "openai-compatible";
  $("#rwRunBtn").textContent = backend === "print-prompt" ? "Build prompt" : "Rewrite";
  if (backend !== "print-prompt" && DEFAULT_URLS[backend]) {
    const current = $("#rwBaseUrl").value.trim();
    if (!current || Object.values(DEFAULT_URLS).includes(current)) {
      $("#rwBaseUrl").value = DEFAULT_URLS[backend];
    }
  }
}
$("#rwBackend").addEventListener("change", syncRewriteControls);
$("#rwStrength").addEventListener("change", syncRewriteControls);
syncRewriteControls();

$("#rwProbeBtn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  const box = $("#rwProbe");
  btn.disabled = true;
  box.hidden = false;
  box.className = "probe-result";
  box.textContent = "Checking…";
  try {
    const res = await api("/api/rewrite/probe", {
      base_url: $("#rwBaseUrl").value, backend: $("#rwBackend").value,
    });
    if (res.ok) {
      box.className = "probe-result ok";
      box.textContent = res.models && res.models.length
        ? `Reachable. Models: ${res.models.join(", ")}`
        : "Reachable.";
      $("#rwModelList").replaceChildren(...(res.models || []).map((m) => el("option", { value: m })));
      if (!$("#rwModel").value && res.models && res.models.length) $("#rwModel").value = res.models[0];
    } else {
      box.className = "probe-result bad";
      box.textContent = res.error || "Not reachable.";
    }
  } catch (err) {
    box.className = "probe-result bad";
    box.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

$("#rwRunBtn").addEventListener("click", async (e) => {
  const text = $("#rwInput").value;
  if (!text.trim()) { toast("Paste some text first"); return; }
  const backend = $("#rwBackend").value;
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = backend === "print-prompt" ? "Building…" : "Rewriting…";
  try {
    const res = await api("/api/rewrite", {
      text,
      backend,
      strength: $("#rwStrength").value,
      model: $("#rwModel").value,
      base_url: $("#rwBaseUrl").value,
      api_key: $("#rwApiKey").value,
      lang: $("#rwLang").value,
      original_lang: $("#rwOriginalLang").value,
      temperature: parseFloat($("#rwTemp").value) || 0.9,
      candidates: parseInt($("#rwCandidates").value, 10) || 1,
      timeout: parseFloat($("#rwTimeout").value) || 120,
      layer_a_after: $("#rwLayerA").checked,
      allow_remote: $("#rwAllowRemote").checked,
    });
    showRewrite(res);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    syncRewriteControls();
  }
});

function showRewrite(res) {
  const info = res.info || {};
  const isPrompt = info.mode === "print-prompt";
  $("#rwResult").hidden = false;
  $("#rwResultLabel").textContent = isPrompt
    ? "Prompt — paste this into any chat model"
    : "Rewritten text";
  $("#rwOutput").textContent = res.text;
  $("#rwReadout").replaceChildren(...readout([
    ["Mode", info.mode || "—"],
    ["Approach", info.strength || "—"],
    info.model ? ["Model", info.model] : null,
    ["Chars in", info.input_chars],
    info.output_chars ? ["Chars out", info.output_chars] : null,
    res.divergence != null ? ["Divergence", `${Math.round(res.divergence * 100)}%`] : null,
    info.candidates ? ["Tries", info.candidates] : null,
  ]).childNodes);
  $("#rwResult").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

$("#rwCopyBtn").addEventListener("click", () => copyText($("#rwOutput").textContent));
$("#rwDownloadBtn").addEventListener("click", async () => {
  try {
    const res = await api("/api/text/save", {
      text: $("#rwOutput").textContent, name: "rewritten.txt",
    });
    await download(`/api/download?id=${encodeURIComponent(res.download_id)}`, res.name);
  } catch (e) {
    toast(e.message, true);
  }
});

// ---------------------------------------------------------------- 04 setup

const INSTALL = {
  Windows: {
    exiftool: "winget install -e --id OliverBetz.ExifTool",
    c2patool: "cargo install c2patool",
    tk: "Reinstall Python and tick “tcl/tk and IDLE”",
  },
  Darwin: {
    exiftool: "brew install exiftool",
    c2patool: "cargo install c2patool",
    tk: "brew install python-tk",
  },
  Linux: {
    exiftool: "sudo apt install libimage-exiftool-perl",
    c2patool: "cargo install c2patool",
    tk: "sudo apt install python3-tk",
  },
};

function osKey(platformString) {
  if (/windows/i.test(platformString)) return "Windows";
  if (/darwin|mac/i.test(platformString)) return "Darwin";
  return "Linux";
}

function snippet(command) {
  return el("div", { class: "snippet" },
    el("code", { text: command }),
    el("button", { class: "btn btn-sm", text: "Copy", onclick: () => copyText(command) }));
}

function toolCard(name, info, blurb, command) {
  return el("div", { class: "card" },
    el("h3", {},
      el("span", { text: name }),
      el("span", { class: `status-pill ${info.available ? "on" : "off"}`,
        text: info.available ? "installed" : "missing" })),
    el("p", { text: blurb }),
    info.available
      ? el("dl", { class: "kv" },
          el("dt", { text: "Version" }), el("dd", { text: info.version || "unknown" }),
          el("dt", { text: "Path" }), el("dd", { text: info.path }))
      : snippet(command));
}

async function loadSetup() {
  const body = $("#setupBody");
  body.replaceChildren(el("div", { class: "skeleton" },
    el("div", { class: "sk-line" }), el("div", { class: "sk-line short" })));
  try {
    const d = await api("/api/diagnostics", {});
    const os = osKey(d.platform);
    const install = INSTALL[os];

    const cards = [
      el("div", { class: "card" },
        el("h3", {}, el("span", { text: "This machine" })),
        el("dl", { class: "kv" },
          el("dt", { text: "Python" }), el("dd", { text: d.python }),
          el("dt", { text: "System" }), el("dd", { text: d.platform }),
          el("dt", { text: "Size limit" }), el("dd", { text: `${d.max_input_mib} MiB per file` }),
          el("dt", { text: "Scripts" }), el("dd", { text: d.scripts_dir }))),

      toolCard("exiftool", d.tools.exiftool,
        "Strips residual metadata that pure-Python passes cannot reach — the difference between a best-effort and a reliable PDF clean.",
        install.exiftool),

      toolCard("c2patool", d.tools.c2patool,
        "Reads C2PA / Content Credentials manifests, so inspection reports what a verifier would actually see.",
        install.c2patool),

      el("div", { class: "card" },
        el("h3", {},
          el("span", { text: "SynthID pixel scoring" }),
          el("span", { class: `status-pill ${d.synthid.configured && d.synthid.exists ? "on" : "off"}`,
            text: d.synthid.configured && d.synthid.exists ? "ready" : "not set up" })),
        el("p", { text: "Optional, heavy, and third-party: scores images for Google’s pixel watermark. Point REVERSE_SYNTHID_DIR at a reverse-SynthID checkout, then restart this app." }),
        d.synthid.dir ? el("dl", { class: "kv" },
          el("dt", { text: "Dir" }), el("dd", { text: d.synthid.dir }),
          el("dt", { text: "Exists" }), el("dd", { text: d.synthid.exists ? "yes" : "no" })) : null,
        snippet(os === "Windows"
          ? "set REVERSE_SYNTHID_DIR=C:\\path\\to\\reverse-SynthID"
          : "export REVERSE_SYNTHID_DIR=~/reverse-SynthID")),

      el("div", { class: "card" },
        el("h3", {},
          el("span", { text: "Native file dialogs" }),
          el("span", { class: `status-pill ${d.native_dialogs ? "on" : "off"}`,
            text: d.native_dialogs ? "available" : "missing" })),
        el("p", { text: d.native_dialogs
          ? "The Browse button opens your system file picker, which lets this app write cleaned files next to the originals."
          : "Tkinter is not installed, so Browse cannot open. Drag and drop still works — cleaned files come back as downloads." }),
        d.native_dialogs ? null : snippet(install.tk)),
    ];

    if (d.compat_notes && d.compat_notes.length) {
      cards.push(el("div", { class: "card" },
        el("h3", {}, el("span", { text: "Platform notes" })),
        el("ul", { class: "findings plain" }, d.compat_notes.map((n) => el("li", { text: n })))));
    }

    body.replaceChildren(...cards);
  } catch (e) {
    body.replaceChildren(emptyState("Cannot reach the local server", e.message,
      el("button", { class: "btn", text: "Try again", onclick: loadSetup })));
  }
}

$("#setupRefresh").addEventListener("click", loadSetup);
$("#quitBtn").addEventListener("click", async () => {
  try { await api("/api/shutdown", {}); } catch { /* the server is going away */ }
  document.body.replaceChildren(el("div", { class: "farewell" },
    el("p", { text: "watermarks-remover has stopped. You can close this window." })));
});

// ---------------------------------------------------------------- 05 guide

let docsLoaded = false;

async function loadDocs() {
  if (docsLoaded) return;
  try {
    const res = await api("/api/refs", {});
    $("#docList").replaceChildren(...res.docs.map((doc) => el("li", {},
      el("button", {
        type: "button",
        text: doc.title,
        onclick: (e) => {
          $$("#docList button").forEach((b) => b.classList.toggle("is-active", b === e.currentTarget));
          showDoc(doc.id);
        },
      }))));
    docsLoaded = true;
    const first = $("#docList button");
    if (first) first.click();
  } catch (e) {
    $("#docBody").replaceChildren(emptyState("Could not load the notes", e.message));
  }
}

async function showDoc(id) {
  try {
    const res = await api("/api/refs", { id });
    $("#docBody").replaceChildren(...markdownNodes(res.body));
  } catch (e) {
    $("#docBody").replaceChildren(emptyState("Could not load that document", e.message));
  }
}

// Small markdown renderer. Builds DOM nodes rather than HTML strings, so
// nothing in a document can turn into markup.
function markdownNodes(src) {
  const out = [];
  const lines = src.split(/\r?\n/);
  let para = [];
  let list = null;
  let quote = [];

  const inline = (text) => {
    const nodes = [];
    const re = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*\n]+)\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
    let last = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m.index > last) nodes.push(text.slice(last, m.index));
      if (m[1] != null) nodes.push(el("code", { text: m[1] }));
      else if (m[2] != null) nodes.push(el("strong", { text: m[2] }));
      else if (m[3] != null) nodes.push(el("em", { text: m[3] }));
      else {
        const href = /^(https?:|#|\.|\/)/.test(m[5]) ? m[5] : "#";
        nodes.push(el("a", { href, target: "_blank", rel: "noopener noreferrer", text: m[4] }));
      }
      last = re.lastIndex;
    }
    if (last < text.length) nodes.push(text.slice(last));
    return nodes;
  };

  const flushPara = () => {
    if (para.length) { out.push(el("p", {}, inline(para.join(" ")))); para = []; }
  };
  const flushList = () => { list = null; };
  const flushQuote = () => {
    if (quote.length) { out.push(el("blockquote", {}, inline(quote.join(" ")))); quote = []; }
  };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    const fence = /^```(\w*)\s*$/.exec(line);
    if (fence) {
      flushAll();
      const buf = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      out.push(el("pre", {}, el("code", { text: buf.join("\n") })));
      continue;
    }
    if (!line.trim()) { flushAll(); continue; }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushAll();
      out.push(el(`h${Math.min(heading[1].length, 6)}`, {}, inline(heading[2])));
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flushAll(); out.push(el("hr", {})); continue; }

    if (line.trim().startsWith("|") && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
      flushAll();
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      i -= 1;
      out.push(el("div", { class: "table-scroll" },
        el("table", {},
          el("thead", {}, el("tr", {}, head.map((c) => el("th", {}, inline(c))))),
          el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, inline(c)))))))));
      continue;
    }

    const quoted = /^>\s?(.*)$/.exec(line);
    if (quoted) { flushPara(); flushList(); quote.push(quoted[1]); continue; }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushPara(); flushQuote();
      const want = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== want) {
        list = el(want, {});
        out.push(list);
      }
      list.append(el("li", {}, inline((bullet || numbered)[1])));
      continue;
    }

    flushList(); flushQuote();
    para.push(line.trim());
  }
  flushAll();
  return out;
}

// ---------------------------------------------------------------- boot

(async function boot() {
  try {
    const d = await api("/api/diagnostics", {});
    $("#toolStrip").replaceChildren(
      el("span", { class: `tool-dot ${d.tools.exiftool.available ? "on" : "off"}` },
        el("i", {}), "exiftool"),
      el("span", { class: `tool-dot ${d.tools.c2patool.available ? "on" : "off"}` },
        el("i", {}), "c2patool"));
    $("#synthidRow").hidden = !(d.synthid.configured && d.synthid.exists);
  } catch (e) {
    toast(`Cannot reach the local server: ${e.message}`, true);
  }
  renderList();
  renderDetail();
})();

})();
