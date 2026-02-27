'use strict';

/* ── State ─────────────────────────────────────────────── */
let chart = null, intradayChart = null;
let refreshIntervalMs = 5000, refreshTimer = null;
let lastUpdateIssues = 0, lastConn = false;
let isUpdating = false, pendingUpdate = false;
let portfolioHistHash = null, intradayHash = null;
let pnlFilter = 'today';
let currentOrders = [], currentTrades = [];

/* ── Formatters ────────────────────────────────────────── */
const fmt    = (n, d=2) => (n==null||isNaN(n)) ? '-' : Number(n).toLocaleString('pl-PL',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtInt = (n)      => (n==null||isNaN(n)) ? '-' : Number(n).toLocaleString('pl-PL');
const price  = (n)      => (n==null||isNaN(n)) ? '-' : Number(n).toFixed(8);
const sign   = (n)      => n >= 0 ? '+' : '';

/* ── API ───────────────────────────────────────────────── */
async function api(url, options = {}) {
  try {
    const r = await fetch(url, options);
    let body;
    try { body = await r.json(); } catch (_) { body = { raw: await r.text() }; }
    if (!r.ok) {
      console.error(`API ${url} HTTP ${r.status}`, body);
      return { ok: false, _httpError: r.status, error: body?.error || body?.message || `HTTP ${r.status}`, ...body };
    }
    return body;
  } catch (e) {
    console.error(`Fetch error ${url}:`, e);
    return { ok: false, error: e.message || 'Network error' };
  }
}

async function safeApi(url, opts = {}) {
  const data = await api(url, opts);
  // ok = false gdy: null, _httpError, lub odpowiedź to obiekt z samym kluczem "error"
  const hasError = data == null || data?._httpError ||
    (data && typeof data === 'object' && !Array.isArray(data) &&
     Object.keys(data).length === 1 && 'error' in data);
  return { ok: !hasError, data: hasError && !Array.isArray(data) ? null : data };
}

/* ── Normalizers ───────────────────────────────────────── */
function normalizeRows(p, keys = []) {
  if (Array.isArray(p)) return p;
  if (!p || typeof p !== 'object') return [];
  for (const k of keys) { const v = p[k]; if (Array.isArray(v)) return v; }
  return [];
}
const normalizeHistory = p => normalizeRows(p, ['history','data','items','rows']);
const normalizeFills   = p => normalizeRows(p, ['fills','trades','data','items','rows']);

function normalizeTime(ts) {
  const d = ts ? new Date(ts) : null;
  return d && !isNaN(d) ? d.toLocaleTimeString() : '-';
}

function stableHash(v) { try { return JSON.stringify(v); } catch (_) { return String(v?.length||0); } }

/* ── Status ────────────────────────────────────────────── */
function updateStatus(on) {
  const dot = document.getElementById('statusIndicator');
  const txt = document.getElementById('statusText');
  if (on !== lastConn) {
    lastConn = on;
    dot?.classList.toggle('live', on);
    document.getElementById('statusIndicator2')?.classList.toggle('live', on);
  }
  const label = on ? (lastUpdateIssues ? `LIVE (${lastUpdateIssues}⚠)` : 'LIVE') : 'OFFLINE';
  if (txt) txt.textContent = label;
  const t2 = document.getElementById('statusText2'); if (t2) t2.textContent = label;
}

/* ── Refresh timer ─────────────────────────────────────── */
function resetRefreshTimer() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => { if (!document.hidden) update(); }, refreshIntervalMs);
}

function setRefreshInterval(ms) {
  refreshIntervalMs = Number(ms) || 5000;
  CountdownBar.start(refreshIntervalMs);
  resetRefreshTimer();
}

/* ── Charts ────────────────────────────────────────────── */
const chartDefaults = {
  responsive: true, maintainAspectRatio: false,
  animation: { duration: 700, easing: 'easeOutQuart' },
  plugins: {
    legend: { display: false },
  },
  scales: {
    x: { ticks: { color: '#4a5070', maxTicksLimit: 6, font: { family: "'JetBrains Mono'" }, maxRotation: 0 }, grid: { color: 'rgba(255,255,255,0.03)' } },
    y: { ticks: { color: '#4a5070', maxTicksLimit: 5, font: { family: "'JetBrains Mono'" } }, grid: { color: 'rgba(255,255,255,0.03)' } },
  },
};

