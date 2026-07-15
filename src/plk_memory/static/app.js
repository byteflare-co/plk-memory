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

function makeChart(host, label, width = 760, height = 210) {
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
      x: left - 8, y: y + 4, fill: 'var(--text-faint)', 'font-size': 10, 'text-anchor': 'end',
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
  const left = 42; const top = 12; const width = 700; const height = 158;
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
    autoTitle.textContent = `${String(row.week || '')}: auto ${auto}`;
    autoRect.appendChild(autoTitle);
    svg.appendChild(autoRect);
    const manualRect = svgElement('rect', { x, y: top + height - autoHeight - manualHeight, width: barWidth, height: manualHeight, rx: 2, fill: CHART_COLORS[2] });
    const manualTitle = svgElement('title');
    manualTitle.textContent = `${String(row.week || '')}: manual ${manual}`;
    manualRect.appendChild(manualTitle);
    svg.appendChild(manualRect);
    svgText(svg, compactWeek(row.week) + (row.in_progress ? '*' : ''), {
      x: x + barWidth / 2, y: 190, fill: 'var(--text-faint)', 'font-size': 9, 'text-anchor': 'middle',
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
    title.textContent = `${String(row.week || '')}: failures ${failures}`;
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
    { label: 'auto', color: CHART_COLORS[0] },
    { label: 'manual', color: CHART_COLORS[2] },
    { label: 'failures', color: CHART_COLORS[6] },
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
  const svg = makeChart(host, '週別結果返却率の折れ線グラフ', 600, 210);
  const left = 42; const top = 12; const width = 540; const height = 158;
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
      x, y: 190, fill: 'var(--text-faint)', 'font-size': 9, 'text-anchor': 'middle',
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
  const height = Math.max(210, shown.length * 28 + 24);
  const svg = makeChart(host, `${hostId} 横棒グラフ`, 600, height);
  svg.style.height = `${height}px`;
  const left = 150; const width = 410;
  const maxValue = Math.max(1, ...shown.map(row => numberOrNull(row[valueKey]) || 0));
  shown.forEach((row, index) => {
    const value = Math.max(0, numberOrNull(row[valueKey]) || 0);
    const y = 12 + index * 28;
    svgText(svg, row[labelKey] || '—', { x: left - 9, y: y + 14, fill: 'var(--text-muted)', 'font-size': 10.5, 'text-anchor': 'end' });
    svg.appendChild(svgElement('rect', { x: left, y, width: width * value / maxValue, height: 18, rx: 3, fill: CHART_COLORS[index % CHART_COLORS.length] }));
    svgText(svg, value, { x: left + width * value / maxValue + 6, y: y + 14, fill: 'var(--text)', 'font-size': 10.5 });
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
  const svg = makeChart(host, '検索品質 hit at 5 と MRR の折れ線グラフ', 600, 210);
  const left = 42; const top = 12; const width = 540; const height = 158;
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
        title.textContent = `${item.runner} / ${item.hash} / ${field}: ${percent(value)}`;
        circle.appendChild(title);
        svg.appendChild(circle);
      });
      if (path) {
        const attrs = { d: path, fill: 'none', stroke: baseColor, 'stroke-width': dashed ? 1.5 : 2.4 };
        if (dashed) attrs['stroke-dasharray'] = '5 4';
        svg.insertBefore(svgElement('path', attrs), svg.querySelector('circle'));
      }
      legend.push({ label: `${item.runner} · ${item.hash} · ${field === 'hit5_rate' ? 'hit@5' : 'MRR'}`, color: baseColor });
    });
  });
  const labels = timestamps.length > 5 ? timestamps.filter((_, index) => index % Math.ceil(timestamps.length / 5) === 0) : timestamps;
  labels.forEach(ts => svgText(svg, formatDate(ts), { x: xFor(ts), y: 190, fill: 'var(--text-faint)', 'font-size': 9, 'text-anchor': 'middle' }));
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

function last7dReturnRate(search) {
  const direct = numberOrNull(search.last7d_return_rate);
  if (direct !== null) return direct;
  const bucket = search.last7d || {};
  const bucketRate = numberOrNull(bucket.return_rate);
  if (bucketRate !== null) return bucketRate;
  const okTotal = numberOrNull(bucket.ok_total);
  return okTotal > 0 ? Number(bucket.returned || 0) / okTotal : null;
}

