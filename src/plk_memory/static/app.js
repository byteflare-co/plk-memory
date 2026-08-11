const NS_META = {
  'plk.domain.tax': { label: 'tax', var: '--ns-tax' },
  'plk.domain.legal': { label: 'legal', var: '--ns-legal' },
  'plk.domain.shaho': { label: 'shaho', var: '--ns-shaho' },
  'plk.domain.dev': { label: 'dev', var: '--ns-dev' },
  'plk.domain.backoffice': { label: 'backoffice', var: '--ns-backoffice' },
  'plk.domain.biz': { label: 'biz', var: '--ns-biz' },
  'plk.domain.agent': { label: 'agent', var: '--ns-agent' },
  'plk.shared': { label: 'shared', var: '--ns-shared' },
};

const state = { ns: '', kind: '', status: 'active', q: '', sortDir: 'desc', csrf: null, view: 'facts' };
let currentFacts = [];
let currentDetailId = null;
let metricsLoaded = false;
let metricsLastSuccessAt = null;
let metricsStaleTimer = null;
let activeMetricsPanel = 'decisionValuePanel';
let lastMetricsData = null;
let chartRerenderTimer = null;

// 隠れたパネル内のチャートは幅0で描かれるため、表示状態が変わったら実幅で描き直す
function scheduleChartRerender() {
  if (!lastMetricsData) return;
  if (chartRerenderTimer) window.clearTimeout(chartRerenderTimer);
  chartRerenderTimer = window.setTimeout(() => {
    if (state.view === 'metrics' && lastMetricsData) renderMetricsCharts(lastMetricsData);
  }, 120);
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function nsColorVar(ns) { return (NS_META[ns] && NS_META[ns].var) ? `var(${NS_META[ns].var})` : 'var(--text-faint)'; }
function nsLabel(ns) { return (NS_META[ns] && NS_META[ns].label) || ns || '—'; }

function clearElement(el) { el.replaceChildren(); }

async function login() {
  const errEl = document.getElementById('loginErr');
  errEl.textContent = '';
  const r = await fetch('/ui/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password: document.getElementById('pw').value }),
  });
  if (r.ok) {
    const data = await r.json();
    state.csrf = data.csrf || null;
    enterMain();
    load();
  } else {
    errEl.textContent = '認証に失敗しました。パスワードを確認してください。';
  }
}

function enterMain() {
  document.getElementById('login').style.display = 'none';
  document.getElementById('main').style.display = 'block';
  document.getElementById('viewTabs').style.display = 'flex';
}

function initNsBar() {
  const bar = document.getElementById('nsBar');
  clearElement(bar);
  const makeChip = (value, label, cssVar) => {
    const b = document.createElement('button');
    b.className = 'chip';
    b.setAttribute('aria-pressed', String(value === state.ns));
    b.dataset.v = value;
    if (cssVar) {
      const dot = document.createElement('span');
      dot.className = 'dot';
      dot.style.background = `var(${cssVar})`;
      b.appendChild(dot);
    }
    const t = document.createElement('span');
    t.textContent = label;
    b.appendChild(t);
    b.addEventListener('click', () => {
      state.ns = value;
      [...bar.children].forEach(c => c.setAttribute('aria-pressed', String(c.dataset.v === value)));
      load();
    });
    bar.appendChild(b);
  };
  makeChip('', 'すべて', null);
  Object.entries(NS_META).forEach(([ns, m]) => makeChip(ns, m.label, m.var));
}

function initStatusToggle() {
  const wrap = document.getElementById('statusToggle');
  [...wrap.children].forEach(btn => {
    btn.addEventListener('click', () => {
      state.status = btn.dataset.v;
      [...wrap.children].forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
      load();
    });
  });
}

function initKindToggle() {
  const wrap = document.getElementById('kindToggle');
  [...wrap.children].forEach(btn => {
    btn.addEventListener('click', () => {
      state.kind = btn.dataset.v;
      [...wrap.children].forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
      load();
    });
  });
}

function sortedFacts() {
  const copy = [...currentFacts];
  copy.sort((a, b) => {
    const av = a.created_at || '';
    const bv = b.created_at || '';
    if (av === bv) return 0;
    const cmp = av < bv ? -1 : 1;
    return state.sortDir === 'desc' ? -cmp : cmp;
  });
  return copy;
}

