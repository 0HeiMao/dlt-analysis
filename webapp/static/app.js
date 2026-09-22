/* 超级大乐透历史数据分析工具 - 本地版 前端逻辑 (原生 JS, 无任何外部依赖)
 *
 * 重要声明: 开奖为独立随机事件, 本工具不预测未来结果;
 * 任何统计依据都不改变单个组合的中奖概率 (恒为 1/21,425,712)。
 */
"use strict";

/* ============ 工具函数 ============ */
function el(id) { return document.getElementById(id); }
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function fmtInt(n) { return Number(n).toLocaleString("zh-CN"); }
function fmtFixed(x, d) { return Number(x).toFixed(d === undefined ? 4 : d); }
function fmtPct(x, d) { return (Number(x) * 100).toFixed(d === undefined ? 2 : d) + "%"; }
function fmtSci(p) {
  if (p <= 0) return "0";
  return Number(p).toExponential(6);
}
function fmtOneIn(p) {
  if (!p || p <= 0) return "-";
  var n = 1 / p;
  return "1/" + (n >= 1000 ? fmtInt(Math.round(n)) : fmtFixed(n, n >= 100 ? 1 : 2));
}
function fmtNum(v) {
  if (v >= 100) return String(Math.round(v));
  if (v >= 10) return String(Math.round(v * 10) / 10);
  return String(Math.round(v * 100) / 100);
}
function ballHTML(n, zone) {
  return '<span class="ball ' + zone + '">' + (n < 10 ? "0" + n : n) + "</span>";
}

var toastTimer = null;
function toast(msg) {
  var t = el("toast");
  t.textContent = msg;
  t.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.classList.remove("show"); }, 5000);
}

/* ============ API 封装 (统一中文错误) ============ */
async function api(path, opts) {
  opts = opts || {};
  var init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined && !(opts.body instanceof FormData)) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  } else if (opts.body instanceof FormData) {
    init.body = opts.body;
  }
  var resp;
  try {
    resp = await fetch(path, init);
  } catch (e) {
    throw new Error("网络请求失败：无法连接本地服务，请确认 server.py 正在运行（默认端口 8765）。");
  }
  var data = null;
  try { data = await resp.json(); } catch (e) { data = null; }
  if (!resp.ok) {
    var detail = data && data.detail ? data.detail : "HTTP " + resp.status;
    if (typeof detail !== "string") detail = JSON.stringify(detail);
    var err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  return data;
}

function setBtnLoading(btn, loading, text) {
  if (!btn) return;
  btn.disabled = loading;
  if (loading) { btn.dataset.origText = btn.textContent; btn.textContent = text || "计算中…"; }
  else if (btn.dataset.origText) { btn.textContent = btn.dataset.origText; }
}

function notLoadedHint() {
  return '<div class="warn-inline">尚未载入数据集：请先到「<b>数据管理</b>」页上传 CSV 或载入内置模拟数据。</div>';
}

/* ============ 全局状态 ============ */
var datasetLoaded = false;
var loadedTabs = {};

function refreshStatus(ds) {
  var box = el("ds-status");
  if (ds && ds.loaded) {
    datasetLoaded = true;
    box.className = "ds-status loaded";
    box.textContent = "当前数据集：" + ds.name + "（有效 " + fmtInt(ds.valid_rows) + " 期 / 原始 " + fmtInt(ds.rows) + " 条）";
  } else {
    datasetLoaded = false;
    box.className = "ds-status not-loaded";
    box.textContent = "未载入数据集 —— 请到「数据管理」页载入数据";
  }
}

async function checkHealth() {
  try {
    var h = await api("/api/health");
    el("ds-status").textContent = "服务正常 (v" + h.version + ") · 未载入数据集";
    refreshStatus(h.dataset);
  } catch (e) {
    el("ds-status").className = "ds-status not-loaded";
    el("ds-status").textContent = "服务不可用：" + e.message;
    toast(e.message);
  }
}

/* ============ Tab 切换 ============ */
var tabLoaders = {
  describe: function () { loadDescribe(); },
  probability: function () { loadProbability(); },
  randomness: function () { loadRandomness(); },
  generate: function () { loadGenerate(); }
};