function renderStats(data) {
  const host = document.getElementById('metricsStats');
  clearElement(host);
  const search = data.search || {};
  const clients = Array.isArray(search.clients) ? search.clients : [];
  const weekly = Array.isArray(search.weekly) ? search.weekly : [];
  const total = numberOrNull(search.total) ?? clients.reduce((sum, row) => sum + (numberOrNull(row.count) || 0), 0);
  const failures = weekly.reduce((sum, row) => sum + (numberOrNull(row.failures) || 0), 0);
  const latency = search.latency || {};
  const last7dLatency = latency.last7d || {};
  addStatTile(host, '総検索数', String(total), `直近 12 週の障害 ${failures} 件`);
  addStatTile(host, '直近 7 日結果返却率', percent(last7dReturnRate(search)), `latency p50 ${numberOrNull(last7dLatency.p50) ?? '—'} ms`);
  const corpus = data.corpus || {};
  const active = corpus.available === false ? '—' : String(numberOrNull((corpus.status || {}).active) ?? 0);
  addStatTile(host, 'active ファクト', active, corpus.available === false ? 'backend 未対応' : `読み込み skip ${numberOrNull(corpus.skipped_files) || 0} 件`);
  const verdict = String((data.kill_criteria || {}).verdict || 'inconclusive');
  const verdictMeta = {
    proxy_ok: ['proxy OK', 'ok'], proxy_breached: ['proxy breached', 'bad'], inconclusive: ['判定不能', 'warn'],
  }[verdict] || [verdict, 'warn'];
  addStatTile(host, 'キル基準 proxy', verdictMeta[0], '正式判定は Phase 2 以降', verdictMeta[1]);
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
    emptyTableRow(tbody, 4, 'ゼロヒットクエリはありません。');
    return;
  }
  rows.forEach(row => {
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
    emptyTableRow(tbody, 3, 'この backend ではコーパス指標を利用できません。');
    return;
  }
  const rows = Array.isArray(unreturned.items) ? unreturned.items : [];
  if (!rows.length) {
    emptyTableRow(tbody, 3, '未返却の active ファクトはありません。');
    return;
  }
  rows.forEach(row => {
    const tr = document.createElement('tr');
    const statement = document.createElement('td');
    statement.textContent = row.statement || '（statement なし）';
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
  const labels = { proxy_ok: 'proxy OK', proxy_breached: 'proxy breached', inconclusive: '判定不能' };
  const row = document.createElement('div');
  row.className = 'metrics-kill';
  const pill = document.createElement('span');
  const statusClass = verdict === 'proxy_ok' ? 'active' : 'invalidated';
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
    renderHorizontalBars('killWeeksChart', weeks, 'auto_returned_searches', 'week', '完了週の観測がありません。');
  }
  const note = document.createElement('div');
  note.className = 'metrics-note';
  note.textContent = '正式判定は Phase 2（引用計測）以降です。保守時間は本ダッシュボードの対象外です。';
  host.appendChild(note);
}

function renderMetrics(data) {
  const search = data.search || {};
  const weekly = Array.isArray(search.weekly) ? search.weekly : [];
  const corpus = data.corpus || {};
  renderStats(data);
  renderWeeklySearch(weekly);
  renderReturnRate(weekly);
  renderEval(data.eval || {});
  renderHorizontalBars('namespaceChart', Array.isArray(corpus.namespaces) ? corpus.namespaces : [], 'count', 'namespace', corpus.available === false ? 'この backend ではコーパス指標を利用できません。' : 'active ファクトがありません。');
  renderHorizontalBars('clientChart', Array.isArray(search.clients) ? search.clients : [], 'count', 'client', '検索ログがありません。');
  renderKillCriteria(data.kill_criteria || {});
  renderZeroHits(Array.isArray(data.zero_hit) ? data.zero_hit : []);
  renderUnreturned(corpus.unreturned || {}, corpus.available);
  const generated = document.getElementById('metricsStatus');
  generated.className = 'metrics-status';
  generated.textContent = data.generated_at ? `集計日時: ${formatDateTime(data.generated_at)}` : '集計完了';
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
    status.textContent = `メトリクスを取得できませんでした: ${error.message}`;
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