function renderList() {
  const tbody = document.getElementById('list');
  clearElement(tbody);
  const facts = sortedFacts();

  if (facts.length === 0) {
    const tr = document.createElement('tr');
    tr.className = 'empty-row';
    const td = document.createElement('td');
    td.colSpan = 5;
    td.textContent = 'このフィルタに該当する記憶はありません。';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  facts.forEach(f => {
    const tr = document.createElement('tr');
    tr.addEventListener('click', () => detail(f.fact_id));

    const tdStatement = document.createElement('td');
    tdStatement.className = 'statement-cell';
    const stText = document.createElement('div');
    stText.className = 'statement-text';
    stText.textContent = f.statement || '(statement なし)';
    tdStatement.appendChild(stText);
    tr.appendChild(tdStatement);

    const tdNs = document.createElement('td');
    const nsCell = document.createElement('div');
    nsCell.className = 'ns-cell';
    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.background = nsColorVar(f.namespace);
    nsCell.appendChild(dot);
    const nsText = document.createElement('span');
    nsText.textContent = nsLabel(f.namespace);
    nsCell.appendChild(nsText);
    tdNs.appendChild(nsCell);
    tr.appendChild(tdNs);

    const tdKind = document.createElement('td');
    tdKind.className = 'kind-cell';
    tdKind.textContent = f.kind || '—';
    tr.appendChild(tdKind);

    const tdStatus = document.createElement('td');
    const pill = document.createElement('span');
    pill.className = 'status-pill ' + (f.status === 'invalidated' ? 'invalidated' : 'active');
    const pdot = document.createElement('span');
    pdot.className = 'dot';
    pill.appendChild(pdot);
    pill.appendChild(document.createTextNode(f.status === 'invalidated' ? '無効化' : '有効'));
    tdStatus.appendChild(pill);
    tr.appendChild(tdStatus);

    const tdCreated = document.createElement('td');
    tdCreated.className = 'created-cell';
    tdCreated.textContent = formatDate(f.created_at);
    tr.appendChild(tdCreated);

    tbody.appendChild(tr);

    if (f.fact_text) {
      const snipTr = document.createElement('tr');
      snipTr.className = 'snippet-row';
      snipTr.addEventListener('click', () => detail(f.fact_id));
      const snipTd = document.createElement('td');
      snipTd.colSpan = 5;
      const snip = document.createElement('div');
      snip.className = 'snippet';
      snip.textContent = '一致箇所: "' + f.fact_text + '"';
      snipTd.appendChild(snip);
      snipTr.appendChild(snipTd);
      tbody.appendChild(snipTr);
    }
  });
}

async function load() {
  const q = document.getElementById('q').value.trim();
  state.q = q;
  const p = new URLSearchParams();
  if (q) p.set('q', q);
  if (state.ns) p.set('namespace', state.ns);
  if (state.kind) p.set('kind', state.kind);
  if (state.status) p.set('status', state.status);

  const banner = document.getElementById('banner');
  banner.style.display = 'none';
  const metaRow = document.getElementById('metaRow');
  metaRow.textContent = '読み込み中…';

  const r = await fetch('/ui/api/facts?' + p.toString());
  const data = await r.json();

  if (data.degraded) {
    banner.textContent = '⚠ グラフ索引が未接続です（degraded モード）。検索結果は空になります。検索語なしの一覧表示は利用できます。';
    banner.style.display = 'flex';
  }

  currentFacts = data.facts || [];
  const nsText = state.ns ? nsLabel(state.ns) : 'すべて';
  const kindText = state.kind || 'すべてのkind';
  metaRow.textContent = `${currentFacts.length} 件 · ${nsText} · ${kindText} · ${state.status === 'active' ? '有効' : '無効化'}`;
  renderList();
}

function openDetailPanel() {
  const panel = document.getElementById('detail');
  panel.style.display = 'block';
  const scrim = document.getElementById('scrim');
  scrim.style.display = 'block';
  requestAnimationFrame(() => {
    panel.classList.add('open');
    scrim.style.opacity = '1';
  });
}
function closeDetailPanel() {
  currentDetailId = null;
  const panel = document.getElementById('detail');
  panel.classList.remove('open');
  setTimeout(() => { panel.style.display = 'none'; }, 200);
  const scrim = document.getElementById('scrim');
  scrim.style.opacity = '0';
  setTimeout(() => { scrim.style.display = 'none'; }, 200);
}

async function detail(id) {
  const r = await fetch('/ui/api/facts/' + encodeURIComponent(id));
  if (!r.ok) return;
  const data = await r.json();
  currentDetailId = id;
  const meta = data.meta || {};
  const el = document.getElementById('detail');
  clearElement(el);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'closeBtn';
  closeBtn.setAttribute('aria-label', '閉じる');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', closeDetailPanel);
  el.appendChild(closeBtn);

  const kickerRow = document.createElement('div');
  kickerRow.className = 'kicker-row';
  kickerRow.textContent = nsLabel(meta.namespace) + ' · ' + (meta.kind || '') + ' · ' + formatDate(meta.created_at);
  el.appendChild(kickerRow);

  const h2 = document.createElement('h2');
  h2.textContent = meta.statement || '';
  el.appendChild(h2);

  if (meta.status === 'invalidated') {
    const alertBox = document.createElement('div');
    alertBox.className = 'alert';
    const span = document.createElement('span');
    span.textContent = '無効化: ' + (meta.invalidation_reason || '理由なし');
    alertBox.appendChild(span);
    if (meta.superseded_by) {
      const b = document.createElement('button');
      b.textContent = '後継記憶を見る →';
      b.addEventListener('click', () => detail(meta.superseded_by));
      alertBox.appendChild(b);
    }
    el.appendChild(alertBox);
  }

  const mkField = (label, value) => {
    if (!value) return;
    const f = document.createElement('div');
    f.className = 'field';
    const l = document.createElement('div');
    l.className = 'label';
    l.textContent = label;
    const v = document.createElement('div');
    v.className = 'val';
    v.textContent = value;
    f.appendChild(l); f.appendChild(v);
    el.appendChild(f);
  };
  mkField('why', meta.why);
  mkField('how to apply', meta.how_to_apply);
  mkField('source', meta.source);

  if (Array.isArray(meta.tags) && meta.tags.length) {
    const f = document.createElement('div');
    f.className = 'field';
    const l = document.createElement('div');
    l.className = 'label';
    l.textContent = 'tags';
    const row = document.createElement('div');
    row.className = 'tagrow';
    meta.tags.forEach(t => {
      const s = document.createElement('span');
      s.textContent = t;
      row.appendChild(s);
    });
    f.appendChild(l); f.appendChild(row);
    el.appendChild(f);
  }

  // body_html はサーバー側で nh3 sanitize 済み（非信頼入力の二重防御として、ここでは加工しない）
  const body = document.createElement('div');
  body.className = 'body-content';
  body.innerHTML = data.body_html || '';
  el.appendChild(body);

  const hist = data.history || {};

  if (Array.isArray(hist.supersedes_chain) && hist.supersedes_chain.length) {
    const h3 = document.createElement('h3');
    h3.className = 'section';
    h3.textContent = 'この記憶に置き換えられた記憶';
    el.appendChild(h3);
    const chain = document.createElement('div');
    chain.className = 'chain';
    hist.supersedes_chain.forEach(fid => {
      const b = document.createElement('button');
      b.textContent = fid;
      b.addEventListener('click', () => detail(fid));
      chain.appendChild(b);
    });
    el.appendChild(chain);
  }

  const h3c = document.createElement('h3');
  h3c.className = 'section';
  h3c.textContent = '変遷（git log）';
  el.appendChild(h3c);

  const commits = hist.commits || [];
  if (commits.length === 0) {
    const p = document.createElement('div');
    p.style.color = 'var(--text-faint)';
    p.style.fontSize = '12px';
    p.textContent = '履歴なし';
    el.appendChild(p);
  } else {
    const ul = document.createElement('ul');
    ul.className = 'timeline';
    commits.forEach(c => {
      const li = document.createElement('li');
      const d = document.createElement('div');
      d.className = 'd';
      d.textContent = formatDate(c.date) + ' · ';
      const sha = document.createElement('span');
      sha.className = 'sha';
      sha.textContent = c.sha;
      d.appendChild(sha);
      const s = document.createElement('div');
      s.className = 's';
      s.textContent = c.subject || '';
      li.appendChild(d); li.appendChild(s);
      ul.appendChild(li);
    });
    el.appendChild(ul);
  }

  await renderOperations(el, id, meta);

  openDetailPanel();
}

async function apiPost(url, payload) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-plk-csrf': state.csrf || '',
    },
    body: JSON.stringify(payload || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

function proposalField(container, label, before, after) {
  if (String(before || '') === String(after || '')) return;
  const wrap = document.createElement('div');
  wrap.className = 'proposal-field';
  const l = document.createElement('div');
  l.className = 'label';
  l.textContent = label;
  const b = document.createElement('div');
  b.className = 'before';
  b.textContent = Array.isArray(before) ? before.join(', ') : (before || '（空）');
  const a = document.createElement('div');
  a.className = 'after';
  a.textContent = Array.isArray(after) ? after.join(', ') : (after || '（空）');
  wrap.append(l, b, a);
  container.appendChild(wrap);
}

async function renderOperations(el, factId, meta) {
  if (!state.csrf || meta.status !== 'active') return;
  const heading = document.createElement('h3');
  heading.className = 'section';
  heading.textContent = '操作';
  el.appendChild(heading);

  const form = document.createElement('div');
  form.className = 'feedback-form';
  const textarea = document.createElement('textarea');
  textarea.placeholder = '例: この主張は条件が曖昧なので、適用条件と例外を明確にして';
  textarea.setAttribute('aria-label', 'AIへの改善フィードバック');
  const actions = document.createElement('div');
  actions.className = 'fact-actions';
  const submit = document.createElement('button');
  submit.className = 'action-btn primary';
  submit.textContent = 'AIに改善案を作らせる';
  const invalidate = document.createElement('button');
  invalidate.className = 'action-btn danger';
  invalidate.textContent = '無効化';
  const error = document.createElement('div');
  error.className = 'operation-error';

  submit.addEventListener('click', async () => {
    error.textContent = '';
    submit.disabled = true;
    try {
      await apiPost(`/ui/api/facts/${encodeURIComponent(factId)}/feedback`, {
        feedback: textarea.value,
      });
      textarea.value = '';
      await renderFeedbackJobs(el, factId, meta);
    } catch (e) {
      error.textContent = e.message;
    } finally {
      submit.disabled = false;
    }
  });
  invalidate.addEventListener('click', async () => {
    const reason = window.prompt('無効化する理由（5文字以上）');
    if (!reason) return;
    if (!window.confirm('このfactを無効化します。履歴は保持されます。実行しますか？')) return;
    error.textContent = '';
    invalidate.disabled = true;
    try {
      await apiPost(`/ui/api/facts/${encodeURIComponent(factId)}/invalidate`, {
        reason,
        expected_hash: meta._content_hash || '',
      });
      closeDetailPanel();
      await load();
    } catch (e) {
      error.textContent = e.message;
      invalidate.disabled = false;
    }
  });
  actions.append(submit, invalidate);
  form.append(textarea, actions, error);
  el.appendChild(form);

  const jobs = document.createElement('div');
  jobs.id = 'feedbackJobs';
  el.appendChild(jobs);
  await renderFeedbackJobs(el, factId, meta);
}

async function renderFeedbackJobs(el, factId, meta) {
  if (currentDetailId !== factId) return;
  const host = el.querySelector('#feedbackJobs');
  if (!host) return;
  const r = await fetch(`/ui/api/facts/${encodeURIComponent(factId)}/feedback`);
  if (!r.ok) return;
  const data = await r.json();
  clearElement(host);
  const requests = data.requests || [];
  requests.forEach(job => {
    const wrap = document.createElement('div');
    wrap.className = 'feedback-job';
    const metaLine = document.createElement('div');
    metaLine.className = 'job-meta';
    metaLine.textContent = `${formatDate(job.created_at)} · `;
    const stateEl = document.createElement('span');
    stateEl.className = 'job-state';
    stateEl.textContent = job.state;
    metaLine.appendChild(stateEl);
    wrap.appendChild(metaLine);

    const feedback = document.createElement('div');
    feedback.textContent = job.feedback;
    wrap.appendChild(feedback);

    if (job.error) {
      const err = document.createElement('div');
      err.className = 'operation-error';
      err.textContent = job.error;
      wrap.appendChild(err);
    }
    if (job.state === 'proposed' && job.proposal) {
      proposalField(wrap, 'statement', meta.statement, job.proposal.statement);
      proposalField(wrap, 'why', meta.why, job.proposal.why);
      proposalField(wrap, 'how to apply', meta.how_to_apply, job.proposal.how_to_apply);
      proposalField(wrap, 'tags', meta.tags || [], job.proposal.tags || []);
      proposalField(wrap, 'body', (job.original || {}).body || '', job.proposal.body || '');
      const rationale = document.createElement('div');
      rationale.className = 'proposal-field';
      rationale.textContent = `AIの変更理由: ${job.proposal.rationale}`;
      wrap.appendChild(rationale);
      const buttons = document.createElement('div');
      buttons.className = 'fact-actions';
      const apply = document.createElement('button');
      apply.className = 'action-btn primary';
      apply.textContent = 'この差分を反映';
      const reject = document.createElement('button');
      reject.className = 'action-btn';
      reject.textContent = '却下';
      apply.addEventListener('click', async () => {
        if (!window.confirm('表示された差分を新しいfactとして反映し、現在のfactを無効化しますか？')) return;
        apply.disabled = true;
        try {
          const result = await apiPost(`/ui/api/feedback/${encodeURIComponent(job.id)}/apply`, {});
          closeDetailPanel();
          await load();
          if (result.fact_id) await detail(result.fact_id);
        } catch (e) {
          window.alert(e.message);
          apply.disabled = false;
        }
      });
      reject.addEventListener('click', async () => {
        reject.disabled = true;
        try {
          await apiPost(`/ui/api/feedback/${encodeURIComponent(job.id)}/reject`, {});
          await renderFeedbackJobs(el, factId, meta);
        } catch (e) {
          window.alert(e.message);
          reject.disabled = false;
        }
      });
      buttons.append(apply, reject);
      wrap.appendChild(buttons);
    }
    host.appendChild(wrap);
  });
  if (requests.some(job => ['queued', 'running', 'applying'].includes(job.state))) {
    setTimeout(() => renderFeedbackJobs(el, factId, meta), 2000);
  }
}

const SVG_NS = 'http://www.w3.org/2000/svg';
// 図版は ink を主系列に置き、必要な分だけアクセントを足す。
// 罫線・軸・注記は hairline / mute に寄せ、面で色を主張しない。
const INK = 'var(--chart-ink)';
const BLUE = 'var(--chart-accent)';
const VIOLET = 'var(--chart-violet)';
const AMBER = 'var(--chart-amber)';
const MUTE = 'var(--chart-mute)';
const FAINT = 'var(--chart-faint)';
const RULE = 'var(--chart-rule)';
const RULE_SOFT = 'var(--chart-rule-soft)';
const RULE_STRONG = 'var(--chart-rule-strong)';
const CHART_COLORS = [INK, BLUE, VIOLET, MUTE, AMBER, 'var(--chart-cyan)', 'var(--chart-pink)', RULE_STRONG];

// 軸の刻みは 1/2/5×10^n に丸める。上端は刻みの倍数まで“切り上げ”に留め、
// 目盛り数を固定して無駄な余白（最大26なのに軸が40）を作らない。
function niceScale(rawMax, preferredTicks = 4) {
  const max = Math.max(1, rawMax);
  const rough = max / preferredTicks;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / magnitude;
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
  const top = Math.ceil(max / step) * step;
  return { max: top, step, ticks: Math.max(1, Math.round(top / step)) };
}

function svgElement(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
  return el;
}

function svgText(parent, value, attrs = {}) {
  const textEl = svgElement('text', attrs);
  textEl.textContent = String(value);
  parent.appendChild(textEl);
  return textEl;
}

// ホストの実幅で描くことで、preserveAspectRatio による中央寄せ・左右余白を避ける
function chartWidth(host, fallback = 760) {
  const width = host.clientWidth;
  return width > 80 ? width : fallback;
}

function makeChart(host, label, height = 224) {
  clearElement(host);
  const width = chartWidth(host);
  const svg = svgElement('svg', {
    viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': label,
    // 描画時と表示時で幅がずれても中央に浮かせず、左端を揃えたまま縮める
    preserveAspectRatio: 'xMinYMid meet',
  });
  svg.style.height = `${height}px`;
  host.dataset.drawnWidth = String(width);
  host.appendChild(svg);
  return { svg, width };
}

function everyNthLabel(count, plotWidth, minSlot = 64) {
  return Math.max(1, Math.ceil(count / Math.max(1, Math.floor(plotWidth / minSlot))));
}

function renderChartEmpty(host, message) {
  clearElement(host);
  const empty = document.createElement('div');
  empty.className = 'chart-empty';
  empty.textContent = message;
  host.appendChild(empty);
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function percent(value) {
  const n = numberOrNull(value);
  return n === null ? '—' : `${Math.round(n * 100)}%`;
}

function compactWeek(value) {
  const text = String(value || '');
  return text.length >= 10 ? text.slice(5, 10).replace('-', '/') : text;
}

function formatDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function appendLegend(host, items) {
  const legend = document.createElement('div');
  legend.className = 'chart-legend';
  items.forEach(item => {
    const row = document.createElement('span');
    row.className = 'legend-item';
    const swatch = document.createElement('span');
    swatch.className = `legend-swatch${item.outlined ? ' outlined' : ''}`;
    swatch.style.background = item.color;
    const label = document.createElement('span');
    label.textContent = item.label;
    row.append(swatch, label);
    legend.appendChild(row);
  });
  host.appendChild(legend);
  return legend;
}

// 目盛り線は最下段だけ hairline、中間は更に淡くして数字を邪魔しない
function drawGrid(svg, { left, top, width, height, ticks = 4, maxValue = 1, formatter = String }) {
  for (let i = 0; i <= ticks; i += 1) {
    const y = top + (height * i / ticks);
    const baseline = i === ticks;
    svg.appendChild(svgElement('line', {
      x1: left, y1: y, x2: left + width, y2: y,
      stroke: baseline ? RULE : RULE_SOFT, 'stroke-width': 1, 'shape-rendering': 'crispEdges',
    }));
    svgText(svg, formatter(maxValue * (ticks - i) / ticks), {
      x: left - 10, y: y + 4, fill: FAINT, 'font-size': 11, 'text-anchor': 'end',
    });
  }
}

function renderWeeklySearch(weekly) {
  const host = document.getElementById('weeklySearchChart');
  const observed = weekly.some(row => (
    (numberOrNull(row.auto) || 0) + (numberOrNull(row.manual) || 0) + (numberOrNull(row.failures) || 0)
  ) > 0);
  if (!weekly.length || !observed) {
    renderChartEmpty(host, '週次集計できる検索ログがありません。plk_search の利用後に表示されます。');
    return;
  }
  const { svg, width: hostWidth } = makeChart(host, '週別検索数の積み上げ棒グラフ');
  const left = 40; const top = 12; const width = hostWidth - left - 18; const height = 180;
  const scale = niceScale(Math.max(1, ...weekly.map(row => (numberOrNull(row.auto) || 0) + (numberOrNull(row.manual) || 0))));
  const maxValue = scale.max;
  drawGrid(svg, { left, top, width, height, ticks: scale.ticks, maxValue, formatter: value => String(Math.round(value)) });
  const slot = width / weekly.length;
  const barWidth = Math.max(6, Math.min(24, slot * .42));
  const labelEvery = everyNthLabel(weekly.length, width);
  weekly.forEach((row, index) => {
    const auto = Math.max(0, numberOrNull(row.auto) || 0);
    const manual = Math.max(0, numberOrNull(row.manual) || 0);
    const autoHeight = height * auto / maxValue;
    const manualHeight = height * manual / maxValue;
    const x = left + slot * index + (slot - barWidth) / 2;
    const autoRect = svgElement('rect', { x, y: top + height - autoHeight, width: barWidth, height: autoHeight, fill: INK });
    const autoTitle = svgElement('title');
    autoTitle.textContent = `${String(row.week || '')}: 自動検索 ${auto}`;
    autoRect.appendChild(autoTitle);
    svg.appendChild(autoRect);
    const manualRect = svgElement('rect', { x, y: top + height - autoHeight - manualHeight, width: barWidth, height: manualHeight, fill: BLUE });
    const manualTitle = svgElement('title');
    manualTitle.textContent = `${String(row.week || '')}: 手動検索 ${manual}`;
    manualRect.appendChild(manualTitle);
    svg.appendChild(manualRect);
    if (index % labelEvery === 0 || index === weekly.length - 1) {
      svgText(svg, compactWeek(row.week) + (row.in_progress ? '*' : ''), {
        x: x + barWidth / 2, y: top + height + 22, fill: MUTE, 'font-size': 11, 'text-anchor': 'middle',
      });
    }
  });
  let failurePath = '';
  weekly.forEach((row, index) => {
    const failures = Math.max(0, numberOrNull(row.failures) || 0);
    const x = left + slot * index + slot / 2;
    const y = top + height * (1 - failures / maxValue);
    failurePath += `${failurePath ? ' L' : 'M'} ${x} ${y}`;
    const marker = svgElement('circle', { cx: x, cy: y, r: 2.5, fill: AMBER });
    const title = svgElement('title');
    title.textContent = `${String(row.week || '')}: 障害 ${failures}`;
    marker.appendChild(title);
    svg.appendChild(marker);
  });
  const firstMarker = svg.querySelector('circle');
  if (failurePath && firstMarker) {
    svg.insertBefore(svgElement('path', {
      d: failurePath, fill: 'none', stroke: AMBER, 'stroke-width': 1.5,
    }), firstMarker);
  }
  const legend = appendLegend(host, [
    { label: '自動検索', color: INK },
    { label: '手動検索', color: BLUE },
    { label: '障害', color: AMBER },
  ]);
  const progressNote = document.createElement('span');
  progressNote.textContent = '* 進行中の週';
  legend.appendChild(progressNote);
}

function renderReturnRate(weekly) {
  const host = document.getElementById('returnRateChart');
  const points = weekly.map(row => ({
    week: row.week,
    inProgress: Boolean(row.in_progress),
    rate: numberOrNull(row.ok_total) > 0 ? Number(row.returned || 0) / Number(row.ok_total) : null,
  }));
  if (!points.some(point => point.rate !== null)) {
    renderChartEmpty(host, '正常検索の観測がまだありません。');
    return;
  }
  const { svg, width: hostWidth } = makeChart(host, '週別結果返却率の折れ線グラフ');
  const left = 40; const top = 12; const width = hostWidth - left - 18; const height = 180;
  drawGrid(svg, { left, top, width, height, maxValue: 1, formatter: value => `${Math.round(value * 100)}%` });
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const labelEvery = everyNthLabel(points.length, width);
  const paths = [];
  let path = '';
  points.forEach((point, index) => {
    if (point.rate === null) {
      if (path) paths.push(path);
      path = '';
      return;
    }
    const x = points.length > 1 ? left + step * index : left + width / 2;
    const y = top + height * (1 - Math.max(0, Math.min(1, point.rate)));
    path += `${path ? ' L' : 'M'} ${x} ${y}`;
    const circle = svgElement('circle', { cx: x, cy: y, r: 2.5, fill: INK });
    const title = svgElement('title');
    title.textContent = `${String(point.week || '')}: ${percent(point.rate)}`;
    circle.appendChild(title);
    svg.appendChild(circle);
    if (index % labelEvery === 0 || index === points.length - 1) {
      svgText(svg, compactWeek(point.week) + (point.inProgress ? '*' : ''), {
        x, y: top + height + 22, fill: MUTE, 'font-size': 11, 'text-anchor': 'middle',
      });
    }
  });
  if (path) paths.push(path);
  const firstPoint = svg.querySelector('circle');
  paths.forEach(segment => svg.insertBefore(
    svgElement('path', { d: segment, fill: 'none', stroke: INK, 'stroke-width': 1.5 }),
    firstPoint,
  ));
  const legend = appendLegend(host, [{ label: '結果返却率', color: INK }]);
  const progressNote = document.createElement('span');
  progressNote.textContent = '* 進行中の週';
  legend.appendChild(progressNote);
}

// dotFor を渡すと、棒の直前に分類色のドットを置く。棒自体はアクセント1色に揃え、
// 彩度の高い面が広く出ないようにする（Geist: 色は図版の小さなアクセントに留める）。
function renderHorizontalBars(hostId, rows, valueKey, labelKey, emptyMessage, dotFor = null) {
  const host = document.getElementById(hostId);
  if (!rows.length) {
    renderChartEmpty(host, emptyMessage);
    return;
  }
  const shown = rows.slice(0, 10);
  const rowH = 30;
  const height = shown.length * rowH + 8;
  const { svg, width: hostWidth } = makeChart(host, `${hostId} 横棒グラフ`, height);
  const left = Math.min(210, Math.max(110, Math.round(hostWidth * .26)));
  const width = hostWidth - left - 48;
  const dotGap = dotFor ? 14 : 0;
  const maxLabelChars = Math.max(6, Math.floor((left - 14 - dotGap) / 9));
  const maxValue = Math.max(1, ...shown.map(row => numberOrNull(row[valueKey]) || 0));
  shown.forEach((row, index) => {
    const value = Math.max(0, numberOrNull(row[valueKey]) || 0);
    const y = 6 + index * rowH;
    const barY = y + 4;
    const barLength = Math.max(2, width * value / maxValue);
    const rawLabel = String(row[labelKey] || '—');
    const labelText = rawLabel.length > maxLabelChars ? `${rawLabel.slice(0, maxLabelChars - 1)}…` : rawLabel;
    const labelEl = svgText(svg, labelText, {
      x: left - 10 - dotGap, y: barY + 10, fill: MUTE, 'font-size': 12, 'text-anchor': 'end',
    });
    if (labelText !== rawLabel) {
      const title = svgElement('title');
      title.textContent = rawLabel;
      labelEl.appendChild(title);
    }
    if (dotFor) {
      svg.appendChild(svgElement('circle', { cx: left - 8, cy: barY + 6, r: 3.5, fill: dotFor(row, index) }));
    }
    // 最大値までのトラックを淡く敷き、棒の短さが読み取れるようにする
    svg.appendChild(svgElement('rect', { x: left, y: barY, width, height: 12, fill: RULE_SOFT }));
    svg.appendChild(svgElement('rect', { x: left, y: barY, width: barLength, height: 12, fill: INK }));
    // トラック終端より右の余白に right-align で置く（棒に数字が重ならないようにする）
    svgText(svg, value, {
      x: hostWidth - 4, y: barY + 10, fill: MUTE, 'font-size': 12, 'text-anchor': 'end',
    });
  });
}

function evalSeries(evalData) {
  const series = [];
  Object.entries(evalData || {}).forEach(([runner, rows]) => {
    const grouped = new Map();
    (Array.isArray(rows) ? rows : []).forEach(row => {
      const hash = String(row.queries_hash || 'unknown');
      if (!grouped.has(hash)) grouped.set(hash, []);
      grouped.get(hash).push(row);
    });
    grouped.forEach((points, hash) => {
      points.sort((a, b) => String(a.ts || '').localeCompare(String(b.ts || '')));
      series.push({ runner, hash, points });
    });
  });
  return series;
}

function renderEval(evalData) {
  const host = document.getElementById('evalChart');
  const series = evalSeries(evalData);
  if (!series.length) {
    renderChartEmpty(host, '評価は未実行です。uv run python scripts/eval/run_eval.py で計測できます。');
    return;
  }
  const { svg, width: hostWidth } = makeChart(host, '上位5件の正解率と検索順位スコアの折れ線グラフ');
  const left = 40; const top = 12; const width = hostWidth - left - 18; const height = 180;
  drawGrid(svg, { left, top, width, height, maxValue: 1, formatter: value => `${Math.round(value * 100)}%` });
  const timestamps = [...new Set(series.flatMap(item => item.points.map(point => String(point.ts || ''))))].sort();
  const xFor = ts => timestamps.length > 1 ? left + width * timestamps.indexOf(String(ts || '')) / (timestamps.length - 1) : left + width / 2;
  const runners = [...new Set(series.map(item => item.runner))];
  const colorForRunner = runner => CHART_COLORS[runners.indexOf(runner) % CHART_COLORS.length];
  series.forEach(item => {
    const baseColor = colorForRunner(item.runner);
    [['hit5_rate', false], ['mrr', true]].forEach(([field, dashed]) => {
      let path = '';
      item.points.forEach(point => {
        const value = numberOrNull(point[field]);
        if (value === null) return;
        const x = xFor(point.ts);
        const y = top + height * (1 - Math.max(0, Math.min(1, value)));
        path += `${path ? ' L' : 'M'} ${x} ${y}`;
        const circle = svgElement('circle', { cx: x, cy: y, r: 2.6, fill: dashed ? 'var(--canvas-elevated)' : baseColor, stroke: baseColor, 'stroke-width': 1.4 });
        const title = svgElement('title');
        const scoreName = field === 'hit5_rate' ? '上位5件の正解率' : '検索順位スコア';
        title.textContent = `${item.runner} / ${scoreName}: ${percent(value)}（${item.hash}）`;
        circle.appendChild(title);
        svg.appendChild(circle);
      });
      if (path) {
        const attrs = { d: path, fill: 'none', stroke: baseColor, 'stroke-width': dashed ? 1.2 : 1.8 };
        if (dashed) attrs['stroke-dasharray'] = '5 4';
        svg.insertBefore(svgElement('path', attrs), svg.querySelector('circle'));
      }
    });
  });
  const labels = timestamps.length > 5 ? timestamps.filter((_, index) => index % Math.ceil(timestamps.length / 5) === 0) : timestamps;
  labels.forEach(ts => svgText(svg, formatDate(ts), { x: xFor(ts), y: top + height + 22, fill: MUTE, 'font-size': 11, 'text-anchor': 'middle' }));
  const legend = appendLegend(host, runners.map(runner => ({ label: runner, color: colorForRunner(runner) })));
  const styleNote = document.createElement('span');
  styleNote.textContent = '実線: 上位5件の正解率 / 破線: 検索順位スコア';
  legend.appendChild(styleNote);
  const hashes = [...new Set(series.map(item => item.hash))];
  const hashNote = document.createElement('span');
  hashNote.className = 'chart-caption';
  hashNote.textContent = hashes.length === 1
    ? `評価セット: ${hashes[0].replace(/^sha256:/, '').slice(0, 12)}…`
    : `評価セット ${hashes.length} 種（点にマウスを重ねると詳細）`;
  host.appendChild(hashNote);
}

function makeTag(text, tone = '') {
  const tag = document.createElement('span');
  tag.className = `tag ${tone}`.trim();
  tag.textContent = text;
  return tag;
}

// 数値は常に ink。達成/未達は数字の色ではなく、隣に置く小さなタグで示す。
// ratio を渡すと 2px のメーターを添える。
function addStatTile(host, { label, value, unit = '', note = '', ratio = null, tag = null, tone = '' }) {
  const tile = document.createElement('div');
  tile.className = 'stat-tile';

  const labelEl = document.createElement('div');
  labelEl.className = 'stat-label';
  labelEl.textContent = label;

  const valueEl = document.createElement('div');
  valueEl.className = 'stat-value';
  valueEl.textContent = value;
  if (unit) {
    const unitEl = document.createElement('span');
    unitEl.className = 'unit';
    unitEl.textContent = unit;
    valueEl.appendChild(unitEl);
  }
  tile.append(labelEl, valueEl);

  if (ratio !== null && Number.isFinite(ratio)) {
    const meter = document.createElement('div');
    meter.className = 'stat-meter';
    const fill = document.createElement('span');
    fill.style.width = `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`;
    meter.appendChild(fill);
    tile.appendChild(meter);
  }

  const foot = document.createElement('div');
  foot.className = 'stat-foot';
  if (tag) foot.appendChild(makeTag(tag, tone));
  if (note) {
    const noteEl = document.createElement('span');
    noteEl.className = 'stat-note';
    noteEl.textContent = note;
    foot.appendChild(noteEl);
  }
  if (foot.childElementCount) tile.appendChild(foot);
  host.appendChild(tile);
}

// 判定不能週を「薄く塗る」と 0 件と見分けが付かず、輪郭だけだと積み上げが読めない。
// 系列色のハッチで塗り、面の存在は保ったまま暫定であることを示す。
function hatchFill(svg, id, color) {
  let defs = svg.querySelector('defs');
  if (!defs) {
    defs = svgElement('defs');
    svg.insertBefore(defs, svg.firstChild);
  }
  const pattern = svgElement('pattern', {
    id, width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)',
  });
  pattern.appendChild(svgElement('rect', { width: 5, height: 5, fill: 'var(--chart-surface)' }));
  pattern.appendChild(svgElement('line', { x1: 0, y1: 0, x2: 0, y2: 5, stroke: color, 'stroke-width': 2 }));
  defs.appendChild(pattern);
  return `url(#${id})`;
}

const HATCH_CSS = color => `repeating-linear-gradient(45deg, ${color} 0 2px, var(--chart-surface) 2px 5px)`;

function renderDecisionValueChart(weekly) {
  const host = document.getElementById('decisionValueChart');
  if (!weekly.length) {
    renderChartEmpty(host, '4完了週の観測データがまだありません。');
    return;
  }
  const { svg, width: hostWidth } = makeChart(host, '直近4完了週の強い影響報告と観測カバレッジ', 174);
  const description = svgElement('desc');
  description.textContent = '行動変更と誤り防止の報告数を週別に積み上げ、週次目標線と観測カバレッジを表示します。';
  svg.appendChild(description);
  const left = 40; const top = 8; const width = hostWidth - left - 72; const height = 108;
  const target = Math.max(1, ...weekly.map(row => numberOrNull(row.target) || 0));
  const scale = niceScale(Math.max(target, ...weekly.map(row => numberOrNull(row.strong_decisions) || 0)));
  const maxValue = scale.max;
  drawGrid(svg, { left, top, width, height, ticks: scale.ticks, maxValue, formatter: value => String(Math.round(value)) });

  const slot = width / weekly.length;
  const barWidth = Math.min(64, Math.max(18, slot * .34));
  const hatches = [hatchFill(svg, 'dvHatchInk', INK), hatchFill(svg, 'dvHatchBlue', BLUE)];
  weekly.forEach((row, index) => {
    const changed = Math.max(0, numberOrNull(row.changed_action_decisions) || 0);
    const prevented = Math.max(0, numberOrNull(row.prevented_error_decisions) || 0);
    const x = left + slot * index + (slot - barWidth) / 2;
    const solid = Boolean(row.evaluable);
    const stack = [
      { value: changed, color: INK, hatch: hatches[0], label: '行動変更' },
      { value: prevented, color: BLUE, hatch: hatches[1], label: '誤り防止' },
    ];
    let cursor = 0;
    stack.forEach(part => {
      if (part.value <= 0) return;
      const barHeight = height * part.value / maxValue;
      cursor += barHeight;
      const rect = svgElement('rect', {
        x, y: top + height - cursor, width: barWidth, height: barHeight,
        fill: solid ? part.color : part.hatch,
        stroke: solid ? 'none' : part.color,
        'stroke-width': solid ? 0 : 1,
      });
      const title = svgElement('title');
      title.textContent = `${row.week}: ${part.label} ${part.value}件${solid ? '' : '（判定不能週）'}`;
      rect.appendChild(title);
      svg.appendChild(rect);
    });
    if (!solid && changed + prevented === 0) {
      const placeholderHeight = Math.max(28, height * .18);
      const pending = svgElement('rect', {
        x, y: top + height - placeholderHeight, width: barWidth, height: placeholderHeight,
        fill: hatches[0], stroke: RULE_STRONG, 'stroke-width': 1,
      });
      const pendingTitle = svgElement('title');
      pendingTitle.textContent = `${row.week}: 計測不足のため判定不能`;
      pending.appendChild(pendingTitle);
      svg.appendChild(pending);
      svgText(svg, '判定不能', {
        x: x + barWidth / 2, y: top + height - placeholderHeight / 2 + 4,
        fill: MUTE, 'font-size': 10, 'font-weight': 600, 'text-anchor': 'middle',
      });
    }
    svgText(svg, compactWeek(row.week), {
      x: x + barWidth / 2, y: top + height + 22, fill: MUTE, 'font-size': 11, 'text-anchor': 'middle',
    });
    const coverage = numberOrNull(row.auto_measurement_rate);
    svgText(svg, solid ? percent(coverage) : '判定不能', {
      x: x + barWidth / 2, y: top + height + 40, fill: FAINT, 'font-size': 11, 'text-anchor': 'middle',
    });
  });

  // 目標線は罫線と同じ格で引き、注記だけをプロット域の外に出す
  const targetY = top + height * (1 - target / maxValue);
  svg.appendChild(svgElement('line', {
    x1: left, y1: targetY, x2: left + width, y2: targetY,
    stroke: RULE_STRONG, 'stroke-width': 1, 'stroke-dasharray': '4 4', 'shape-rendering': 'crispEdges',
  }));
  svgText(svg, `目標 ${target}`, {
    x: left + width + 8, y: targetY + 4, fill: MUTE, 'font-size': 11, 'text-anchor': 'start',
  });
  const legend = [
    { label: '行動を変更', color: INK },
    { label: '誤りを防止', color: BLUE },
  ];
  if (weekly.some(row => !row.evaluable)) {
    legend.push({ label: '判定不能週', color: HATCH_CSS(INK), outlined: true });
  }
  appendLegend(host, legend);
}

function renderDecisionValueRows(weekly) {
  const tbody = document.getElementById('decisionValueRows');
  clearElement(tbody);
  if (!weekly.length) {
    emptyTableRow(tbody, 7, '4完了週の観測データがありません。');
    return;
  }
  weekly.forEach(row => {
    const tr = document.createElement('tr');
    const week = document.createElement('td');
    week.className = 'mono';
    week.textContent = row.week || '—';
    tr.appendChild(week);
    [
      numberOrNull(row.auto_measurable_searches) || 0,
      numberOrNull(row.auto_resolved_searches) || 0,
      percent(row.auto_measurement_rate),
      numberOrNull(row.changed_action_decisions) || 0,
      numberOrNull(row.prevented_error_decisions) || 0,
    ].forEach(value => {
      const td = document.createElement('td');
      td.className = 'num';
      td.textContent = String(value);
      tr.appendChild(td);
    });
    const statusTd = document.createElement('td');
    if (row.evaluable) {
      statusTd.appendChild(makeTag(row.target_met ? '目標達成' : '目標未達', row.target_met ? 'pass' : 'fail'));
    } else {
      statusTd.appendChild(makeTag('判定不能', ''));
      const why = (row.unevaluable_reasons || []).join(', ');
      if (why) statusTd.title = why;
    }
    tr.appendChild(statusTd);
    tbody.appendChild(tr);
  });
}

function nextActionCopy(action) {
  const code = String(action.code || 'none');
  const copies = {
    repair_invalid_records: [`不正な計測記録 ${action.count || 0}件を確認`, '週次判定から除外された重複・不正記録を修復します。', 'データ状態を見る'],
    record_missing_decisions: [`未計測 ${action.count || 0}件を確認`, `${action.client || '対象client'}の検索後に最終判断を記録し、判定可能な週を増やします。`, '計測内訳を見る'],
    verify_auto_search_flow: ['自動検索の動線を確認', `観測開始後 ${action.weeks || 0}週で対象検索がありません。`, '検索品質を見る'],
    observe_more_weeks: ['観測を継続', `4週判定まで、あと${action.weeks_remaining || 0}完了週の観測が必要です。`, null],
    inspect_below_target_week: [`${action.week || '対象週'}の未達要因を確認`, `強い影響の報告は${action.strong_decisions || 0}件、目標は${action.target || 0}件です。`, '判断内訳を見る'],
    none: ['現在、優先対応はありません', '同じ基準で週次観測を継続します。', null],
  };
  return copies[code] || ['観測状態を確認', '詳細データを確認してください。', '詳細を見る'];
}

function switchMetricsPanel(panelId, focusTab = false) {
  const panels = ['decisionValuePanel', 'searchQualityPanel', 'dataStatePanel'];
  const tabs = ['decisionValueTab', 'searchQualityTab', 'dataStateTab'];
  activeMetricsPanel = panels.includes(panelId) ? panelId : panels[0];
  panels.forEach((id, index) => {
    const selected = id === activeMetricsPanel;
    document.getElementById(id).hidden = !selected;
    const tab = document.getElementById(tabs[index]);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focusTab) tab.focus();
  });
  scheduleChartRerender();
}