function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach(function (b) {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach(function (p) {
    p.classList.toggle("active", p.id === "tab-" + name);
  });
  if (tabLoaders[name] && !loadedTabs[name]) {
    loadedTabs[name] = true;
    tabLoaders[name]();
  }
}

/* ============ SVG 柱状图 / 直方图 ============ */
function barChart(cfg) {
  var W = cfg.width || 940, H = cfg.height || 300;
  var m = { l: 54, r: 18, t: 16, b: 34 };
  var pw = W - m.l - m.r, ph = H - m.t - m.b;
  var labels = cfg.labels, values = cfg.values;
  var n = labels.length;
  var expected = cfg.expected || null;
  var max = Math.max.apply(null, values.concat(expected !== null ? [expected] : [0]));
  if (!isFinite(max) || max <= 0) max = 1;
  max = max * 1.12;
  var slot = pw / n;
  var barW = cfg.hist ? Math.max(slot - 0.5, 0.5) : Math.min(slot * 0.72, 34);

  var s = '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" width="' + W +
          '" height="' + H + '" xmlns="http://www.w3.org/2000/svg" role="img">';
  for (var g = 0; g <= 4; g++) {
    var gy = m.t + ph * (1 - g / 4);
    s += '<line x1="' + m.l + '" y1="' + gy.toFixed(1) + '" x2="' + (W - m.r) +
         '" y2="' + gy.toFixed(1) + '" stroke="#e3e9f0" stroke-width="1"/>';
    s += '<text x="' + (m.l - 6) + '" y="' + (gy + 4).toFixed(1) +
         '" text-anchor="end" font-size="10.5" fill="#6b7a8d">' +
         fmtNum(max * g / 4) + "</text>";
  }
  for (var i = 0; i < n; i++) {
    var h = ph * (values[i] / max);
    var x = m.l + i * slot + (slot - barW) / 2;
    var y = m.t + ph - h;
    s += '<rect x="' + x.toFixed(2) + '" y="' + y.toFixed(2) + '" width="' +
         barW.toFixed(2) + '" height="' + Math.max(h, 0).toFixed(2) + '" fill="' +
         (cfg.color || "#4a7fc1") + '" rx="1"><title>' + esc(labels[i]) + " : " +
         fmtNum(values[i]) + "</title></rect>";
  }
  if (expected !== null && expected > 0) {
    var ey = m.t + ph * (1 - expected / max);
    s += '<line x1="' + m.l + '" y1="' + ey.toFixed(2) + '" x2="' + (W - m.r) +
         '" y2="' + ey.toFixed(2) + '" stroke="#c0392b" stroke-width="1.6" stroke-dasharray="7 5"/>';
    s += '<text x="' + (W - m.r - 4) + '" y="' + (ey - 5).toFixed(2) +
         '" text-anchor="end" font-size="11" fill="#c0392b">' +
         esc(cfg.expectedLabel || "理论期望") + " " + fmtNum(expected) + "</text>";
  }
  var every = cfg.labelEvery || 1;
  for (var k = 0; k < n; k++) {
    if (k % every !== 0) continue;
    var lx = m.l + k * slot + slot / 2;
    s += '<text x="' + lx.toFixed(2) + '" y="' + (H - m.b + 15) +
         '" text-anchor="middle" font-size="10" fill="#6b7a8d">' + esc(labels[k]) + "</text>";
  }
  s += "</svg>";
  return s;
}

function chartBlock(title, note, svg) {
  return '<div class="chart-box"><div class="chart-title">' + title + "</div>" +
         (note ? '<div class="chart-note">' + note + "</div>" : "") + svg + "</div>";
}

/* ============ Tab 1: 数据管理 ============ */
function renderReport(payload) {
  refreshStatus(payload.dataset);
  el("report-card").style.display = "";
  el("report-source").textContent = "（" + payload.dataset.name + "）";
  var r = payload.report;
  el("report-summary").innerHTML =
    statBox("原始记录数", fmtInt(r.original_rows)) +
    statBox("有效记录数", fmtInt(r.valid_rows), "ok") +
    statBox("丢弃记录数", fmtInt(r.dropped_rows), r.dropped_rows > 0 ? "warn" : "") +
    statBox("warning", fmtInt(r.warning_count), r.warning_count > 0 ? "warn" : "") +
    statBox("error", fmtInt(r.error_count), r.error_count > 0 ? "warn" : "");

  var tb = el("issues-table").querySelector("tbody");
  tb.innerHTML = "";
  if (!r.issues || r.issues.length === 0) {
    el("issues-empty").style.display = "";
  } else {
    el("issues-empty").style.display = "none";
    r.issues.forEach(function (it) {
      var tr = document.createElement("tr");
      tr.innerHTML = '<td class="lv-' + esc(it["级别"]) + '">' + esc(it["级别"]) + "</td>" +
        "<td>" + esc(it["期号"] || "-") + "</td>" +
        "<td>" + esc(it["规则码"]) + "</td>" +
        '<td class="left">' + esc(it["规则说明"] || "") + "</td>" +
        '<td class="left">' + esc(it["明细"]) + "</td>";
      tb.appendChild(tr);
    });
  }
  var pt = el("preview-table").querySelector("tbody");
  pt.innerHTML = "";
  (payload.preview || []).forEach(function (row) {
    var tr = document.createElement("tr");
    tr.innerHTML = "<td>" + esc(row["期号"]) + "</td><td>" + esc(row["开奖日期"]) + "</td>" +
      [1, 2, 3, 4, 5].map(function (i) { return "<td>" + esc(row["前区" + i]) + "</td>"; }).join("") +
      "<td>" + esc(row["后区1"]) + "</td><td>" + esc(row["后区2"]) + "</td>";
    pt.appendChild(tr);
  });
}

function statBox(k, v, cls) {
  return '<div class="stat-box ' + (cls || "") + '"><div class="v">' + v + '</div><div class="k">' + k + "</div></div>";
}

async function loadSample() {
  var btn = el("btn-sample");
  setBtnLoading(btn, true, "载入中…");
  el("data-error").textContent = "";
  try {
    var res = await api("/api/dataset/sample", { method: "POST" });
    renderReport(res);
    toast(res.message);
  } catch (e) {
    el("data-error").textContent = e.message;
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

async function uploadCsv() {
  var f = el("csv-file").files[0];
  if (!f) { el("data-error").textContent = "请先选择要上传的 CSV 文件。"; return; }
  var btn = el("btn-upload");
  setBtnLoading(btn, true, "上传清洗中…");
  el("data-error").textContent = "";
  try {
    var fd = new FormData();
    fd.append("file", f);
    var res = await api("/api/dataset/upload", { method: "POST", body: fd });
    renderReport(res);
    toast(res.message);
  } catch (e) {
    el("data-error").textContent = e.message;
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

/* ============ Tab 2: 描述统计 ============ */
async function loadDescribe() {
  if (!datasetLoaded) {
    el("describe-body").innerHTML = notLoadedHint();
    return;
  }
  var btn = el("btn-describe");
  setBtnLoading(btn, true, "统计计算中…");
  el("describe-error").textContent = "";
  el("describe-body").innerHTML = '<div class="card"><p class="muted">统计计算中，请稍候…</p></div>';
  try {
    var topN = parseInt(el("desc-topn").value, 10) || 5;
    var res = await api("/api/describe?top_n=" + topN);
    renderDescribe(res);
  } catch (e) {
    el("describe-body").innerHTML = "";
    el("describe-error").textContent = e.message;
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

function renderDescribe(res) {
  var st = res.statistics;
  var html = "";

  html += '<div class="card"><h2>概览</h2><div class="stat-grid">' +
    statBox("有效期数", fmtInt(st.total_issues)) +
    statBox("前区单号理论期望频次", fmtFixed(st.frequency_front[0]["理论期望频次"], 2)) +
    statBox("后区单号理论期望频次", fmtFixed(st.frequency_back[0]["理论期望频次"], 2)) +
    "</div></div>";

  /* 1. 频次柱状图 */
  html += '<div class="card"><h2>号码频次分布</h2>';
  html += chartBlock("前区 35 个号码出现次数（红色虚线 = 理论期望频次 = 期数 × 5/35）", null,
    barChart({
      labels: st.frequency_front.map(function (r) { return r["号码"]; }),
      values: st.frequency_front.map(function (r) { return r["出现次数"]; }),
      expected: st.frequency_front[0]["理论期望频次"],
      color: "#4a7fc1", labelEvery: 1
    }));
  html += chartBlock("后区 12 个号码出现次数（红色虚线 = 理论期望频次 = 期数 × 2/12）", null,
    barChart({
      labels: st.frequency_back.map(function (r) { return r["号码"]; }),
      values: st.frequency_back.map(function (r) { return r["出现次数"]; }),
      expected: st.frequency_back[0]["理论期望频次"],
      color: "#2e9e7e", width: 560, height: 260
    }));
  html += '<p class="muted small">口径：频率 = 出现次数 / 总期数；前区 35 个号的频率之和 = 5，后区 12 个号的频率之和 = 2。柱子高度差异属于正常随机波动，不代表未来走势。</p></div>';

  /* 2. 冷热号 */
  html += '<div class="card"><h2>冷热号（对照理论期望频次）</h2>';
  html += chipBlock("前区热号 Top", st.hot_cold_front.hot, "hot");
  html += chipBlock("前区冷号 Bottom", st.hot_cold_front.cold, "cold");
  html += chipBlock("后区热号 Top", st.hot_cold_back.hot, "hot");
  html += chipBlock("后区冷号 Bottom", st.hot_cold_back.cold, "cold");
  html += '<p class="muted small">说明：热/冷仅是按历史频次的排序描述；随机性检验（见「随机性检验」页）未检出显著偏离，因此“热号更易出”没有任何统计支持。</p></div>';

  /* 3. 遗漏值 */
  html += '<div class="card"><h2>遗漏值</h2><p class="muted small">口径：当前遗漏 = 距最近一次出现的期数；历史最大遗漏含首现前与末现后的间隔。</p>';
  html += missingTable("前区", st.missing_front);
  html += missingTable("后区", st.missing_back);
  html += '<p class="muted small">提醒：号码“遗漏很久”不意味着它更容易出现——每期独立，单号命中概率恒为 5/35（前区）/ 2/12（后区）。</p></div>';

  /* 4. 和值 */
  var sd = st.sum_distribution;
  var sums = Object.keys(sd.histogram).map(Number).sort(function (a, b) { return a - b; });
  html += '<div class="card"><h2>前区和值分布</h2><div class="stat-grid">' +
    statBox("观测均值", fmtFixed(sd.observed_mean, 2)) +
    statBox("观测标准差", fmtFixed(sd.observed_std, 2)) +
    statBox("理论均值", fmtFixed(sd.theoretical_mean, 2)) +
    statBox("理论标准差", fmtFixed(sd.theoretical_std, 2)) +
    "</div>";
  html += chartBlock("和值直方图（红色虚线 = 理论均值 " + fmtFixed(sd.theoretical_mean, 1) + "）", null,
    barChart({
      labels: sums, values: sums.map(function (s) { return sd.histogram[s]; }),
      expected: sd.theoretical_mean, expectedLabel: "理论均值",
      color: "#8f6fc0", hist: true, labelEvery: 5, width: 940, height: 300
    }));
  html += "</div>";

  /* 5-9. 形态表 */
  html += '<div class="card"><h2>形态分布（观测 vs 理论）</h2>';
  html += ratioTable("奇偶比（前区奇数个数）", "奇:偶", st.odd_even, 5, function (k) { return k + ":" + (5 - k); });
  html += ratioTable("大小比（18 为界，大号个数）", "大:小", st.big_small, 5, function (k) { return k + ":" + (5 - k); });
  html += zoneTable(st.zone);
  html += simpleRatioTable("连号组数（相邻号码差为 1 的极大连号组）", st.consecutive, 4);
  html += simpleRatioTable("重号个数（相邻两期前区重复号码）", st.repeat, 5,
    "理论期望重号个数 = 5 × 5 / 35 = " + fmtFixed(st.repeat.expected_repeat, 4));
  html += "</div>";

  html += '<div class="conclusion"><b>解读提示：</b>以上统计仅描述历史样本的形态。观测值与理论值的差异在小样本下必然存在，且不构成对未来的任何预测——每期开奖相互独立。</div>';
  el("describe-body").innerHTML = html;
}

function chipBlock(title, records, cls) {
  var chips = records.map(function (r) {
    return '<span class="chip ' + cls + '">' + r["号码"] + "（" + r["出现次数"] + " 次）</span>";
  }).join("");
  return '<h3>' + title + "</h3><div class=\"chip-list\">" + chips + "</div>";
}

function missingTable(title, rows) {
  var t = '<h3>' + title + "（" + rows.length + " 个号码）</h3><div class=\"table-wrap\"><table class=\"data-table\">" +
    "<thead><tr><th>号码</th><th>当前遗漏</th><th>历史最大遗漏</th><th>平均遗漏</th></tr></thead><tbody>";
  rows.forEach(function (r) {
    t += "<tr><td>" + r["号码"] + "</td><td>" + r["当前遗漏"] + "</td><td>" +
         r["历史最大遗漏"] + "</td><td>" + fmtFixed(r["平均遗漏"], 2) + "</td></tr>";
  });
  return t + "</tbody></table></div>";
}

function ratioTable(title, midLabel, data, maxK, labelFn) {
  var t = "<h3>" + title + "</h3><div class=\"table-wrap\"><table class=\"data-table\">" +
    "<thead><tr><th>" + midLabel + "</th><th>观测期数</th><th>观测频率</th><th>理论概率（超几何）</th></tr></thead><tbody>";
  for (var k = 0; k <= maxK; k++) {
    t += "<tr><td>" + labelFn(k) + "</td><td>" + (data.observed[String(k)] || 0) + "</td><td>" +
         fmtFixed(data.observed_freq[String(k)] || 0, 4) + "</td><td>" +
         fmtFixed(data.theoretical[String(k)] || 0, 4) + "</td></tr>";
  }
  return t + "</tbody></table></div>";
}

function simpleRatioTable(title, data, maxK, footNote) {
  var t = "<h3>" + title + "</h3><div class=\"table-wrap\"><table class=\"data-table\">" +
    "<thead><tr><th>个数</th><th>观测期数</th><th>观测频率</th><th>理论概率</th></tr></thead><tbody>";
  for (var k = 0; k <= maxK; k++) {
    t += "<tr><td>" + k + "</td><td>" + (data.observed[String(k)] || 0) + "</td><td>" +
         fmtFixed(data.observed_freq[String(k)] || 0, 4) + "</td><td>" +
         fmtFixed(data.theoretical[String(k)] || 0, 4) + "</td></tr>";
  }
  t += "</tbody></table></div>";
  if (footNote) t += '<p class="muted small">' + footNote + "</p>";
  return t;
}

function zoneTable(z) {
  var t = "<h3>区间分布（01-07 / 08-14 / 15-21 / 22-28 / 29-35）</h3><div class=\"table-wrap\"><table class=\"data-table\">" +
    "<thead><tr><th>区间</th><th>命中总数</th><th>平均每期</th><th>理论每期</th></tr></thead><tbody>";
  for (var i = 1; i <= 5; i++) {
    var lo = z.zones[String(i)][0], hi = z.zones[String(i)][1];
    t += "<tr><td>" + (lo < 10 ? "0" + lo : lo) + "-" + (hi < 10 ? "0" + hi : hi) + "</td><td>" +
      z.observed_total[String(i)] + "</td><td>" + fmtFixed(z.observed_avg_per_issue[String(i)], 4) +
      "</td><td>" + fmtFixed(z.theoretical_avg_per_issue[String(i)], 4) + "</td></tr>";
  }
  return t + "</tbody></table></div>";
}

/* ============ Tab 3: 概率推理 ============ */
var PRIZE_ORDER = ["一等奖", "二等奖", "三等奖", "四等奖", "五等奖", "六等奖", "七等奖", "八等奖", "九等奖"];

async function loadProbability() {
  var btn = el("btn-probability");
  setBtnLoading(btn, true, "计算中…");
  el("probability-error").textContent = "";
  el("probability-body").innerHTML = '<div class="card"><p class="muted">概率计算中…</p></div>';
  try {
    var res = await api("/api/probability");
    renderProbability(res);
  } catch (e) {
    el("probability-body").innerHTML = "";
    el("probability-error").textContent = e.message;
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

function renderProbability(res) {
  var cc = res.combination_counts;
  var sc = res.self_consistency;
  var ev = res.expected_value;
  var html = "";

  html += '<div class="card"><h2>组合总数与自洽性</h2><div class="stat-grid">' +
    statBox("前区组合数 C(35,5)", fmtInt(cc.front)) +
    statBox("后区组合数 C(12,2)", fmtInt(cc.back)) +
    statBox("总组合数", fmtInt(cc.total)) +
    statBox("至少中任一奖级", fmtOneIn(res.any_prize_probability)) +
    "</div>";
  html += '<p>概率自洽性断言（各奖级概率之和与精确计数交叉校验）：<span class="badge ' +
    (sc.passed ? "pass" : "fail") + '">' + (sc.passed ? "PASSED 通过" : "FAILED 失败") +
    "</span></p>";
  html += '<p class="muted small">校验内容：枚举全部 (前命中 a, 后命中 b) 子情形组合数之和 = ' + fmtInt(sc.total_combinations) +
    "；中奖组合 " + fmtInt(sc.win_cases) + " + 未中奖组合 " + fmtInt(sc.lose_cases) +
    " = 总组合；计数法与公式法概率差 " + sc.p_win_abs_diff.toExponential(2) + "。</p>";
  html += '<p class="muted">每个 5+2 组合的一等奖中奖概率恒为 <b>1/' + fmtInt(cc.total) +
    '</b>（约 ' + (1 / res.prizes["一等奖"].probability).toExponential(3) + '），与投注方式、金额、历史数据无关。</p></div>';

  /* 奖级表 */
  html += '<div class="card"><h2>九个奖级理论中奖概率（超几何分布精确计算）</h2><div class="table-wrap"><table class="data-table">' +
    "<thead><tr><th>奖级</th><th>命中要求（前区+后区）</th><th>组合数</th><th>概率</th><th>约</th></tr></thead><tbody>";
  PRIZE_ORDER.forEach(function (name) {
    var p = res.prizes[name];
    var req = p.cases.map(function (c) { return "前" + c[0] + "后" + c[1]; }).join(" + ");
    html += "<tr><td>" + name + "</td><td>" + req + "</td><td>" + fmtInt(p.count) +
      "</td><td>" + fmtSci(p.probability) + "</td><td>" + fmtOneIn(p.probability) + "</td></tr>";
  });
  html += "</tbody></table></div>";
  html += '<p class="muted small">八等奖含“前3后1、前2后2”两个互斥子情形；九等奖含“前3后0、前1后2、前2后1、前0后2”四个互斥子情形，概率为子情形之和。</p></div>';

  /* 期望值计算器 */
  html += '<div class="card"><h2>期望值与返奖率计算器</h2>';
  html += '<p class="warn-inline">以下奖金为<b>示例/可配置假设值，非官方承诺</b>。高奖级奖金实际为浮动奖金（与销量、奖池有关），修改奖金只影响期望值测算，不影响中奖概率。单注成本 2 元。</p>';
  html += '<table class="data-table" style="margin-top:10px"><thead><tr><th>奖级</th><th>中奖概率</th><th>单注奖金（元，可编辑）</th><th>期望贡献（元）</th></tr></thead><tbody id="ev-tbody">';
  PRIZE_ORDER.forEach(function (name) {
    var pp = ev.per_prize[name];
    html += "<tr><td>" + name + "</td><td>" + fmtSci(pp.probability) +
      '</td><td><input type="number" min="0" step="any" class="num-input ev-input" data-prize="' +
      name + '" value="' + pp.amount + '"></td><td class="ev-contrib" data-prize="' + name + '">' +
      fmtFixed(pp.expectation_contribution, 8) + "</td></tr>";
  });
  html += "</tbody></table>";
  html += '<div class="btn-row"><button id="btn-recalc" class="btn primary">按自定义奖金重新计算</button>' +
    '<span class="muted small">修改上方奖金后点击重算（POST /api/probability）</span></div>';
  html += '<div id="ev-summary"></div></div>';

  html += '<div class="conclusion"><b>结论解读：</b>在示例奖金下，每 2 元投注的期望毛回报约 ' +
    fmtFixed(ev.gross_return_per_bet, 4) + " 元，净期望 " + fmtFixed(ev.expected_value_per_bet, 4) +
    " 元（期望亏损 " + fmtFixed(ev.expected_loss_per_bet, 4) + " 元）；每 1 元期望回报 " +
    fmtFixed(ev.expected_return_per_yuan, 4) + " 元，即期望返奖率约 " + fmtPct(ev.return_rate) +
    "（官方规定约 51%）。长期看购彩必然期望亏损，彩票是娱乐消费而非投资。<b>置信度：高</b>（精确概率计算）。" +
    "<b>适用局限：</b>返奖率取决于假设的奖金结构，浮动奖金使实际单期返奖率波动很大。</div>";

  el("probability-body").innerHTML = html;
  renderEvSummary(ev);
  el("btn-recalc").addEventListener("click", recalcEv);
}

function renderEvSummary(ev) {
  el("ev-summary").innerHTML = '<div class="stat-grid">' +
    statBox("每注期望毛回报", fmtFixed(ev.gross_return_per_bet, 6) + " 元") +
    statBox("每注净期望值", fmtFixed(ev.expected_value_per_bet, 6) + " 元", "warn") +
    statBox("每 1 元期望回报", fmtFixed(ev.expected_return_per_yuan, 6) + " 元") +
    statBox("期望返奖率", fmtPct(ev.return_rate)) +
    statBox("每注期望亏损", fmtFixed(ev.expected_loss_per_bet, 6) + " 元", "warn") +
    statBox("官方返奖率参考", fmtPct(ev.official_return_rate_reference, 0)) +
    "</div>";
  PRIZE_ORDER.forEach(function (name) {
    var cell = document.querySelector('.ev-contrib[data-prize="' + name + '"]');
    if (cell && ev.per_prize[name]) cell.textContent = fmtFixed(ev.per_prize[name].expectation_contribution, 8);
  });
}

async function recalcEv() {
  var btn = el("btn-recalc");
  setBtnLoading(btn, true, "重算中…");
  try {
    var body = {};
    var ok = true;
    document.querySelectorAll(".ev-input").forEach(function (inp) {
      var v = parseFloat(inp.value);
      if (isNaN(v) || v < 0) { ok = false; }
      body[inp.dataset.prize] = v;
    });
    if (!ok) { toast("奖金输入无效：请输入非负数值。"); return; }
    var res = await api("/api/probability", { method: "POST", body: body });
    renderEvSummary(res.expected_value);
    toast("已按自定义奖金重算：期望返奖率 " + fmtPct(res.expected_value.return_rate));
  } catch (e) {
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

/* ============ Tab 4: 随机性检验 ============ */
async function loadRandomness() {
  if (!datasetLoaded) {
    el("randomness-body").innerHTML = notLoadedHint();
    return;
  }
  var btn = el("btn-randomness");
  setBtnLoading(btn, true, "检验计算中…");
  el("randomness-error").textContent = "";
  el("randomness-body").innerHTML = '<div class="card"><p class="muted">随机性检验计算中（含蒙特卡洛模拟，约需数秒）…</p></div>';
  try {
    var trials = parseInt(el("rnd-trials").value, 10) || 20000;
    var seed = parseInt(el("rnd-seed").value, 10) || 20240920;
    var res = await api("/api/randomness?mc_trials=" + trials + "&seed=" + seed);
    renderRandomness(res);
  } catch (e) {
    el("randomness-body").innerHTML = "";
    el("randomness-error").textContent = e.message;
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

function chi2Card(title, t) {
  var verdict = t.reject_null
    ? '<span class="badge fail">拒绝均匀分布假设</span>'
    : '<span class="badge pass">不拒绝均匀分布假设</span>';
  return '<div class="stat-box"><div class="v">' + fmtFixed(t.chi2, 4) + '</div><div class="k">' +
    title + " χ²（df=" + t.df + "）</div></div>" +
    '<div class="stat-box"><div class="v">' + fmtFixed(t.p_value, 6) + '</div><div class="k">' +
    title + " 渐近 p 值</div></div>" +
    '<div class="stat-box"><div class="v" style="font-size:14px;padding-top:5px">' + verdict +
    '</div><div class="k">' + title + " 结论（α=" + t.alpha + "）</div></div>";
}

function renderRandomness(res) {
  var r = res.result;
  var mc = r.monte_carlo;
  var html = "";

  html += '<div class="card"><h2>卡方拟合优度检验</h2><div class="stat-grid">' +
    chi2Card("前区(35号)", r.chi2_front) + chi2Card("后区(12号)", r.chi2_back) + "</div>";
  html += '<p class="muted small">注：每期前区 5 个号互不重复，号码计数间存在负相关，χ²(k−1) 仅是渐近近似参照（均值偏大）；精确参照以下方蒙特卡洛经验分布为准。</p></div>';

  html += '<div class="card"><h2>单号二项检验 + 多重比较校正</h2>';
  html += '<p class="muted small">同时检验 35（前区）/ 12（后区）个号码，未校正的多次检验会放大第一类错误，因此必须做 Bonferroni 或 Benjamini–Hochberg FDR 校正。</p>';
  html += binomBlock("前区", r.binomial_front, 35);
  html += binomBlock("后区", r.binomial_back, 12);
  html += "</div>";

  html += '<div class="card"><h2>蒙特卡洛模拟（经验 p 值）</h2>';
  html += '<div class="stat-grid">' +
    statBox("模拟期数", fmtInt(mc.trials)) +
    statBox("分块", mc.blocks + " 块 × " + mc.block_size + " 期") +
    statBox("前区经验 p 值", fmtFixed(mc.empirical_p_value_front, 6)) +
    statBox("后区经验 p 值", fmtFixed(mc.empirical_p_value_back, 6)) +
    "</div>";
  html += '<p class="muted small">经验 p 值定义：' + esc(mc.empirical_p_definition) +
    "。模拟前区 χ² 经验分布：均值 " + fmtFixed(mc.front_chi2_distribution.mean, 2) +
    "，p95=" + fmtFixed(mc.front_chi2_distribution.p95, 2) +
    "；历史前区 χ² = " + fmtFixed(mc.historical.front_chi2, 4) + "。</p>";
  html += '<div class="stat-grid">' +
    statBox("历史前区最大遗漏", mc.historical.front_max_missing + " 期") +
    statBox("模拟块最大遗漏均值", fmtFixed(mc.front_max_missing_distribution.mean, 2) + " 期") +
    statBox("模拟 ≥ 历史值比例", fmtPct(mc.max_missing_exceed_ratio)) +
    statBox("历史值分位", fmtPct(mc.max_missing_quantile)) +
    "</div>";
  html += '<p class="muted small">历史最大遗漏落在模拟分布的常规区间内，未见异常。</p></div>';

  html += '<div class="conclusion"><b>结论与局限：</b>在 α=0.05 下，卡方检验与校正后的二项检验均' +
    '<b>不拒绝</b>“号码均匀随机”的原假设；蒙特卡洛经验 p 值（前区 ' + fmtFixed(mc.empirical_p_value_front, 4) +
    "，后区 " + fmtFixed(mc.empirical_p_value_back, 4) + "）同样不拒绝。<b>不拒绝原假设 ≠ 证明开奖均匀</b>——" +
    "只能说明在当前样本量下没有检出显著偏离，结论受样本量限制，且不能预测未来任何一期结果。<b>置信度：高</b>（对“未检出显著偏离”这一陈述）；" +
    "<b>适用局限：</b>检验功效受期数限制；更换数据集或样本量后结论可能变化。</div>";

  el("randomness-body").innerHTML = html;
}

function binomBlock(title, b, size) {
  var sigCount = (b.fdr_reject || []).filter(Boolean).length;
  var sigNums = (b.significant_indices || []).map(function (i) { return i + 1; });
  var pairs = [];
  for (var i = 0; i < b.raw_p_values.length; i++) pairs.push([i + 1, b.raw_p_values[i], b.bh_adjusted_p_values[i]]);
  pairs.sort(function (a, c) { return a[1] - c[1]; });
  var top3 = pairs.slice(0, 3).map(function (p) {
    return "号码 " + p[0] + "：原始 p=" + fmtFixed(p[1], 6) + " → BH 校正 p=" + fmtFixed(p[2], 6);
  }).join("；");
  return "<h3>" + title + "（k=" + b.k + "，单号命中概率 " + fmtFixed(b.p_hit, 6) + "）</h3>" +
    '<div class="stat-grid">' +
    statBox("Bonferroni 阈值", fmtFixed(b.bonferroni_alpha, 8)) +
    statBox("Bonferroni 显著号码", (b.bonferroni_reject || []).filter(Boolean).length + " 个") +
    statBox("FDR 显著号码", sigCount + " 个", sigCount > 0 ? "warn" : "ok") +
    "</div>" +
    '<p class="muted small">FDR 显著号码：' + (sigNums.length ? sigNums.join(", ") : "无（校正后无单号显著偏离）") +
    "。原始 p 值最小的 3 个号码：" + top3 + "。</p>";
}

/* ============ Tab 5: 参考号码 ============ */
async function loadGenerate() {
  if (!datasetLoaded) {
    el("generate-body").innerHTML = notLoadedHint();
    return;
  }
  var btn = el("btn-generate");
  setBtnLoading(btn, true, "生成中…");
  el("generate-error").textContent = "";
  el("generate-body").innerHTML = '<div class="card"><p class="muted">号码生成中…</p></div>';
  try {
    var count = parseInt(el("gen-count").value, 10) || 5;
    var strategy = el("gen-strategy").value;
    var seed = parseInt(el("gen-seed").value, 10) || 20240920;
    var res = await api("/api/generate?count=" + count + "&strategy=" + strategy + "&seed=" + seed);
    renderGenerate(res);
  } catch (e) {
    el("generate-body").innerHTML = "";
    el("generate-error").textContent = e.message;
    toast(e.message);
  } finally {
    setBtnLoading(btn, false);
  }
}

function genGroup(title, g) {
  var html = '<div class="gen-group"><div class="chart-title">' + title + "</div>";
  html += '<div class="numbers">前区：' + g.front.map(function (n) { return ballHTML(n, "front"); }).join("") +
    "&nbsp;&nbsp;后区：" + g.back.map(function (n) { return ballHTML(n, "back"); }).join("") + "</div>";
  html += '<p class="muted small">和值 = ' + g.sum + "；奇偶比 = " + g.odd_even + "；大小比 = " + g.big_small +
    (g.zones_covered !== undefined ? "；覆盖区间 = " + g.zones_covered + "/5" : "") + "</p>";
  html += '<ul class="basis">' + g.basis.map(function (b) { return "<li>" + esc(b) + "</li>"; }).join("") + "</ul></div>";
  return html;
}

function renderGenerate(res) {
  var r = res.result;
  var html = '<div class="card"><h2>参考号码（' + esc(r.strategy) + "，共 " + r.count + " 组）</h2>";
  html += '<p class="warn-inline">' + esc(r.disclaimer) + "</p>";
  if (r.hot_weighted) {
    html += "<h3>策略一：hot_weighted（热号加权）</h3>";
    r.hot_weighted.forEach(function (g, i) { html += genGroup("第 " + (i + 1) + " 组", g); });
  }
  if (r.balanced_profile) {
    html += "<h3>策略二：balanced_profile（形态匹配）</h3>";
    r.balanced_profile.forEach(function (g, i) { html += genGroup("第 " + (i + 1) + " 组", g); });
  }
  if (r.comparison) {
    html += '<div class="conclusion"><b>策略对比：</b>' + esc(r.comparison) + "</div>";
  }
  html += '<div class="conclusion"><b>再次强调：</b>统计依据不改变任何单个组合的中奖概率（恒为 1/21,425,712）；' +
    "以上号码不具备预测能力，不得作为投注依据。理性购彩，量力而行。</div></div>";
  el("generate-body").innerHTML = html;
}

/* ============ 初始化 ============ */
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".tab-btn").forEach(function (b) {
    b.addEventListener("click", function () { activateTab(b.dataset.tab); });
  });
  el("btn-sample").addEventListener("click", loadSample);
  el("btn-upload").addEventListener("click", uploadCsv);
  el("btn-describe").addEventListener("click", function () { loadDescribe(); });
  el("btn-probability").addEventListener("click", function () { loadProbability(); });
  el("btn-randomness").addEventListener("click", function () { loadRandomness(); });
  el("btn-generate").addEventListener("click", function () { loadGenerate(); });
  checkHealth();
});