function upsertLineChart(ref, canvasId, labels, data, borderColor, fillColor) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return ref;
  if (typeof window.Chart === 'undefined') { setTimeout(() => update(true), 500); return ref; }

  const wrap = canvas.closest?.('.chart-wrap');

  if (!ref) {
    const ctx = canvas.getContext('2d');
    ctx?.clearRect(0, 0, canvas.width, canvas.height);
    try {
      const c = new Chart(canvas, {
        type: 'line',
        data: { labels, datasets: [{ data, borderColor, borderWidth: 1.5,
          backgroundColor: fillColor || 'transparent', fill: !!fillColor,
          pointRadius: 0, tension: 0.4 }] },
        options: { ...chartDefaults,
          animation: { duration: 900, easing: 'easeOutCubic',
            onComplete: () => wrap?.classList.add('loaded') } },
      });
      return c;
    } catch (e) { console.warn('Chart error', canvasId, e); return null; }
  }

  ref.data.labels = labels;
  ref.data.datasets[0].data = data;
  ref.update('none');
  return ref;
}

/* ── Manual order panel ────────────────────────────────── */
function syncManualOrderType() {
  const t = document.getElementById('manualType')?.value;
  const inp = document.getElementById('manualPrice');
  if (!inp) return;
  const isLimit = t === 'LIMIT';
  inp.disabled = !isLimit;
  if (!isLimit) inp.value = '';
  inp.placeholder = isLimit ? 'Limit price' : 'N/A for market';
  inp.style.opacity = isLimit ? '1' : '.45';
}

function setQuickQty(pct) {
  const usdt = parseFloat((document.getElementById('usdtBalance')?.textContent||'0').replace(/\s/g,'').replace(',','.')) || 0;
  const px   = parseFloat((document.getElementById('price')?.textContent||'0').replace(',','.')) || 0.0000375;
  const qty  = (usdt * pct / 100) / px;
  const el   = document.getElementById('manualQty');
  if (el) { el.value = isFinite(qty) ? qty.toFixed(2) : ''; preflightManualOrder(); }
}