function renderDecisionValue(value) {
  const summary = document.getElementById('decisionValueSummary');
  const title = document.getElementById('decisionValueTitle');
  const reason = document.getElementById('decisionValueReason');
  const status = String(value.status || 'insufficient_data');
  const fourWeek = value.four_week || {};
  const evaluable = numberOrNull(fourWeek.evaluable_weeks) || 0;
  const targetMet = numberOrNull(fourWeek.target_met_weeks) || 0;
  const required = numberOrNull(fourWeek.required_weeks) || 4;
  const labels = {
    observed_sustained: '4週価値目標を達成（観測上）',
    target_not_met: '4週価値目標は未達',
    insufficient_data: 'データ不足 — 判定保留',
  };
  const verdictLabels = {
    observed_sustained: ['達成', 'pass'],
    target_not_met: ['未達', 'fail'],
    insufficient_data: ['判定保留', ''],
  };
  title.textContent = labels[status] || labels.insufficient_data;
  summary.dataset.tone = status === 'observed_sustained' ? 'good' : 'attention';
  const [verdictText, verdictTone] = verdictLabels[status] || verdictLabels.insufficient_data;
  const verdict = document.getElementById('decisionValueVerdict');
  verdict.className = `tag ${verdictTone}`.trim();
  verdict.textContent = verdictText;
  if (status === 'observed_sustained') {
    reason.textContent = `4完了週すべてで、強い影響の報告が週${fourWeek.weekly_target || 3}件以上あり、計測欠損もありません。`;
  } else if (status === 'target_not_met') {
    reason.textContent = `${required}完了週は計測できましたが、価値目標を満たしたのは${targetMet}週です。`;
  } else {
    reason.textContent = `判定可能な完了週は${evaluable}/${required}週です。未計測や観測開始前の週を0件として扱わず、判定を保留しています。`;
  }

  const stats = document.getElementById('decisionValueStats');
  clearElement(stats);
  const recent = value.recent || {};
  const recentRate = numberOrNull(recent.measurement_rate);
  const recentTarget = numberOrNull(recent.target_rate);
  const coverageMet = recentRate !== null && recentTarget !== null && recentRate >= recentTarget;
  addStatTile(stats, {
    label: `観測カバレッジ / 直近${recent.days || 7}日`,
    value: percent(recent.measurement_rate),
    ratio: recentRate,
    tag: recentRate === null ? null : (coverageMet ? '目標達成' : '目標未達'),
    tone: coverageMet ? 'pass' : 'fail',
    note: `${numberOrNull(recent.resolved_searches) || 0} / ${numberOrNull(recent.measurable_searches) || 0} 検索`,
  });
  addStatTile(stats, {
    label: '判定可能な完了週',
    value: `${evaluable}/${required}`,
    unit: '週',
    ratio: required > 0 ? evaluable / required : null,
    tag: evaluable === required ? '全週計測' : `判定不能 ${Math.max(0, required - evaluable)}週`,
    tone: evaluable === required ? 'pass' : '',
    note: `目標達成 ${targetMet}週`,
  });
  const weekly = Array.isArray(value.weekly) ? value.weekly : [];
  const latest = weekly.at(-1) || {};
  const latestTarget = numberOrNull(latest.target) || 3;
  const latestStrong = numberOrNull(latest.strong_decisions) || 0;
  addStatTile(stats, {
    // 件数対目標は 100% を超え得るため、頭打ちするメーターは付けない
    label: '強い影響の報告 / 直近完了週',
    value: String(latestStrong),
    unit: '件',
    tag: latest.evaluable ? (latest.target_met ? '目標達成' : '目標未達') : '判定保留',
    tone: latest.evaluable && latest.target_met ? 'pass' : (latest.evaluable ? 'fail' : ''),
    note: latest.evaluable ? `基準 ${latestTarget}件` : '計測不足',
  });
  renderDecisionValueRows(weekly);

  const action = value.next_action || {};
  const [actionTitle, actionText, buttonText] = nextActionCopy(action);
  document.getElementById('decisionNextActionTitle').textContent = actionTitle;
  document.getElementById('decisionNextActionText').textContent = actionText;
  const button = document.getElementById('decisionNextActionButton');
  button.hidden = !buttonText;
  button.textContent = buttonText || '';
  button.onclick = () => {
    const destination = action.destination;
    if (destination === 'search_quality') switchMetricsPanel('searchQualityPanel', true);
    else if (destination === 'data_quality') switchMetricsPanel('dataStatePanel', true);
    else {
      const details = document.getElementById('decisionBreakdownDetails');
      if (details) details.open = true;
    }
  };
}

