/** -*- coding: utf-8 -*- */
/** 持仓管理 · 客户工具 —— 前端主逻辑 */

const API = '';
const MKT_CN = { sh: '沪市', sz: '深市', bj: '北交所' };
const MKT_COLOR = { sh: '#3b82f6', sz: '#10b981', bj: '#f59e0b' };
let pool = [];           // 标的池
let holdings = [];       // 当前持仓
let poolMap = {};        // code -> {name, industry, market}

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

async function fetchJSON(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const e = await r.json(); msg = e.error || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}

// ==================== 时钟 ====================
function tick() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  $('#clock').textContent = `${now.getFullYear()}/${now.getMonth()+1}/${now.getDate()} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
setInterval(tick, 1000);

// ==================== 标的池 ====================
async function loadPool() {
  const cls = $('#poolCls').value;
  const d = await fetchJSON(`${API}/api/pool?cls=${cls}`);
  pool = d.items;
  poolMap = {};
  for (const p of pool) poolMap[p.code] = p;
  $('#poolCount').textContent = pool.length;
  const dl = $('#poolList');
  dl.innerHTML = '';
  for (const p of pool) {
    const opt = document.createElement('option');
    opt.value = `${p.code} ${p.name}`;
    dl.appendChild(opt);
  }
}

// ==================== 持仓 ====================
async function loadHoldings() {
  const d = await fetchJSON(`${API}/api/holdings`);
  holdings = d.items;
  renderHoldings();
}

function renderHoldings() {
  $('#holdCount').textContent = holdings.length;
  const tb = $('#holdTable');
  tb.innerHTML = holdings.length ? holdings.map(h => {
    const m = poolMap[h.code] || {};
    const mk = h.code.startsWith('920') || h.code.startsWith('8') || h.code.startsWith('4') ? 'bj'
             : h.code.startsWith('60') || h.code.startsWith('68') || h.code.startsWith('90') ? 'sh' : 'sz';
    return `<tr data-code="${h.code}">
      <td><b>${h.code}</b> ${h.name || m.name || ''}</td>
      <td class="num">${(+h.amount||0).toLocaleString()}</td>
      <td>${h.dingtou ? '<span class="tag tag-up">定投</span>' : '—'}</td>
      <td>${h.date || '—'}</td></tr>`;
  }).join('') : '<tr><td colspan="4" class="empty" style="padding:14px">暂无持仓</td></tr>';
}

function selectedCodes() {
  return [...$$('#holdTable tr[data-code].selected')].map(tr => tr.dataset.code);
}

// ==================== 添加/删除持仓 ====================
async function addHolding() {
  const raw = $('#poolInput').value.trim();
  if (!raw) { alert('请先输入/选择标的'); return; }
  const code = (raw.match(/\d{6}/) || [raw.split(' ')[0]])[0];
  if (!poolMap[code]) { alert(`标的 ${code} 不在池中`); return; }
  const amount = parseFloat($('#holdAmount').value) || 0;
  const dingtou = $('#holdDingtou').checked;
  try {
    await fetchJSON(`${API}/api/holdings`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ code, amount, dingtou })
    });
    $('#poolInput').value = '';
    await loadHoldings();
    await renderCards();
  } catch (e) { alert(e.message); }
}

async function delHoldings() {
  const codes = selectedCodes();
  if (!codes.length) { alert('请先勾选要删除的持仓（点击表格行选中）'); return; }
  if (!confirm(`删除 ${codes.length} 条持仓？`)) return;
  await fetchJSON(`${API}/api/holdings/delete`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ codes })
  });
  await loadHoldings();
  await renderCards();
}

// ==================== 设置 ====================
async function loadSettings() {
  const s = await fetchJSON(`${API}/api/settings`);
  $('#setWeekly').value = s.weekly;
  $('#setNewpos').value = s.newpos;
  $('#setAutoTrack').checked = !!s.auto_track;
  $('#autoTrack').checked = !!s.auto_track;
}

async function saveSettings() {
  await fetchJSON(`${API}/api/settings`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      weekly: parseFloat($('#setWeekly').value) || 0,
      newpos: parseFloat($('#setNewpos').value) || 0,
      auto_track: $('#setAutoTrack').checked
    })
  });
}

// ==================== 保存并分析 ====================
let pollTimer = null;

async function doAnalyze() {
  await saveSettings();
  const forceRefresh = $('#forceRefresh').checked;
  const autoTrack = $('#autoTrack').checked;
  $('#btnAnalyze').disabled = true;
  setProgress('running', 2, '提交分析...');
  try {
    await fetchJSON(`${API}/api/analyze`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ force_refresh: forceRefresh, auto_track: autoTrack })
    });
    pollTimer = setInterval(pollAnalyze, 1500);
    pollAnalyze();
  } catch (e) {
    alert(e.message); setProgress('idle', 0, '等待');
    $('#btnAnalyze').disabled = false;
  }
}

async function pollAnalyze() {
  try {
    const s = await fetchJSON(`${API}/api/analyze/status`);
    $('#statusText').textContent = s.running ? s.message : (s.result ? '分析完成' : '就绪');
    setProgress(s.running ? 'running' : (s.percent >= 100 ? 'done' : 'idle'),
                s.percent || 0, s.running ? s.message : (s.percent >= 100 ? '完成' : '等待'));
    if (!s.running) {
      clearInterval(pollTimer); pollTimer = null;
      $('#btnAnalyze').disabled = false;
      if (s.result) { await renderAll(s.result); }
      else if (s.message && s.message.includes('异常')) { setProgress('error', 0, '异常'); }
    }
  } catch (e) {
    clearInterval(pollTimer); pollTimer = null;
    $('#btnAnalyze').disabled = false;
  }
}

function setProgress(state, pct, label) {
  const w = $('.progress-wrap');
  w.classList.remove('running', 'done', 'error');
  w.classList.add(state);
  $('#progressFill').style.width = (pct || 0) + '%';
  $('#progressState').textContent = label || '';
}

// ==================== 渲染: 持仓操作卡 ====================
function adviceTag(a) {
  const map = { '加仓': 'advice-buy', '买入': 'advice-buy', '持有': 'advice-hold', '减仓': 'advice-cut', '清仓': 'advice-cut', '观望': 'advice-watch' };
  return `<span class="tag ${map[a] || 'advice-watch'}">${a}</span>`;
}

async function renderCards() {
  await loadHoldings(); // 先同步本地持仓,避免显示已删除的持仓
  try {
    const s = await fetchJSON(`${API}/api/analyze/status`);
    if (s.result) renderCardTable(s.result);
    else showCardEmpty('请先 [保存并分析]');
  } catch (e) { showCardEmpty('加载失败: ' + (e.message || e)); }
}

function showCardEmpty(msg) {
  $('#cardTable').innerHTML = '';
  $('#cardEmpty').style.display = 'block';
  $('#cardEmpty').textContent = msg;
  $('#cardSignal').textContent = '';
}

function renderCardTable(res) {
  // 交叉校验: cards 里的 code 必须仍在当前 holdings 里, 否则过滤掉
  const heldCodes = new Set(holdings.map(h => h.code));
  const cards = (res.cards || []).filter(c => heldCodes.has(c.code));
  $('#cardSignal').textContent = cards.length
    ? `信号日 ${res.signal_date} · ${res.summary.regime_cn} · 持仓 ${cards.length} 只 / 池 ${res.summary.buy_pool} 只`
    : '';
  if (!cards.length) {
    showCardEmpty('暂无持仓，请先在左侧录入或直接 [保存并分析]');
    return;
  }
  $('#cardEmpty').style.display = 'none';
  const tb = $('#cardTable');
  tb.innerHTML = cards.map(c => {
    const mk = c.market || (c.code.startsWith('920')||c.code.startsWith('8')||c.code.startsWith('4') ? 'bj'
             : c.code.startsWith('60')||c.code.startsWith('68')||c.code.startsWith('90') ? 'sh' : 'sz');
    const score = c.score != null ? c.score : (c.amount ? 50 : 30);
    return `<tr>
      <td><b>${c.code}</b></td><td>${c.name}</td><td>${c.industry || '—'}</td>
      <td><span class="mkt" style="background:${MKT_COLOR[mk]}">${MKT_CN[mk]}</span></td>
      <td class="num"><b>${score.toFixed(0)}</b></td>
      <td>${adviceTag(c.advice)}</td><td>${c.action || '—'}</td><td style="color:#6b7280">${c.desc}</td></tr>`;
  }).join('');
}

// ==================== 渲染: 本周推荐 ====================
function renderRecs(res) {
  const selected = res.selected_recommends || [];
  const others = res.recommends || [];
  $('#recEmpty').style.display = (selected.length || others.length) ? 'none' : 'block';

  // 已选中的 4 只按"持仓→分数"再排一次（保证稳定）
  const sortFn = (a, b) => (a.held ? 0 : 1) - (b.held ? 0 : 1) || b.score - a.score;
  selected.sort(sortFn);

  let html = '';
  // ⭐ 本周最值得买入（selected = 模型最该买的 N 只，已过资金可行性筛选）
  if (selected.length) {
    html += '<tr class="rec-section"><td colspan="8">⭐ <b>本周最值得买入</b>（已通过<b>资金可行性筛选</b> + 模型评分——价格×100 ≤ 单仓预算，<span style="color:#b91c1c;font-weight:600">整行标红</span>）</td></tr>';
    html += selected.map(c => renderRecRow(c, true)).join('');
  }
  // 📋 更多候选（buy 池其余高分票，因价格超单仓预算暂落选）
  if (others.length) {
    html += '<tr class="rec-section"><td colspan="8">📋 <b>更多候选</b>（评分高但因<b>价格超出单仓预算</b>暂未入精选——可考虑加大资金或减仓换票）</td></tr>';
    html += others.map(c => renderRecRow(c, false)).join('');
  }
  $('#recTable').innerHTML = html;
}

function renderRecRow(c, isTop) {
  const mk = c.market || (c.code.startsWith('920')||c.code.startsWith('8')||c.code.startsWith('4') ? 'bj'
           : c.code.startsWith('60')||c.code.startsWith('68')||c.code.startsWith('90') ? 'sh' : 'sz');
  const rowCls = isTop ? 'rec-top' : 'rec-buy';
  const star = isTop ? '<span class="tag tag-star">⭐精选</span>' : '';
  const heldTag = c.held ? '<span class="tag tag-held">已持仓</span>' : '';
  // 资金可行性提示: 精选显示预算占比, 更多候选显示超预算标签
  let budgetTag = '';
  if (c.one_hand != null) {
    if (isTop && c.fea_ratio != null) {
      budgetTag = `<span class="tag tag-budget" title="一手 ${c.one_hand.toFixed(0)}元 ÷ 单仓预算">占预算 ${c.fea_ratio.toFixed(0)}%</span>`;
    } else if (!isTop && c.fea_ratio > 100) {
      budgetTag = `<span class="tag tag-over">超预算 ${(c.fea_ratio - 100).toFixed(0)}%</span>`;
    }
  }
  return `<tr class="${rowCls}">
    <td><b>${c.code}</b>${star}${heldTag}${budgetTag}</td>
    <td>${c.name}</td><td>${c.industry || '—'}</td>
    <td><span class="mkt" style="background:${MKT_COLOR[mk]}">${MKT_CN[mk]}</span></td>
    <td class="num score-buy">${c.score.toFixed(0)}</td>
    <td>${adviceTag(c.advice)}</td><td>${c.action || '—'}</td><td style="color:#6b7280">${c.desc}</td></tr>`;
}

// ==================== 渲染: 调仓记录 ====================
async function renderActions() {
  try {
    const d = await fetchJSON(`${API}/api/action_log`);
    const items = d.items || [];
    $('#actionEmpty').style.display = items.length ? 'none' : 'block';
    const rows = [];
    for (const a of items) {
      for (const it of a.items || []) {
        rows.push(`<tr><td>${a.ts}</td><td>${a.signal}</td><td><b>${it.code}</b> ${it.name}</td>
          <td>${adviceTag(it.op)}</td><td style="color:#6b7280">${it.detail}</td></tr>`);
      }
    }
    $('#actionTable').innerHTML = rows.join('') || '';
  } catch (_) {}
}

// ==================== 渲染: 历史回测 ====================
let annChart, shpChart, nvChart;
async function renderBacktest() {
  try {
    const bt = await fetchJSON(`${API}/api/backtest`);
    const schemes = [
      { label: 'current(上证)', key: 'current_全样本1996+' },
      { label: 'A(全指)', key: 'A_全样本1996+' },
      { label: 'B(分市场段)', key: 'B_全样本1996+' },
      { label: 'C(内生)', key: 'C_全样本1996+' },
      { label: 'E(尾部)', key: 'E_全样本1996+' },
    ];
    const labels = schemes.map(s => s.label);
    const ann = schemes.map(s => (bt[s.key]?.annualized || 0) * 100);
    const shp = schemes.map(s => bt[s.key]?.sharpe || 0);
    const colors = ann.map(v => v >= 0 ? '#10b981' : '#ef4444');

    const mk = (ctxId, data, fmt, old) => {
      if (old) old.destroy();
      return new Chart(document.getElementById(ctxId), {
        type: 'bar',
        data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: 4 }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false },
            tooltip: { callbacks: { label: c => fmt(c.raw) } } },
          scales: {
            x: { grid: { display: false }, ticks: { color: '#6b7280', font: { size: 11 } } },
            y: { grid: { color: '#f3f4f6' }, ticks: { color: '#6b7280' } }
          }
        }
      });
    };
    annChart = mk('annChart', ann, v => v.toFixed(1) + '%', annChart);
    shpChart = mk('shpChart', shp, v => v.toFixed(2), shpChart);

    let rows = '';
    for (const s of schemes) {
      const r = bt[s.key];
      if (!r) continue;
      const tag = s.key === 'current_全样本1996+' ? ' <span class="tag tag-mid">历史最优(基准)</span>'
                : (s.key === 'B_全样本1996+' ? ' <span class="tag tag-up">修复后≈基准</span>' : '');
      rows += `<tr><td>${s.label}${tag}</td><td class="num">${(r.annualized*100).toFixed(1)}%</td>
        <td class="num">${r.sharpe.toFixed(2)}</td>
        <td class="num" style="color:#dc2626">${(r.max_drawdown*100).toFixed(0)}%</td>
        <td class="num">${(r.empty_frac*100).toFixed(0)}%</td>
        <td class="num">${(r.avg_turnover*100).toFixed(0)}%</td></tr>`;
    }
    $('#btTable').innerHTML = `<table style="margin-top:10px"><thead>
      <tr><th>方案</th><th class="num">年化</th><th class="num">夏普</th><th class="num">最大回撤</th>
      <th class="num">空仓占比</th><th class="num">换手</th></tr></thead><tbody>${rows}</tbody></table>`;

    // 净值曲线
    try {
      const curves = await fetchJSON(`${API}/api/curves`);
      const bk = curves['B_全样本1996+'];
      const ck = curves['current_全样本1996+'];
      if (bk) {
        const labels = bk.dates.map(d => {
          const s = String(d);
          return s.slice(0,4) + '-' + s.slice(4,6) + '-' + s.slice(6,8);
        });
        const datasets = [{
          label: 'B(分市场段)', data: bk.equity,
          borderColor: '#2ecc71', borderWidth: 2, fill: false, pointRadius: 0,
        }];
        if (ck) datasets.push({
          label: 'current(上证)', data: ck.equity,
          borderColor: '#4aa3ff', borderWidth: 1.5, fill: false, pointRadius: 0,
        });
        if (nvChart) nvChart.destroy();
        nvChart = new Chart(document.getElementById('curveChart'), {
          type: 'line',
          data: { labels, datasets },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
              legend: { position: 'top', align: 'start',
                labels: { color: '#374151', font: { size: 11 }, boxWidth: 14, padding: 12 } },
              tooltip: { mode: 'index', intersect: false,
                callbacks: { label: c => c.dataset.label + ': ' + c.parsed.y.toFixed(2) + 'x' } }
            },
            scales: {
              x: {
                grid: { color: '#f3f4f6' },
                ticks: {
                  color: '#6b7280', font: { size: 10 },
                  maxTicksLimit: 12,
                  callback: (v, i) => { const a = labels[i]; return (a && a.endsWith('-01-01')) ? a.slice(0,4) : ''; }
                }
              },
              y: { type: 'logarithmic', grid: { color: '#f3f4f6' },
                ticks: { color: '#6b7280', callback: v => v.toFixed(1) + 'x' } }
            }
          }
        });
      }
    } catch (e) {
      console.warn('净值曲线加载失败:', e);
    }
  } catch (e) {
    console.error('renderBacktest 失败:', e);
    const pane = $('#pane-bt');
    if (pane) pane.insertAdjacentHTML('afterbegin',
      '<div class="warn" style="margin-bottom:10px">回测数据加载失败：' + (e.message || e) + '</div>');
  }
}

// ==================== 下载工具 ====================
function triggerDownload(url, filename) {
  // 用隐藏 <a download> 触发下载, 不打开新窗口(避免跳页报错)
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || '';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => a.remove(), 100);
}

// ==================== MD 报告 & 日志 ====================
async function mdPreview() {
  try {
    const r = await fetch(`${API}/api/report/md`);
    if (!r.ok) { const e = await r.json(); alert(e.error || '请先保存并分析'); return; }
    $('#mdPreview').textContent = await r.text();
  } catch (e) { alert(e.message); }
}

async function logRefresh() {
  try {
    const d = await fetchJSON(`${API}/api/logs`);
    window._logCache = d.items || [];
    renderLog(window._logCache);
  } catch (e) {
    $('#logBox').innerHTML = '<div class="empty">日志加载失败: ' + (e.message || e) + '</div>';
  }
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function parseLogLevel(msg) {
  if (/异常|失败|错误|Error|fail|traceback/i.test(msg)) return 'error';
  if (/警告|Warn|warning/i.test(msg)) return 'warn';
  if (/完成|成功|已写|加载|缓存|Done|OK/i.test(msg)) return 'success';
  return 'info';
}

function parseLogLine(line) {
  // 格式: [2026-08-09 23:10:00] 消息...
  const m = line.match(/^\[([^\]]+)\]\s*(.*)$/);
  if (!m) return { ts: '', level: parseLogLevel(line), msg: line };
  return { ts: m[1], level: parseLogLevel(m[2]), msg: m[2] };
}

function renderLog(items) {
  const parsed = items.map(parseLogLine);
  // 统计
  const counts = { info: 0, success: 0, warn: 0, error: 0 };
  for (const l of parsed) counts[l.level] = (counts[l.level] || 0) + 1;
  $('#logStats').innerHTML =
    `<span>总计 <b>${parsed.length}</b> 条</span>` +
    `<span class="success">成功 <b>${counts.success}</b></span>` +
    `<span class="warn">警告 <b>${counts.warn}</b></span>` +
    `<span class="err">错误 <b>${counts.error}</b></span>` +
    `<span>最后: <b>${parsed.length ? parsed[parsed.length - 1].ts : '--'}</b></span>`;

  // 筛选
  const filter = $('#logFilter').value || 'all';
  const visible = filter === 'all' ? parsed : parsed.filter(l => l.level === filter);

  if (!visible.length) {
    $('#logBox').innerHTML = '<div class="empty">无匹配的日志条目</div>';
    return;
  }

  // 渲染: 最新在最上面
  $('#logBox').innerHTML = visible.slice().reverse().map(l =>
    `<div class="log-line ${l.level}">` +
    `<span class="ts">${escapeHtml(l.ts)}</span>` +
    `<span class="lvl">${l.level.toUpperCase()}</span>` +
    `<span class="msg">${escapeHtml(l.msg)}</span></div>`
  ).join('');
}

// ==================== Tabs ====================
function initTabs() {
  $$('.tab').forEach(t => t.addEventListener('click', () => {
    $$('.tab').forEach(x => x.classList.remove('active'));
    $$('.tab-pane').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    $('#pane-' + t.dataset.tab).classList.add('active');
    // 懒加载：切到历史回测时才画 Chart.js（避免在 hidden canvas 上画图失败）
    if (t.dataset.tab === 'bt' && !window._btRendered) {
      window._btRendered = true;
      renderBacktest();
    }
  }));
  // 持仓表格行选中
  $('#holdTable').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-code]');
    if (tr) tr.classList.toggle('selected');
  });
  // 分栏过滤
  $('#poolCls').addEventListener('change', loadPool);
  // 自动跟踪联动
  $('#autoTrack').addEventListener('change', () => $('#setAutoTrack').checked = $('#autoTrack').checked);
  $('#setAutoTrack').addEventListener('change', () => $('#autoTrack').checked = $('#setAutoTrack').checked);
}

// ==================== 全量渲染 ====================
async function renderAll(res) {
  await loadHoldings();
  renderCardTable(res);  // renderCardTable 内部会做 holdings 交叉校验
  renderRecs(res);
  await renderActions();
  // 切到历史回测 tab 才画图；强制重画（reset flag）
  window._btRendered = false;
  if ($$('.tab.active')[0]?.dataset?.tab === 'bt') {
    window._btRendered = true;
    renderBacktest();
  }
}

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  tick();
  try {
    await loadPool();
    await loadHoldings();
    await loadSettings();
    await renderCards();
    await renderActions();
    logRefresh();
  } catch (e) {
    $('#statusText').textContent = '初始化失败: ' + e.message;
  }

  $('#btnAdd').addEventListener('click', addHolding);
  $('#btnDel').addEventListener('click', delHoldings);
  $('#btnAnalyze').addEventListener('click', doAnalyze);
  $('#btnReport').addEventListener('click', () => window.open('/report/latest', '_blank'));
  $('#btnOpenHtml').addEventListener('click', () => window.open('/report/latest', '_blank'));
  $('#btnLog').addEventListener('click', () => { $$('.tab').forEach(x => x.classList.remove('active')); $$('.tab-pane').forEach(x => x.classList.remove('active')); $$('.tab[data-tab=log]')[0].classList.add('active'); $('#pane-log').classList.add('active'); logRefresh(); });
  $('#btnMdDownload').addEventListener('click', () => triggerDownload(`${API}/api/report/md?download=1`, 'report.md'));
  $('#btnMdPreview').addEventListener('click', mdPreview);
  $('#btnLogDownload').addEventListener('click', () => triggerDownload(`${API}/api/logs/download`, 'analyze.log'));
  $('#btnLogRefresh').addEventListener('click', logRefresh);
  $('#btnLogCopy').addEventListener('click', async () => {
    try {
      const d = await fetchJSON(`${API}/api/logs`);
      const text = (d.items || []).join('\n');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); ta.remove();
      }
      const tip = document.createElement('div');
      tip.className = 'toast'; tip.textContent = `已复制 ${d.items.length} 行日志`;
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 1800);
    } catch (e) { alert('复制失败: ' + e.message); }
  });
  $('#logFilter').addEventListener('change', () => {
    // 复用已有内存缓存避免重复请求
    if (window._logCache) renderLog(window._logCache);
    else logRefresh();
  });
});
