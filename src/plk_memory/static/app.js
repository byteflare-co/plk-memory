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
const CHART_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#a78bfa', '#ec4899', '#06b6d4', '#f87171', '#84cc16'];

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

function makeChart(host, label, width = 760, height = 240) {
  clearElement(host);
  const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': label });
  host.appendChild(svg);
  return svg;
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
    swatch.className = 'legend-swatch';
    swatch.style.background = item.color;
    const label = document.createElement('span');
    label.textContent = item.label;
    row.append(swatch, label);
    legend.appendChild(row);
  });
  host.appendChild(legend);
  return legend;
}

function drawGrid(svg, { left, top, width, height, ticks = 4, maxValue = 1, formatter = String }) {
  for (let i = 0; i <= ticks; i += 1) {
    const y = top + (height * i / ticks);
    svg.appendChild(svgElement('line', { x1: left, y1: y, x2: left + width, y2: y, stroke: 'var(--border)', 'stroke-width': 1 }));
    svgText(svg, formatter(maxValue * (ticks - i) / ticks), {
      x: left - 8, y: y + 4, fill: 'var(--text-muted)', 'font-size': 12, 'text-anchor': 'end',
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
  const svg = makeChart(host, '週別検索数の積み上げ棒グラフ');
  const left = 48; const top = 12; const width = 694; const height = 180;
  const maxValue = Math.max(1, ...weekly.map(row => (numberOrNull(row.auto) || 0) + (numberOrNull(row.manual) || 0)));
  drawGrid(svg, { left, top, width, height, maxValue, formatter: value => String(Math.round(value)) });
  const slot = width / weekly.length;
  const barWidth = Math.max(8, Math.min(38, slot * .58));
  weekly.forEach((row, index) => {
    const auto = Math.max(0, numberOrNull(row.auto) || 0);
    const manual = Math.max(0, numberOrNull(row.manual) || 0);
    const autoHeight = height * auto / maxValue;
    const manualHeight = height * manual / maxValue;
    const x = left + slot * index + (slot - barWidth) / 2;
    const autoRect = svgElement('rect', { x, y: top + height - autoHeight, width: barWidth, height: autoHeight, rx: 2, fill: CHART_COLORS[0] });
    const autoTitle = svgElement('title');
    autoTitle.textContent = `${String(row.week || '')}: 自動検索 ${auto}`;
    autoRect.appendChild(autoTitle);
    svg.appendChild(autoRect);
    const manualRect = svgElement('rect', { x, y: top + height - autoHeight - manualHeight, width: barWidth, height: manualHeight, rx: 2, fill: CHART_COLORS[2] });
    const manualTitle = svgElement('title');
    manualTitle.textContent = `${String(row.week || '')}: 手動検索 ${manual}`;
    manualRect.appendChild(manualTitle);
    svg.appendChild(manualRect);
    svgText(svg, compactWeek(row.week) + (row.in_progress ? '*' : ''), {
      x: x + barWidth / 2, y: 220, fill: 'var(--text-muted)', 'font-size': 11, 'text-anchor': 'middle',
    });
  });
  let failurePath = '';
  weekly.forEach((row, index) => {
    const failures = Math.max(0, numberOrNull(row.failures) || 0);
    const x = left + slot * index + slot / 2;
    const y = top + height * (1 - failures / maxValue);
    failurePath += `${failurePath ? ' L' : 'M'} ${x} ${y}`;
    const marker = svgElement('circle', { cx: x, cy: y, r: 3, fill: CHART_COLORS[6] });
    const title = svgElement('title');
    title.textContent = `${String(row.week || '')}: 障害 ${failures}`;
    marker.appendChild(title);
    svg.appendChild(marker);
  });
  const firstMarker = svg.querySelector('circle');
  if (failurePath && firstMarker) {
    svg.insertBefore(svgElement('path', {
      d: failurePath, fill: 'none', stroke: CHART_COLORS[6], 'stroke-width': 2,
    }), firstMarker);
  }
  const legend = appendLegend(host, [
    { label: '自動検索', color: CHART_COLORS[0] },
    { label: '手動検索', color: CHART_COLORS[2] },
    { label: '障害', color: CHART_COLORS[6] },
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
  const svg = makeChart(host, '週別結果返却率の折れ線グラフ', 600, 240);
  const left = 48; const top = 12; const width = 532; const height = 180;
  drawGrid(svg, { left, top, width, height, maxValue: 1, formatter: value => `${Math.round(value * 100)}%` });
  const step = points.length > 1 ? width / (points.length - 1) : 0;
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
    const circle = svgElement('circle', { cx: x, cy: y, r: 3.5, fill: CHART_COLORS[1] });
    const title = svgElement('title');
    title.textContent = `${String(point.week || '')}: ${percent(point.rate)}`;
    circle.appendChild(title);
    svg.appendChild(circle);
    svgText(svg, compactWeek(point.week) + (point.inProgress ? '*' : ''), {
      x, y: 220, fill: 'var(--text-muted)', 'font-size': 11, 'text-anchor': 'middle',
    });
  });
  if (path) paths.push(path);
  const firstPoint = svg.querySelector('circle');
  paths.forEach(segment => svg.insertBefore(
    svgElement('path', { d: segment, fill: 'none', stroke: CHART_COLORS[1], 'stroke-width': 2 }),
    firstPoint,
  ));
  const legend = appendLegend(host, [{ label: '結果返却率', color: CHART_COLORS[1] }]);
  const progressNote = document.createElement('span');
  progressNote.textContent = '* 進行中の週';
  legend.appendChild(progressNote);
}

function renderHorizontalBars(hostId, rows, valueKey, labelKey, emptyMessage) {
  const host = document.getElementById(hostId);
  if (!rows.length) {
    renderChartEmpty(host, emptyMessage);
    return;
  }
  const shown = rows.slice(0, 10);
  const height = Math.max(240, shown.length * 32 + 28);
  const svg = makeChart(host, `${hostId} 横棒グラフ`, 600, height);
  svg.style.height = `${height}px`;
  const left = 170; const width = 390;
  const maxValue = Math.max(1, ...shown.map(row => numberOrNull(row[valueKey]) || 0));
  shown.forEach((row, index) => {
    const value = Math.max(0, numberOrNull(row[valueKey]) || 0);
    const y = 14 + index * 32;
    svgText(svg, row[labelKey] || '—', { x: left - 10, y: y + 15, fill: 'var(--text-muted)', 'font-size': 12, 'text-anchor': 'end' });
    svg.appendChild(svgElement('rect', { x: left, y, width: width * value / maxValue, height: 20, rx: 3, fill: CHART_COLORS[index % CHART_COLORS.length] }));
    svgText(svg, value, { x: left + width * value / maxValue + 7, y: y + 15, fill: 'var(--text)', 'font-size': 12 });
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
  const svg = makeChart(host, '上位5件の正解率と検索順位スコアの折れ線グラフ', 600, 240);
  const left = 48; const top = 12; const width = 532; const height = 180;
  drawGrid(svg, { left, top, width, height, maxValue: 1, formatter: value => `${Math.round(value * 100)}%` });
  const timestamps = [...new Set(series.flatMap(item => item.points.map(point => String(point.ts || ''))))].sort();
  const xFor = ts => timestamps.length > 1 ? left + width * timestamps.indexOf(String(ts || '')) / (timestamps.length - 1) : left + width / 2;
  const legend = [];
  series.forEach((item, seriesIndex) => {
    const baseColor = CHART_COLORS[seriesIndex % CHART_COLORS.length];
    [['hit5_rate', false], ['mrr', true]].forEach(([field, dashed]) => {
      let path = '';
      item.points.forEach(point => {
        const value = numberOrNull(point[field]);
        if (value === null) return;
        const x = xFor(point.ts);
        const y = top + height * (1 - Math.max(0, Math.min(1, value)));
        path += `${path ? ' L' : 'M'} ${x} ${y}`;
        const circle = svgElement('circle', { cx: x, cy: y, r: 2.8, fill: baseColor });
        const title = svgElement('title');
        const scoreName = field === 'hit5_rate' ? '上位5件の正解率' : '検索順位スコア';
        title.textContent = `${item.runner} / ${item.hash} / ${scoreName}: ${percent(value)}`;
        circle.appendChild(title);
        svg.appendChild(circle);
      });
      if (path) {
        const attrs = { d: path, fill: 'none', stroke: baseColor, 'stroke-width': dashed ? 1.5 : 2.4 };
        if (dashed) attrs['stroke-dasharray'] = '5 4';
        svg.insertBefore(svgElement('path', attrs), svg.querySelector('circle'));
      }
      legend.push({ label: `${item.runner} · ${item.hash} · ${field === 'hit5_rate' ? '上位5件の正解率' : '検索順位スコア'}`, color: baseColor });
    });
  });
  const labels = timestamps.length > 5 ? timestamps.filter((_, index) => index % Math.ceil(timestamps.length / 5) === 0) : timestamps;
  labels.forEach(ts => svgText(svg, formatDate(ts), { x: xFor(ts), y: 220, fill: 'var(--text-muted)', 'font-size': 11, 'text-anchor': 'middle' }));
  appendLegend(host, legend);
}

function addStatTile(host, label, value, note, valueClass = '') {
  const tile = document.createElement('div');
  tile.className = 'stat-tile';
  const labelEl = document.createElement('div');
  labelEl.className = 'stat-label';
  labelEl.textContent = label;
  const valueEl = document.createElement('div');
  valueEl.className = `stat-value ${valueClass}`.trim();
  valueEl.textContent = value;
  const noteEl = document.createElement('div');
  noteEl.className = 'stat-note';
  noteEl.textContent = note;
  tile.append(labelEl, valueEl, noteEl);
  host.appendChild(tile);
}

function renderDecisionValueChart(weekly) {
  const host = document.getElementById('decisionValueChart');
  if (!weekly.length) {
    renderChartEmpty(host, '4完了週の観測データがまだありません。');
    return;
  }
  const svg = makeChart(host, '直近4完了週の強い影響報告と観測カバレッジ', 760, 270);
  const description = svgElement('desc');
  description.textContent = '行動変更と誤り防止の報告数を週別に積み上げ、週3件の目標線と観測カバレッジを表示します。';
  svg.appendChild(description);
  const left = 52; const top = 18; const width = 680; const height = 170;
  const target = Math.max(1, ...weekly.map(row => numberOrNull(row.target) || 0));
  const maxValue = Math.max(target + 1, ...weekly.map(row => numberOrNull(row.strong_decisions) || 0));
  drawGrid(svg, { left, top, width, height, maxValue, formatter: value => String(Math.round(value)) });
  const slot = width / weekly.length;
  const barWidth = Math.min(70, slot * .48);
  weekly.forEach((row, index) => {
    const changed = Math.max(0, numberOrNull(row.changed_action_decisions) || 0);
    const prevented = Math.max(0, numberOrNull(row.prevented_error_decisions) || 0);
    const x = left + slot * index + (slot - barWidth) / 2;
    const changedHeight = height * changed / maxValue;
    const preventedHeight = height * prevented / maxValue;
    const opacity = row.evaluable ? 1 : .38;
    const changedRect = svgElement('rect', {
      x, y: top + height - changedHeight, width: barWidth, height: changedHeight,
      rx: 3, fill: CHART_COLORS[0], opacity,
    });
    const changedTitle = svgElement('title');
    changedTitle.textContent = `${row.week}: 行動変更 ${changed}件`;
    changedRect.appendChild(changedTitle);
    svg.appendChild(changedRect);
    const preventedRect = svgElement('rect', {
      x, y: top + height - changedHeight - preventedHeight, width: barWidth,
      height: preventedHeight, rx: 3, fill: CHART_COLORS[1], opacity,
    });
    const preventedTitle = svgElement('title');
    preventedTitle.textContent = `${row.week}: 誤り防止 ${prevented}件`;
    preventedRect.appendChild(preventedTitle);
    svg.appendChild(preventedRect);
    svgText(svg, compactWeek(row.week), {
      x: x + barWidth / 2, y: 216, fill: 'var(--text-muted)', 'font-size': 12, 'text-anchor': 'middle',
    });
    const coverage = numberOrNull(row.auto_measurement_rate);
    svgText(svg, row.evaluable ? `計測 ${percent(coverage)}` : '判定不能', {
      x: x + barWidth / 2, y: 238,
      fill: row.evaluable ? 'var(--success)' : 'var(--warning)',
      'font-size': 11, 'font-weight': 650, 'text-anchor': 'middle',
    });
  });
  const targetY = top + height * (1 - target / maxValue);
  svg.appendChild(svgElement('line', {
    x1: left, y1: targetY, x2: left + width, y2: targetY,
    stroke: CHART_COLORS[2], 'stroke-width': 2, 'stroke-dasharray': '6 5',
  }));
  svgText(svg, `目標 ${target}件`, {
    x: left + width, y: targetY - 6, fill: CHART_COLORS[2],
    'font-size': 11, 'text-anchor': 'end',
  });
  appendLegend(host, [
    { label: '行動を変更', color: CHART_COLORS[0] },
    { label: '誤りを防止', color: CHART_COLORS[1] },
    { label: '週次目標', color: CHART_COLORS[2] },
  ]);
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
    const status = row.evaluable
      ? (row.target_met ? '目標達成' : '目標未達')
      : `判定不能（${(row.unevaluable_reasons || []).join(', ') || 'データ不足'}）`;
    [
      row.week || '—',
      numberOrNull(row.auto_measurable_searches) || 0,
      numberOrNull(row.auto_resolved_searches) || 0,
      percent(row.auto_measurement_rate),
      numberOrNull(row.changed_action_decisions) || 0,
      numberOrNull(row.prevented_error_decisions) || 0,
      status,
    ].forEach((value, index) => {
      const td = document.createElement('td');
      td.textContent = String(value);
      if (index === 6) td.className = row.target_met ? 'success-text' : 'danger-text';
      tr.appendChild(td);
    });
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
  title.textContent = labels[status] || labels.insufficient_data;
  summary.dataset.tone = status === 'observed_sustained' ? 'good' : 'attention';
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
  addStatTile(
    stats,
    `直近${recent.days || 7}日の観測カバレッジ`,
    percent(recent.measurement_rate),
    `${numberOrNull(recent.resolved_searches) || 0} / ${numberOrNull(recent.measurable_searches) || 0}検索`,
    recentRate !== null && recentTarget !== null && recentRate >= recentTarget ? 'ok' : 'warn',
  );
  addStatTile(stats, '判定可能な完了週', `${evaluable} / ${required}週`, `判定不能 ${Math.max(0, required - evaluable)}週`, evaluable === required ? 'ok' : 'warn');
  const weekly = Array.isArray(value.weekly) ? value.weekly : [];
  const latest = weekly.at(-1) || {};
  addStatTile(
    stats,
    '直近完了週の強い影響報告',
    `${numberOrNull(latest.strong_decisions) || 0}件`,
    latest.evaluable ? `基準 ${numberOrNull(latest.target) || 3}件` : '計測不足のため週次判定は保留',
    latest.evaluable && latest.target_met ? 'ok' : 'warn',
  );
  renderDecisionValueChart(weekly);
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

function last7dReturnRate(search) {
  const direct = numberOrNull(search.last7d_return_rate);
  if (direct !== null) return direct;
  const bucket = search.last7d || {};
  const bucketRate = numberOrNull(bucket.return_rate);
  if (bucketRate !== null) return bucketRate;
  const okTotal = numberOrNull(bucket.ok_total);
  return okTotal > 0 ? Number(bucket.returned || 0) / okTotal : null;
}

function weeklySearchCount(row) {
  return (numberOrNull(row.auto) || 0) + (numberOrNull(row.manual) || 0);
}

function weeklyReturnRate(row) {
  const total = numberOrNull(row.ok_total);
  return total > 0 ? Number(row.returned || 0) / total : null;
}

function signedCount(value, unit) {
  const rounded = Math.round(value);
  return `${rounded > 0 ? '+' : ''}${rounded}${unit}`;
}

function renderMetricsSummary(data) {
  const summary = document.getElementById('metricsSummary');
  const title = document.getElementById('metricsSummaryTitle');
  const lead = document.getElementById('metricsSummaryLead');
  const usageSummary = document.getElementById('metricsUsageSummary');
  const valueSummary = document.getElementById('metricsValueSummary');
  const actionSummary = document.getElementById('metricsActionSummary');
  const search = data.search || {};
  const contribution = data.contribution || {};
  const weekly = Array.isArray(search.weekly) ? search.weekly : [];
  const last7 = search.last7d || {};
  const okTotal = numberOrNull(last7.ok_total) || 0;
  const returned = numberOrNull(last7.returned) || 0;
  const noResult = Math.max(0, okTotal - returned);
  const failures = weekly.reduce((sum, row) => sum + (numberOrNull(row.failures) || 0), 0);
  const total = numberOrNull(search.total) || 0;
  const current = weekly.findLast(row => row.in_progress) || weekly.at(-1) || {};
  const completed = weekly.filter(row => !row.in_progress && weeklyReturnRate(row) !== null);
  const latest = completed.at(-1);
  const previous = completed.at(-2);
  const evalAvailable = Object.keys(data.eval || {}).length > 0;

  const measurable = numberOrNull(contribution.measurable_hit_searches) || 0;
  const resolved = numberOrNull(contribution.resolved_hit_searches) || 0;
  const strong = numberOrNull(contribution.strong_contribution_decisions) || 0;
  const adopted = numberOrNull(contribution.adopted_decisions) || 0;
  const unresolved = numberOrNull(contribution.unresolved_hit_searches) || 0;

  if (okTotal === 0) {
    summary.dataset.tone = 'attention';
    title.textContent = '改善を判断するための検索データがまだありません';
    lead.textContent = '検索が記録されると、利用量・結果返却率・前週からの変化をここに表示します。';
  } else if (measurable > 0 && resolved === 0) {
    summary.dataset.tone = 'attention';
    title.textContent = '検索は使われていますが、最終判断への貢献はまだ未計測です';
    lead.textContent = '結果が返った検索の後に plk_record_decision を記録すると、採用と強い貢献を分けて確認できます。';
  } else if (noResult === 0 && failures === 0 && unresolved === 0) {
    summary.dataset.tone = 'good';
    title.textContent = '検索から最終判断まで計測できています';
    lead.textContent = '自己申告の観測値として、採用された判断と行動変更・誤り防止への貢献を確認できます。';
  } else {
    summary.dataset.tone = 'attention';
    title.textContent = '検索の利用は進んでいます。未計測または結果 0 件の検索に改善余地があります';
    lead.textContent = '検索結果の返却と最終判断への貢献を分けて確認します。';
  }

  const currentCount = weeklySearchCount(current);
  usageSummary.textContent = `全期間で ${total} 回、${current.in_progress ? '今週' : '直近週'}は ${currentCount} 回検索されています。`;

  let trendText = '完了週が 2 週たまると、前週からの変化を表示します。';
  if (latest && previous) {
    const searchDelta = weeklySearchCount(latest) - weeklySearchCount(previous);
    const rateDelta = (weeklyReturnRate(latest) - weeklyReturnRate(previous)) * 100;
    trendText = `完了週の前週比は、検索数 ${signedCount(searchDelta, ' 回')}、結果返却率 ${signedCount(rateDelta, ' ポイント')}です。`;
  }
  valueSummary.textContent = `計測対象 ${measurable} 回中 ${resolved} 回を最終判断まで記録しました（${percent(contribution.measurement_rate)}）。採用 ${adopted} 件、うち行動変更・誤り防止 ${strong} 件です。`;

  const actions = [];
  if (unresolved > 0) actions.push(`未計測の ${unresolved} 回で最終判断を記録する`);
  if (noResult > 0) actions.push(`結果が 0 件だった ${noResult} 回の検索を見直す`);
  if (!evalAvailable) actions.push('検索精度の定期評価を実行する');
  if (failures > 0) actions.push(`${failures} 件の障害原因を確認する`);
  if (!actions.length) actions.push('現在の状態を維持し、週ごとの変化を確認する');
  actionSummary.textContent = `${actions.join('。')}。`;
}

function renderStats(data) {
  const host = document.getElementById('metricsStats');
  clearElement(host);
  const search = data.search || {};
  const contribution = data.contribution || {};
  const clients = Array.isArray(search.clients) ? search.clients : [];
  const weekly = Array.isArray(search.weekly) ? search.weekly : [];
  const total = numberOrNull(search.total) ?? clients.reduce((sum, row) => sum + (numberOrNull(row.count) || 0), 0);
  const failures = weekly.reduce((sum, row) => sum + (numberOrNull(row.failures) || 0), 0);
  const latency = search.latency || {};
  const last7dLatency = latency.last7d || {};
  addStatTile(host, '総検索数', String(total), `直近 12 週の障害 ${failures} 件`);
  addStatTile(host, '最終判断の計測率', percent(contribution.measurement_rate), `未計測 ${numberOrNull(contribution.unresolved_hit_searches) || 0} 回`);
  addStatTile(host, '採用された判断', String(numberOrNull(contribution.adopted_decisions) || 0), '確認補強を含む観測値');
  addStatTile(host, '強い貢献', String(numberOrNull(contribution.strong_contribution_decisions) || 0), '行動変更 + 誤り防止');
  addStatTile(host, '直近 7 日の結果返却率', percent(last7dReturnRate(search)), `応答時間の中央値 ${numberOrNull(last7dLatency.p50) ?? '—'} ms`);
  const corpus = data.corpus || {};
  const active = corpus.available === false ? '—' : String(numberOrNull((corpus.status || {}).active) ?? 0);
  addStatTile(host, '有効なファクト', active, corpus.available === false ? '現在の保存方式では集計できません' : `読み込めなかったファイル ${numberOrNull(corpus.skipped_files) || 0} 件`);
  const verdict = String((data.kill_criteria || {}).verdict || 'inconclusive');
  const verdictMeta = {
    observed_ok: ['基準内', 'ok'], observed_breached: ['基準未達', 'bad'], inconclusive: ['データ不足', 'warn'],
  }[verdict] || [verdict, 'warn'];
  addStatTile(host, '継続判断の参考値', verdictMeta[0], '強い貢献の観測数による参考判定', verdictMeta[1]);
  const readiness = data.operational_readiness || {};
  const readinessStatus = String(readiness.status || 'insufficient_data');
  const readinessMeta = {
    ready: ['運用証拠が充足', 'ok'],
    needs_work: ['改善が必要', 'bad'],
    insufficient_data: ['観測中', 'warn'],
  }[readinessStatus] || [readinessStatus, 'warn'];
  addStatTile(
    host,
    '実運用ゲート',
    `${numberOrNull(readiness.passed_gates) || 0}/${numberOrNull(readiness.total_gates) || 0}`,
    readinessMeta[0],
    readinessMeta[1],
  );
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
    count.textContent = String(numberOrNull(row.count) || 0);
    const last = document.createElement('td');
    last.className = 'mono';
    last.textContent = formatDateTime(row.last_ts);
    const clients = document.createElement('td');
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
    namespace.textContent = row.namespace || '—';
    const id = document.createElement('td');
    id.className = 'mono';
    id.textContent = row.id || row.fact_id || '—';
    tr.append(statement, namespace, id);
    tbody.appendChild(tr);
  });
}

function renderKillCriteria(criteria) {
  const host = document.getElementById('killCriteria');
  clearElement(host);
  const verdict = String(criteria.verdict || 'inconclusive');
  const labels = { observed_ok: '基準内', observed_breached: '基準未達', inconclusive: 'データ不足' };
  const row = document.createElement('div');
  row.className = 'metrics-kill';
  const pill = document.createElement('span');
  const statusClass = verdict === 'observed_ok' ? 'active' : 'invalidated';
  pill.className = `status-pill ${statusClass}`;
  const dot = document.createElement('span');
  dot.className = 'dot';
  pill.append(dot, document.createTextNode(labels[verdict] || verdict));
  const threshold = document.createElement('span');
  threshold.textContent = `閾値: 週 ${numberOrNull(criteria.threshold_weekly_hits) ?? '—'} 回`;
  row.append(pill, threshold);
  host.appendChild(row);
  const weeks = Array.isArray(criteria.weeks) ? criteria.weeks : [];
  if (weeks.length) {
    const chart = document.createElement('div');
    chart.className = 'chart';
    chart.id = 'killWeeksChart';
    host.appendChild(chart);
    renderHorizontalBars('killWeeksChart', weeks, 'auto_strong_contribution_decisions', 'week', '完了週の観測がありません。');
  }
  const note = document.createElement('div');
  note.className = 'metrics-note';
  note.textContent = 'エージェントが最終判断時に申告した観測値です。因果効果の証明ではなく、未計測の検索は判定へ含めません。';
  host.appendChild(note);
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
  const pill = document.createElement('span');
  pill.className = `status-pill ${status === 'ready' ? 'active' : 'invalidated'}`;
  const dot = document.createElement('span');
  dot.className = 'dot';
  pill.append(dot, document.createTextNode(labels[status] || status));
  const count = document.createElement('span');
  count.textContent = `${numberOrNull(readiness.passed_gates) || 0} / ${numberOrNull(readiness.total_gates) || 0} ゲート達成`;
  statusHost.append(pill, count);

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
      [gate.label || gate.id || '—', gateLabels[gate.status] || gate.status || '—',
        gate.current || '—', gate.target || '—'].forEach((value, index) => {
        const td = document.createElement('td');
        td.textContent = String(value);
        if (index === 1) td.className = gate.status === 'pass' ? 'success-text' : 'danger-text';
        tr.appendChild(td);
      });
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
    [row.client || 'unknown', numberOrNull(row.measurable) || 0, numberOrNull(row.resolved) || 0,
      percent(row.measurement_rate), numberOrNull(row.strong) || 0].forEach((value, index) => {
      const td = document.createElement('td');
      td.textContent = String(value);
      if (index === 0) td.className = 'mono';
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
    [row.fact_id || '—', numberOrNull(row.returned_searches) || 0,
      numberOrNull(row.used_decisions) || 0, numberOrNull(row.strong_decisions) || 0].forEach((value, index) => {
      const td = document.createElement('td');
      td.textContent = String(value);
      if (index === 0) td.className = 'mono';
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderMetrics(data) {
  const search = data.search || {};
  const weekly = Array.isArray(search.weekly) ? search.weekly : [];
  const corpus = data.corpus || {};
  const contribution = data.contribution || {};
  renderDecisionValue(data.decision_value || {});
  renderOperationalReadiness(data.operational_readiness || {});
  renderWeeklySearch(weekly);
  renderReturnRate(weekly);
  renderEval(data.eval || {});
  renderHorizontalBars('namespaceChart', Array.isArray(corpus.namespaces) ? corpus.namespaces : [], 'count', 'namespace', corpus.available === false ? '現在の保存方式では、登録データの状態を集計できません。' : '有効なファクトがありません。');
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