function emptyTableRow(tbody, columns, message) {
  const tr = document.createElement('tr');
  tr.className = 'empty-row';
  const td = document.createElement('td');
  td.colSpan = columns;
  td.textContent = message;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

function renderZeroHits(rows) {
  const tbody = document.getElementById('zeroHitRows');
  clearElement(tbody);
  if (!rows.length) {
    emptyTableRow(tbody, 4, '結果が 0 件だった検索はありません。');
    return;
  }
  rows.slice(0, 10).forEach(row => {
    const tr = document.createElement('tr');
    const query = document.createElement('td');
    query.textContent = row.query || '（空のクエリ）';
    const count = document.createElement('td');
    count.className = 'num';
    count.textContent = String(numberOrNull(row.count) || 0);
    const last = document.createElement('td');
    last.className = 'mono';
    last.textContent = formatDateTime(row.last_ts);
    const clients = document.createElement('td');
    clients.className = 'mono';
    clients.textContent = Array.isArray(row.clients) ? row.clients.join(', ') : '—';
    tr.append(query, count, last, clients);
    tbody.appendChild(tr);
  });
}

function renderUnreturned(unreturned, corpusAvailable) {
  const tbody = document.getElementById('unreturnedRows');
  clearElement(tbody);
  if (corpusAvailable === false) {
    emptyTableRow(tbody, 3, '現在の保存方式では、登録データの状態を集計できません。');
    return;
  }
  const rows = Array.isArray(unreturned.items) ? unreturned.items : [];
  if (!rows.length) {
    emptyTableRow(tbody, 3, '検索結果に出ていない有効なファクトはありません。');
    return;
  }
  rows.slice(0, 10).forEach(row => {
    const tr = document.createElement('tr');
    const statement = document.createElement('td');
    statement.textContent = row.statement || '（内容なし）';
    const namespace = document.createElement('td');
    namespace.className = 'mono';
    namespace.textContent = nsLabel(row.namespace);
    const id = document.createElement('td');
    id.className = 'mono';
    id.textContent = row.id || row.fact_id || '—';
    tr.append(statement, namespace, id);
    tbody.appendChild(tr);
  });
}

function renderOperationalReadiness(readiness) {
  const statusHost = document.getElementById('readinessStatus');
  const tbody = document.getElementById('readinessRows');
  const note = document.getElementById('readinessNote');
  clearElement(statusHost);
  clearElement(tbody);
  const status = String(readiness.status || 'insufficient_data');
  const labels = {
    ready: '運用証拠が充足',
    needs_work: '改善が必要',
    insufficient_data: '観測中',
  };
  const tone = status === 'ready' ? 'pass' : (status === 'needs_work' ? 'fail' : '');
  const count = document.createElement('span');
  count.className = 'gate-count';
  count.textContent = `${numberOrNull(readiness.passed_gates) || 0} / ${numberOrNull(readiness.total_gates) || 0} ゲート達成`;
  statusHost.append(makeTag(labels[status] || status, tone), count);

  const gateLabels = {
    pass: '達成',
    fail: '未達',
    insufficient: 'データ不足',
    stale: '評価期限切れ',
  };
  const gates = Array.isArray(readiness.gates) ? readiness.gates : [];
  if (!gates.length) {
    emptyTableRow(tbody, 4, '実運用ゲートを集計できません。');
  } else {
    gates.forEach(gate => {
      const tr = document.createElement('tr');
      const label = document.createElement('td');
      label.textContent = gate.label || gate.id || '—';
      const verdict = document.createElement('td');
      verdict.appendChild(makeTag(
        gateLabels[gate.status] || gate.status || '—',
        gate.status === 'pass' ? 'pass' : (gate.status === 'fail' ? 'fail' : ''),
      ));
      const current = document.createElement('td');
      current.className = 'mono';
      current.textContent = gate.current || '—';
      const target = document.createElement('td');
      target.className = 'mono';
      target.textContent = gate.target || '—';
      tr.append(label, verdict, current, target);
      tbody.appendChild(tr);
    });
  }
  note.textContent = readiness.note || '';
}

function renderMeasurementClients(rows) {
  const tbody = document.getElementById('measurementClientRows');
  clearElement(tbody);
  if (!rows.length) {
    emptyTableRow(tbody, 5, '最終判断まで計測できる検索がありません。');
    return;
  }
  rows.slice(0, 10).forEach(row => {
    const tr = document.createElement('tr');
    const client = document.createElement('td');
    client.className = 'mono';
    client.textContent = row.client || 'unknown';
    tr.appendChild(client);
    [numberOrNull(row.measurable) || 0, numberOrNull(row.resolved) || 0,
      percent(row.measurement_rate), numberOrNull(row.strong) || 0].forEach(value => {
      const td = document.createElement('td');
      td.className = 'num';
      td.textContent = String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderOperationTraces(value) {
  const stats = document.getElementById('operationTraceStats');
  clearElement(stats);
  const required = numberOrNull(value.plk_required) || 0;
  const searched = numberOrNull(value.required_searched) || 0;
  addStatTile(stats, {
    label: '申告trace内の事前検索率',
    value: percent(value.required_search_rate),
    ratio: value.required_search_rate,
    tag: required === 0 ? 'データ不足' : (searched === required ? '全件検索' : `検索漏れ ${required - searched}件`),
    tone: required > 0 && searched === required ? 'pass' : (required > 0 ? 'fail' : ''),
    note: `${searched} / ${required} PLK必須trace（未trace操作は対象外）`,
  });
  addStatTile(stats, {
    label: '操作の終了記録trace',
    value: String(numberOrNull(value.with_action_completion) || 0),
    unit: '件',
    tag: `試行 ${numberOrNull(value.with_action_attempt) || 0}件`,
    note: `成功 ${numberOrNull((value.terminal_outcomes || {}).succeeded) || 0} / 失敗 ${numberOrNull((value.terminal_outcomes || {}).failed) || 0} / 停止 ${numberOrNull((value.terminal_outcomes || {}).blocked) || 0}`,
  });
  addStatTile(stats, {
    label: '判断を結んだ完了操作',
    value: String(numberOrNull(value.decision_linked_actions) || 0),
    unit: '件',
    tag: '観測値',
    note: 'PLKによる因果効果そのものは示しません',
  });

  const tbody = document.getElementById('operationTraceClientRows');
  clearElement(tbody);
  const rows = Array.isArray(value.clients) ? value.clients : [];
  if (!rows.length) {
    emptyTableRow(tbody, 5, '操作traceはまだ記録されていません。');
    return;
  }
  rows.forEach(row => {
    const tr = document.createElement('tr');
    const client = document.createElement('td');
    client.className = 'mono';
    client.textContent = row.client || 'unknown';
    tr.appendChild(client);
    [numberOrNull(row.intents) || 0, numberOrNull(row.plk_required) || 0,
      numberOrNull(row.required_searched) || 0, percent(row.required_search_rate)].forEach(value => {
      const td = document.createElement('td');
      td.className = 'num';
      td.textContent = String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderContributionFacts(rows) {
  const tbody = document.getElementById('contributionFactRows');
  clearElement(tbody);
  if (!rows.length) {
    emptyTableRow(tbody, 4, '観測利用を集計できるファクトがありません。');
    return;
  }
  rows.slice(0, 10).forEach(row => {
    const tr = document.createElement('tr');
    const statementTd = document.createElement('td');
    if (row.statement) {
      statementTd.textContent = row.statement;
      statementTd.title = row.fact_id || '';
    } else {
      statementTd.textContent = row.fact_id || '—';
      statementTd.className = 'mono';
    }
    tr.appendChild(statementTd);
    [numberOrNull(row.returned_searches) || 0,
      numberOrNull(row.used_decisions) || 0, numberOrNull(row.strong_decisions) || 0].forEach(value => {
      const td = document.createElement('td');
      td.className = value === 0 ? 'num dim' : 'num';
      td.textContent = String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

// チャートだけを再描画する（リサイズ・タブ切替・disclosure展開で呼ばれる）
function renderMetricsCharts(data) {
  const search = data.search || {};
  const weekly = Array.isArray(search.weekly) ? search.weekly : [];
  const corpus = data.corpus || {};
  const contribution = data.contribution || {};
  const decisionWeekly = Array.isArray((data.decision_value || {}).weekly) ? data.decision_value.weekly : [];
  renderDecisionValueChart(decisionWeekly);
  renderWeeklySearch(weekly);
  renderReturnRate(weekly);
  renderEval(data.eval || {});
  const namespaceRows = (Array.isArray(corpus.namespaces) ? corpus.namespaces : []).map(row => ({
    ...row, label: nsLabel(row.namespace),
  }));
  renderHorizontalBars(
    'namespaceChart',
    namespaceRows,
    'count', 'label',
    corpus.available === false ? '現在の保存方式では、登録データの状態を集計できません。' : '有効なファクトがありません。',
    row => nsColorVar(row.namespace),
  );
  renderHorizontalBars('clientChart', Array.isArray(search.clients) ? search.clients : [], 'count', 'client', '検索ログがありません。');
  const effectLabels = {
    changed_action: '行動を変更',
    prevented_error: '誤りを防止',
    confirmed: '確認を補強',
    none: '不採用',
  };
  const effectRows = Object.entries(contribution.effects || {}).map(([effect, count]) => ({
    label: effectLabels[effect] || effect, count,
  }));
  renderHorizontalBars('effectChart', effectRows, 'count', 'label', '最終判断の記録がありません。');
  const reasonLabels = {
    irrelevant: '関連しない',
    already_known: '既知だった',
    stale: '古い',
    conflict: '矛盾した',
    insufficient: '不十分',
  };
  const reasonRows = (Array.isArray(contribution.no_use_reasons) ? contribution.no_use_reasons : []).map(row => ({
    label: reasonLabels[row.reason] || row.reason, count: row.count,
  }));
  renderHorizontalBars('noUseReasonChart', reasonRows, 'count', 'label', '不採用の記録はありません。');
}

function renderMetrics(data) {
  lastMetricsData = data;
  const corpus = data.corpus || {};
  const contribution = data.contribution || {};
  renderDecisionValue(data.decision_value || {});
  renderOperationTraces(data.operation_traces || {});
  renderOperationalReadiness(data.operational_readiness || {});
  renderMetricsCharts(data);
  renderMeasurementClients(Array.isArray(contribution.clients) ? contribution.clients : []);
  renderContributionFacts(Array.isArray(contribution.facts) ? contribution.facts : []);
  renderZeroHits(Array.isArray(data.zero_hit) ? data.zero_hit : []);
  renderUnreturned(corpus.unreturned || {}, corpus.available);
  const generated = document.getElementById('metricsStatus');
  generated.className = 'metrics-status';
  generated.textContent = data.generated_at ? `集計日時: ${formatDateTime(data.generated_at)}` : '集計完了';
  metricsLastSuccessAt = Date.now();
  if (metricsStaleTimer) window.clearTimeout(metricsStaleTimer);
  metricsStaleTimer = window.setTimeout(() => {
    if (!metricsLastSuccessAt || Date.now() - metricsLastSuccessAt < 15 * 60 * 1000) return;
    generated.className = 'metrics-status error';
    generated.textContent = `15分以上更新されていません。最終成功: ${new Date(metricsLastSuccessAt).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}`;
  }, 15 * 60 * 1000 + 250);
}

async function loadMetrics(force = false) {
  if (metricsLoaded && !force) return;
  const status = document.getElementById('metricsStatus');
  const refresh = document.getElementById('metricsRefresh');
  status.className = 'metrics-status';
  status.textContent = '読み込み中…';
  refresh.disabled = true;
  try {
    const response = await fetch('/ui/api/metrics');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderMetrics(data);
    metricsLoaded = true;
  } catch (error) {
    status.className = 'metrics-status error';
    const lastSuccess = metricsLastSuccessAt
      ? ` 最終成功: ${new Date(metricsLastSuccessAt).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}`
      : '';
    status.textContent = `更新失敗: ${error.message}.${lastSuccess}`;
  } finally {
    refresh.disabled = false;
  }
}

function switchView(view) {
  state.view = view === 'metrics' ? 'metrics' : 'facts';
  const isMetrics = state.view === 'metrics';
  const factsView = document.getElementById('factsView');
  const metricsView = document.getElementById('metricsView');
  factsView.hidden = isMetrics;
  factsView.style.display = isMetrics ? 'none' : 'block';
  metricsView.hidden = !isMetrics;
  metricsView.style.display = isMetrics ? 'block' : 'none';
  document.getElementById('factsTab').setAttribute('aria-selected', String(!isMetrics));
  document.getElementById('metricsTab').setAttribute('aria-selected', String(isMetrics));
  if (isMetrics) {
    closeDetailPanel();
    loadMetrics();
    scheduleChartRerender();
  }
}

function updateSortArrow() {
  const arrow = document.querySelector('#sortByCreated .arrow');
  arrow.textContent = state.sortDir === 'desc' ? '▾' : '▴';
}

async function init() {
  initNsBar();
  initStatusToggle();
  initKindToggle();

  document.getElementById('loginBtn').addEventListener('click', login);
  document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') login(); });
  document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') load(); });
  document.getElementById('scrim').addEventListener('click', closeDetailPanel);
  document.getElementById('sortByCreated').addEventListener('click', () => {
    state.sortDir = state.sortDir === 'desc' ? 'asc' : 'desc';
    updateSortArrow();
    renderList();
  });
  document.getElementById('factsTab').addEventListener('click', () => switchView('facts'));
  document.getElementById('metricsTab').addEventListener('click', () => switchView('metrics'));
  document.getElementById('metricsRefresh').addEventListener('click', () => loadMetrics(true));
  const metricsTabs = [
    ['decisionValueTab', 'decisionValuePanel'],
    ['searchQualityTab', 'searchQualityPanel'],
    ['dataStateTab', 'dataStatePanel'],
  ];
  metricsTabs.forEach(([tabId, panelId], index) => {
    const tab = document.getElementById(tabId);
    tab.addEventListener('click', () => switchMetricsPanel(panelId));
    tab.addEventListener('keydown', event => {
      let next = null;
      if (event.key === 'ArrowRight') next = (index + 1) % metricsTabs.length;
      if (event.key === 'ArrowLeft') next = (index - 1 + metricsTabs.length) % metricsTabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = metricsTabs.length - 1;
      if (next === null) return;
      event.preventDefault();
      switchMetricsPanel(metricsTabs[next][1], true);
    });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.getElementById('detail').classList.contains('open')) closeDetailPanel();
  });
  window.addEventListener('resize', scheduleChartRerender);
  const breakdown = document.getElementById('decisionBreakdownDetails');
  if (breakdown) breakdown.addEventListener('toggle', scheduleChartRerender);
  // window の resize だけでは、disclosure 展開やスクロールバー出現による
  // カード幅の変化を拾えず、SVG が旧幅のまま中央に浮いて残る
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(entries => {
      const changed = entries.some(entry => {
        const drawn = Number(entry.target.dataset.drawnWidth || 0);
        return drawn > 0 && Math.abs(entry.contentRect.width - drawn) > 1;
      });
      if (changed) scheduleChartRerender();
    });
    document.querySelectorAll('.chart').forEach(chart => observer.observe(chart));
  }

  // 既存の HttpOnly cookie セッションが有効なら、ログイン画面を出さず一覧を直接表示する
  const session = await fetch('/ui/session');
  if (session.ok) {
    const sessionData = await session.json();
    state.csrf = sessionData.csrf || null;
  }
  const r = await fetch('/ui/api/facts?status=active');
  if (r.ok) {
    const data = await r.json();
    enterMain();
    currentFacts = data.facts || [];
    document.getElementById('metaRow').textContent = `${currentFacts.length} 件 · すべて · すべてのkind · 有効`;
    renderList();
  } else if (r.status === 401) {
    document.getElementById('login').style.display = 'block';
  }
}

init();