async function preflightManualOrder() {
  const payload = {
    side: document.getElementById('manualSide')?.value,
    type: document.getElementById('manualType')?.value,
    quantity: Number(document.getElementById('manualQty')?.value),
    price: Number(document.getElementById('manualPrice')?.value),
    reduce_only: document.getElementById('manualReduceOnly')?.checked,
  };
  const pre = await api('/api/orders/preflight', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  const el = document.getElementById('manualValidation');
  if (el) el.textContent = pre
    ? `min ${pre.min_qty} qty | notional ~${fmt(pre.estimated_notional_usdt,4)} | fee ~${fmt(pre.estimated_fee_usdt,6)} ${pre.confirm_required?'⚠ confirm req':''} ${(pre.errors||[]).join(' ')}`
    : 'Preflight failed';
  return pre;
}

async function submitManualOrder() {
  const payload = {
    side: document.getElementById('manualSide')?.value,
    type: document.getElementById('manualType')?.value,
    quantity: Number(document.getElementById('manualQty')?.value),
    price: Number(document.getElementById('manualPrice')?.value),
    reduce_only: document.getElementById('manualReduceOnly')?.checked,
  };
  const pre = await preflightManualOrder();
  if (pre?.confirm_required && !document.getElementById('manualConfirmMode')?.checked) {
    toast('⚠ Duże zlecenie — włącz Confirm mode'); return;
  }
  if (pre?.confirm_required) payload.confirm_token = pre.confirm_token;
  const res = await api('/api/orders/manual', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  const el = document.getElementById('manualOrderResult');
  if (el) el.textContent = res ? JSON.stringify(res).slice(0,160) : 'Error';
  toast(res?.ok ? '✓ Zlecenie wysłane' : `✗ ${res?.error||'Błąd zlecenia'}`);
  if (res?.ok) update();
}

async function cancelAllOrders() {
  const btn = document.getElementById('btnCancelAll');
  if (btn) { btn.disabled = true; btn.textContent = 'Anulowanie…'; }
  const res = await api('/api/orders/cancel-all', { method:'POST' });
  if (btn) { btn.disabled = false; btn.textContent = 'Cancel all'; }
  const el = document.getElementById('manualOrderResult');
  if (el) el.textContent = res?.ok ? `OK: ${JSON.stringify(res?.result||'').slice(0,100)}` : `Błąd: ${res?.error||''}`;
  toast(res?.ok ? '✓ Anulowano wszystkie zlecenia' : `✗ Cancel-all: ${res?.error||''}`);
  if (res?.ok) update();
}

async function syncTradesFromExchange() {
  const btn = document.getElementById('btnSyncTrades');
  if (btn) { btn.disabled = true; btn.textContent = 'Synchronizuję…'; }
  const res = await api('/api/trades/sync-from-exchange', { method:'POST' });
  if (btn) { btn.disabled = false; btn.textContent = 'Sync trades'; }
  const ok  = res?.status === 'success' || res?.ok;
  const msg = ok ? `✓ Zsynchronizowano ${res.added||0} tradów` : (res?.error || res?.message || '✗ Błąd sync');
  const el  = document.getElementById('manualOrderResult');
  if (el) el.textContent = msg;
  toast(msg);
  if (ok) update();
}

/* ── Automation rules ──────────────────────────────────── */
async function addAutomationRule() {
  const payload = {
    name:      document.getElementById('ruleName')?.value,
    condition: document.getElementById('ruleCondition')?.value,
    action:    document.getElementById('ruleAction')?.value,
  };
  await api('/api/automation-rules', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  ['ruleName','ruleCondition','ruleAction'].forEach(id => { const e = document.getElementById(id); if (e) e.value=''; });
  toast('Dodano regułę'); update();
}

async function addBuilderRule() {
  const payload = {
    name: document.getElementById('ruleName')?.value || 'Builder Rule',
    if:   { type: document.getElementById('ifType')?.value, operator: document.getElementById('ifOperator')?.value, value: document.getElementById('ifValue')?.value },
    then: { action: document.getElementById('thenAction')?.value },
    time_window: document.getElementById('ruleWindow')?.value || 'always',
  };
  const res = await api('/api/automation-rules/builder', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  toast(res?.ok ? '✓ Dodano regułę IF/THEN' : '✗ Błąd reguły IF/THEN');
  update();
}

/* ── Backtest ──────────────────────────────────────────── */
async function importBacktestData() {
  const res = await api('/api/backtest/import', { method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ dataset: document.getElementById('btDatasetInput')?.value||'manual_dataset', candles: Number(document.getElementById('btCandlesInput')?.value||0) }) });
  const el = document.getElementById('btCompare');
  if (el) el.textContent = res ? `Import: ${res.dataset}, candles=${res.candles}` : 'Failed';
}

async function compareConfigs() {
  const res = await api('/api/backtest/compare');
  const el  = document.getElementById('btCompare');
  if (!res || !el) return;
  el.textContent = `A PF ${res.config_a?.profit_factor} | B PF ${res.config_b?.profit_factor} | better: ${res.better}`;
}

/* ── Modal ─────────────────────────────────────────────── */
function showOrderDetails(idx) {
  const o = currentOrders[idx]; if (!o) return;
  openModal('Order Details',
    `<div class="modal-row"><span class="modal-label">ID</span><span class="modal-value">${o.id||'-'}</span></div>
     <div class="modal-row"><span class="modal-label">Side</span><span class="modal-value ${(o.side||'').toLowerCase()}">${o.side||'-'}</span></div>
     <div class="modal-row"><span class="modal-label">Quantity</span><span class="modal-value">${fmtInt(o.quantity)}</span></div>
     <div class="modal-row"><span class="modal-label">Remaining</span><span class="modal-value">${fmtInt(o.remaining||o.quantity)}</span></div>
     <div class="modal-row"><span class="modal-label">Price</span><span class="modal-value">${price(o.price)} USDT</span></div>
     <div class="modal-footer">
       <button class="btn danger" onclick="(async()=>{await api('/api/open-orders/${encodeURIComponent(o.id)}/cancel',{method:'POST'});closeModal();update();})()">Cancel order</button>
       <button class="btn" onclick="closeModal()">Close</button>
     </div>`
  );
}

function showTradeDetails(idx) {
  const t = currentTrades[idx]; if (!t) return;
  const pnlVal = t.calculated_pnl ?? t.pnl ?? null;
  const canClose = String(t.side||'').toUpperCase() === 'BUY';
  openModal('Trade Details',
    `<div class="modal-row"><span class="modal-label">ID</span><span class="modal-value">${t.id||'-'}</span></div>
     <div class="modal-row"><span class="modal-label">Time</span><span class="modal-value">${normalizeTime(t.timestamp)}</span></div>
     <div class="modal-row"><span class="modal-label">Side</span><span class="modal-value ${(t.side||'').toLowerCase()}">${t.side||'-'}</span></div>
     <div class="modal-row"><span class="modal-label">Quantity</span><span class="modal-value">${fmtInt(t.quantity)}</span></div>
     <div class="modal-row"><span class="modal-label">Price</span><span class="modal-value">${price(t.price)} USDT</span></div>
     <div class="modal-row"><span class="modal-label">P&L</span><span class="modal-value ${pnlVal!=null?(pnlVal>=0?'positive':'negative'):''}">${pnlVal!=null?fmt(pnlVal,4):'-'}</span></div>
     <div class="modal-footer">
       ${canClose ? `<button class="btn success" onclick="(async()=>{await api('/api/trades/${encodeURIComponent(t.id)}/close',{method:'POST'});closeModal();update();})()">Close BUY position</button>` : ''}
       <button class="btn" onclick="closeModal()">Close</button>
     </div>`
  );
}

function setPnlFilter(w) { pnlFilter = w; update(); }

/* ── Orderbook renderer ────────────────────────────────── */
function renderOrderbook(ob, myOrders) {
  const el = document.getElementById('orderbookLadder');
  if (!el) return;

  const asks_raw = Array.isArray(ob?.asks) ? ob.asks : [];
  const bids_raw = Array.isArray(ob?.bids) ? ob.bids : [];

  if (!asks_raw.length && !bids_raw.length) {
    el.innerHTML = '<div class="small-muted" style="padding:10px;text-align:center">No orderbook data</div>';
    return;
  }

  const myPricesArr = (myOrders||[]).map(o => Number(o.price)).filter(p => p > 0);
  function isMyPrice(px) {
    return myPricesArr.some(mp => Math.abs(mp - px) / Math.max(mp, px, 1e-12) < 1e-6);
  }

  const asks = asks_raw.slice(0,8).reverse();
  const bids = bids_raw.slice(0,8);
  const allQtys = [...asks,...bids].map(r => Number(r.quantity||r.qty||0)).filter(q => q > 0);
  const maxQty = allQtys.length ? Math.max(...allQtys) : 1;

  const renderRow = (r, side) => {
    const px  = Number(r.price);
    const qty = Number(r.quantity || r.qty || 0);
    const pct = maxQty > 0 ? (qty / maxQty * 100).toFixed(1) : 0;
    const mine = isMyPrice(px) ? ' mine' : '';
    return `<div class="ladder-${side}${mine}">
      <span class="ladder-bar" style="width:${pct}%"></span>
      <span class="ladder-price">${price(px)}</span>
      <span class="ladder-qty">${fmtInt(qty)}</span>
    </div>`;
  };

  const spread = asks.length && bids.length
    ? ((Number(asks[asks.length-1].price) - Number(bids[0].price)) / Number(bids[0].price) * 100).toFixed(3)
    : '—';

  el.innerHTML =
    asks.map(r => renderRow(r,'ask')).join('') +
    `<div class="ladder-spread">SPREAD ${spread}%</div>` +
    bids.map(r => renderRow(r,'bid')).join('');
}

/* ── Risk meters ───────────────────────────────────────── */
function renderRiskMeter(id, value, label, max = 100) {
  const el = document.getElementById(id);
  if (!el) return;
  const pct = Math.min(100, Math.abs(value / max * 100));
  const cls = pct > 80 ? 'danger' : pct > 55 ? 'warn' : '';
  el.innerHTML = `
    <div class="risk-meter-label"><span>${label}</span><span class="mono">${fmt(value, 2)}%</span></div>
    <div class="risk-bar"><div class="risk-fill ${cls}" style="width:${pct}%"></div></div>`;
}

/* ── Main update loop ──────────────────────────────────── */
async function update(force = false) {
  if (isUpdating) { pendingUpdate = true; return; }
  isUpdating = true;
  CountdownBar.reset(refreshIntervalMs);

  try {
    const [pR,pfR,pnlR,pnlSaldoR,wrR,fillsR,histR,ordersR,errorsR,botR,profR,execqR,obR,riskR,lcR,rulesR,btR,jR,livePnlR,lmR,rtR] = await Promise.all([
      safeApi('/api/price'), safeApi('/api/portfolio'), safeApi('/api/pnl'),
      safeApi('/api/pnl-saldo'), safeApi('/api/win-rate'), safeApi('/api/fills'),
      safeApi('/api/history'), safeApi('/api/open-orders'), safeApi('/api/errors'),
      safeApi('/api/bot-status'), safeApi('/api/profitability'), safeApi('/api/execution-quality'),
      safeApi('/api/orderbook'), safeApi('/api/risk-cockpit'), safeApi('/api/order-lifecycle'),
      safeApi('/api/automation-rules'), safeApi('/api/backtest-replay-summary'),
      safeApi('/api/strategy-journal'),
      safeApi(`/api/live-pnl?window=${encodeURIComponent(pnlFilter)}&symbol=${encodeURIComponent(document.getElementById('pnlSymbol')?.value||'MEWC_USDT')}&strategy=${encodeURIComponent(document.getElementById('pnlStrategy')?.value||'default')}`),
      safeApi('/api/order-lifecycle-metrics'),
      safeApi('/api/strategy-reason-trace?limit=30'),
    ]);

    const p=pR.data, pf=pfR.data, pnl=pnlR.data, pnlSaldo=pnlSaldoR.data, wr=wrR.data,
      fills=fillsR.data, hist=histR.data, orders=ordersR.data, errors=errorsR.data,
      bot=botR.data, prof=profR.data, execq=execqR.data, ob=obR.data, risk=riskR.data,
      lc=lcR.data, rules=rulesR.data, bt=btR.data, journal=jR.data, livePnl=livePnlR.data,
      lm=lmR.data, rt=rtR.data;

    lastUpdateIssues = [pR,pfR,pnlR,pnlSaldoR,wrR,fillsR,histR,ordersR,errorsR,botR].filter(x=>!x.ok).length;

    /* Price */
    if (p) {
      const el = document.getElementById('price');
      if (el) el.textContent = price(p.last_price);
      const bid = document.getElementById('bid');   if (bid) bid.textContent = price(p.bid);
      const ask = document.getElementById('ask');   if (ask) ask.textContent = price(p.ask);
      const vol = document.getElementById('volume');if (vol) vol.textContent = fmt(p.usd_volume_est,0) + ' USDT';
      const cv  = parseFloat(p.change_percent) || 0;
      const ch  = document.getElementById('priceChange');
      if (ch) { ch.textContent = (cv>=0?'+':'')+p.change_percent+'%'; ch.className = 'price-change ' + (cv>=0?'up':'down'); }
    }

    /* Portfolio */
    if (pf) {
      setNumber('mewcBalance', pf.mewc_balance,      { decimals:0, animate:true });
      setNumber('mewcValue',   pf.mewc_value_usdt,   { decimals:2, suffix:' USDT', animate:true });
      setNumber('usdtBalance', pf.usdt_balance,       { decimals:2, animate:true });
      setNumber('usdtValue',   pf.usdt_balance,       { decimals:2, suffix:' USDT', animate:true });
      const total = isFinite(Number(pf.total_value_usdt)) ? pf.total_value_usdt : ((pf.mewc_value_usdt||0)+(pf.usdt_balance||0));
      setNumber('totalValue', total, { decimals:2, suffix:' USDT', animate:true });
    }

    /* PnL saldo */
    if (pnlSaldo) {
      const v = pnlSaldo.pnl || 0;
      setNumber('portfolioPnL', v, { decimals:2, prefix:sign(v), suffix:' USDT', colorize:true, animate:true });
    }

    /* Win rate */
    if (wr) {
      setNumber('winRate',    wr.win_rate,  { decimals:1, suffix:'%', animate:true });
      setNumber('totalTrades',wr.total,     { decimals:0, animate:false });
    }

    /* Daily/Weekly/Monthly PnL */
    if (pnl && typeof pnl === 'object') {
      ['daily','weekly','monthly'].forEach(period => {
        const d   = pnl[period] || {};
        const val = parseFloat(d.net) || 0;
        const key = period.charAt(0).toUpperCase() + period.slice(1);
        setNumber('pnl'+key, val, { decimals:2, prefix:sign(val), suffix:' USDT', colorize:true, animate:true });
        const tEl = document.getElementById('trades'+key);
        if (tEl) tEl.textContent = d.trades || 0;
      });
    }

    /* Open orders */
    // orders może być: [] (puste), [{...},...] (lista), null (błąd API)
    currentOrders = Array.isArray(orders) ? orders
      : Array.isArray(orders?.orders) ? orders.orders
      : Array.isArray(orders?.data)   ? orders.data
      : [];
    const oEl = document.getElementById('ordersList');
    if (oEl) oEl.innerHTML = currentOrders.length
      ? currentOrders.map((o,i) => `
          <div class="order-item ${(o.side||'').toLowerCase()}" onclick="showOrderDetails(${i})">
            <span class="order-side">${(o.side||'').toUpperCase()}</span>
            <span class="order-qty">${fmtInt(o.remaining||o.quantity)} MEWC</span>
            <span class="order-price">${price(o.price)}</span>
          </div>`).join('')
      : '<div class="small-muted" style="padding:12px 0;text-align:center;">No open orders</div>';

    /* Trades table */
    const fillsRaw = fills;
    currentTrades = Array.isArray(fillsRaw) ? fillsRaw : normalizeFills(fillsRaw);
    const tbl = document.getElementById('tradesTable');
    if (tbl) tbl.innerHTML = currentTrades.length
      ? currentTrades.map((t,i) => {
          const pv  = t.calculated_pnl ?? t.pnl ?? null;
          const cls = pv != null ? (pv >= 0 ? 'positive' : 'negative') : '';
          return `<tr class="trade-row" onclick="showTradeDetails(${i})">
            <td>${normalizeTime(t.timestamp)}</td>
            <td class="${(t.side||'').toLowerCase()}">${(t.side||'').toUpperCase()}</td>
            <td>${fmtInt(t.quantity)}</td>
            <td>${price(t.price)}</td>
            <td class="${cls}">${pv != null ? fmt(pv,4) : '-'}</td>
          </tr>`;
        }).join('')
      : '<tr><td colspan="5" class="small-muted" style="text-align:center;padding:14px">No trades yet</td></tr>';

    /* Errors */
    const eEl = document.getElementById('errorsList');
    if (eEl) eEl.innerHTML = (errors && errors.length)
      ? errors.slice(0,8).map(e => `<div class="stat"><span class="stat-label">•</span><span class="stat-value" style="color:var(--red);font-size:.78rem">${e}</span></div>`).join('')
      : '<div class="small-muted" style="color:var(--green);padding:8px 0">✓ No errors</div>';

    /* Orderbook */
    renderOrderbook(ob, currentOrders);

    /* Portfolio chart */
    const histRows = normalizeHistory(hist);
    const chartCanvas = document.getElementById('portfolioChart');
    if (histRows.length >= 2) {
      // Determine if data spans multiple days
      const firstTs = new Date(histRows[0].timestamp);
      const lastTs  = new Date(histRows[histRows.length-1].timestamp);
      const multiDay = (lastTs - firstTs) > 86400000;
      const labels = histRows.map(h => {
        const d = new Date(h.timestamp);
        return multiDay
          ? d.toLocaleDateString('pl-PL', {month:'2-digit',day:'2-digit'}) + ' ' + d.toLocaleTimeString('pl-PL', {hour:'2-digit',minute:'2-digit'})
          : d.toLocaleTimeString('pl-PL', {hour:'2-digit',minute:'2-digit'});
      });
      const values = histRows.map(h => Number(h.total_value_usdt)||0);
      const hash   = stableHash([histRows.length, values[0], values[values.length-1]]);
      if (force || !chart || hash !== portfolioHistHash) {
        // Remove placeholder if present
        chartCanvas.closest?.('.chart-wrap')?.querySelector('.chart-placeholder')?.remove();
        const nc = upsertLineChart(chart,'portfolioChart',labels,values,'#ff9500','rgba(255,149,0,.08)');
        if (nc) { chart = nc; portfolioHistHash = hash; }
      }
    } else if (chartCanvas && !chart) {
      const wrap = chartCanvas.closest?.('.chart-wrap');
      if (wrap && !wrap.querySelector('.chart-placeholder')) {
        const ph = document.createElement('div');
        ph.className = 'chart-placeholder';
        ph.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:.8rem;font-family:var(--mono)';
        ph.textContent = 'Collecting portfolio data…';
        wrap.appendChild(ph);
      }
    }

    /* Live PnL */
    if (livePnl) {
      setNumber('liveUnrealized', livePnl.unrealized_usdt, { decimals:4, prefix:sign(livePnl.unrealized_usdt), suffix:' USDT', colorize:true, animate:true });
      setNumber('liveRealized',   livePnl.realized_usdt,   { decimals:4, prefix:sign(livePnl.realized_usdt),   suffix:' USDT', colorize:true, animate:true });
      setNumber('liveFees',       livePnl.fees_usdt,        { decimals:4, suffix:' USDT', animate:true });
      setNumber('liveNetProfit',  livePnl.net_usdt,         { decimals:4, prefix:sign(livePnl.net_usdt), suffix:' USDT', colorize:true, animate:true });
      if (livePnl.equity_curve?.length >= 2) {
        const labels = livePnl.equity_curve.map(x => normalizeTime(x.timestamp));
        const values = livePnl.equity_curve.map(x => Number(x.equity)||0);
        const hash   = stableHash([labels,values]);
        if (force || !intradayChart || hash !== intradayHash) {
          const nc = upsertLineChart(intradayChart,'intradayCurve',labels,values,'#b388ff','rgba(179,136,255,.07)');
          if (nc) { intradayChart = nc; intradayHash = hash; }
        }
      } else if (!intradayChart) {
        const cv2 = document.getElementById('intradayCurve');
        const wrap2 = cv2?.closest?.('.chart-wrap');
        if (wrap2 && !wrap2.querySelector('.chart-placeholder')) {
          const ph = document.createElement('div');
          ph.className = 'chart-placeholder';
          ph.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:.8rem;font-family:var(--mono)';
          ph.textContent = 'Collecting equity data…';
          wrap2.appendChild(ph);
        }
      }
    }

    if (prof) { const el = document.getElementById('livePf'); if (el) el.textContent = prof.profit_factor; }

    /* Risk */
    if (risk) {
      renderRiskMeter('riskInventoryMeter', (risk.inventory_ratio||0)*100, 'Inventory', 100);
      renderRiskMeter('riskExposureMeter',  risk.inventory_exposure_pct||risk.inventory_ratio*100||0, 'Exposure', 100);
      setNumber('riskInventory', (risk.inventory_ratio||0)*100,  { decimals:1, suffix:'%', animate:true });
      setNumber('riskTarget',    (risk.target_ratio||0)*100,     { decimals:1, suffix:'%', animate:true });
      setNumber('riskSkew',       risk.current_skew||0,          { decimals:4, animate:true });
      setNumber('riskDrawdown',  risk.session_drawdown_pct||risk.drawdown_pct||0, { decimals:2, suffix:'%', colorize:true, animate:true });
      setNumber('riskDayDd',     risk.day_drawdown_pct||0,       { decimals:2, suffix:'%', colorize:true, animate:true });
      setNumber('riskWeekDd',    risk.week_drawdown_pct||0,      { decimals:2, suffix:'%', colorize:true, animate:true });
      const sg = document.getElementById('riskGuard');  if (sg) { sg.textContent = risk.hard_limit_guard ? 'ON':'OFF'; sg.className = 'stat-value ' + (risk.hard_limit_guard?'positive':'negative'); }
      const ss = document.getElementById('riskState');  if (ss) ss.textContent = risk.risk_state || '-';
    }

    /* Exec quality */
    if (execq) {
      ['execFills','execPositive','execNegative'].forEach((id, i) => {
        const vals = [execq.fills_total, execq.positive_sell_fills, execq.negative_sell_fills];
        const el = document.getElementById(id); if (el) el.textContent = vals[i];
      });
      setNumber('execAvgPnl', execq.avg_realized_pnl_per_sell_usdt, { decimals:6, suffix:' USDT', animate:true });
    }

    if (lm) {
      const ep = document.getElementById('execPercentiles');
      if (ep) ep.textContent = `${fmt(lm.p50_sec,3)} / ${fmt(lm.p95_sec,3)} / ${fmt(lm.p99_sec,3)}s`;
      setNumber('execPostAck',  lm.post_to_ack_avg_sec,       { decimals:3, suffix:'s', animate:true });
      setNumber('execAckFill',  lm.ack_to_first_fill_avg_sec, { decimals:3, suffix:'s', animate:true });
      setNumber('execLifetime', lm.total_lifetime_avg_sec,    { decimals:3, suffix:'s', animate:true });
      const eh = document.getElementById('execHistogram');
      if (eh) eh.innerHTML = (lm.histogram||[]).map(h=>`<div class="stat"><span class="stat-label">${h.bucket}</span><span class="stat-value">${h.count}</span></div>`).join('');
    }

    /* Lifecycle */
    const lcEl = document.getElementById('lifecycleList');
    if (lcEl) lcEl.innerHTML = (lc?.length)
      ? lc.slice(0,50).map(i=>`<div class="stat"><span class="stat-label">${i.event||'-'}</span><span class="stat-value mono" style="font-size:.75rem">${i.order_id||'-'} @ ${i.price||'-'}</span></div>`).join('')
      : '<div class="small-muted">No lifecycle events</div>';

    /* Automation rules */
    const arEl = document.getElementById('automationRules');
    if (arEl) arEl.innerHTML = (rules?.length)
      ? rules.map(r => `<div class="rule-item"><span class="rule-dot ${r.enabled?'':'off'}"></span><span class="rule-name">${r.name}</span><span class="rule-cond">${r.condition} → ${r.action}</span></div>`).join('')
      : '<div class="small-muted">No rules</div>';

    /* Backtest */
    if (bt) {
      const ids = ['btDataset','btTrades','btPnl','btPf','btDd','btReady'];
      const vals = [bt.dataset, bt.simulated_trades, fmt(bt.net_pnl_usdt,4)+' USDT', bt.profit_factor, fmt(bt.max_drawdown_pct,2)+'%', bt.replay_ready?'✓':'✗'];
      ids.forEach((id,i) => { const e=document.getElementById(id); if(e) e.textContent=vals[i]; });
    }

    /* Journal */
    const jEl = document.getElementById('journalList');
    if (jEl) jEl.innerHTML = (journal?.length)
      ? journal.map(j=>`<div class="stat"><span class="stat-label">${j.timestamp||''}</span><span class="stat-value" style="font-size:.75rem">${j.message||''}</span></div>`).join('')
      : '<div class="small-muted">No journal entries</div>';

    /* Reason trace */
    const rtEl = document.getElementById('reasonTraceList');
    if (rtEl) rtEl.innerHTML = (rt?.length)
      ? rt.map(r=>`<div class="stat"><span class="stat-label">${r.signal} / ${r.risk_decision}</span><span class="stat-value" style="font-size:.75rem">${r.final_action}</span></div>`).join('')
      : '<div class="small-muted">No trace</div>';

    /* Bot status */
    if (bot) {
      const el = document.getElementById('botCycle');   if (el) el.textContent = bot.last_cycle || '-';
      const sm = document.getElementById('botSummary'); if (sm) sm.textContent = `mid ${price(bot.last_mid_price)} | skew ${fmt(bot.last_skew,4)} | bids ${bot.active_bids||0} / asks ${bot.active_asks||0}`;
      // Trading tab duplicates
      const c2 = document.getElementById('botCycle2'); if (c2) c2.textContent = bot.last_cycle || '-';
      const mid = document.getElementById('botMid');   if (mid) mid.textContent = price(bot.last_mid_price);
      const sk  = document.getElementById('botSkew');  if (sk)  sk.textContent  = fmt(bot.last_skew, 4);
      const bi  = document.getElementById('botBids');  if (bi)  bi.textContent  = bot.active_bids || 0;
      const as  = document.getElementById('botAsks');  if (as)  as.textContent  = bot.active_asks || 0;
    }

    const lu = document.getElementById('lastUpdate'); if (lu) lu.textContent = new Date().toLocaleTimeString();
    updateStatus(true);

  } catch (e) { console.error('Update error:', e); updateStatus(false); }
  finally {
    isUpdating = false;
    CountdownBar.start(refreshIntervalMs);
    if (pendingUpdate) { pendingUpdate = false; queueMicrotask(() => update(force)); }
  }
}

/* ── Init ──────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  syncManualOrderType();
  document.getElementById('manualType')?.addEventListener('change', syncManualOrderType);
  ['manualQty','manualPrice','manualSide','manualType','manualReduceOnly']
    .forEach(id => document.getElementById(id)?.addEventListener('change', preflightManualOrder));
  document.getElementById('refreshSelect')?.addEventListener('change', e => setRefreshInterval(e.target.value));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) update(true); });

  const initMs = Number(document.getElementById('refreshSelect')?.value) || 5000;
  setRefreshInterval(initMs);
  update();
});
