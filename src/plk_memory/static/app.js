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

const state = { ns: '', kind: '', status: 'active', q: '', sortDir: 'desc' };
let currentFacts = [];

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function nsColorVar(ns) { return (NS_META[ns] && NS_META[ns].var) ? `var(${NS_META[ns].var})` : 'var(--text-faint)'; }
function nsLabel(ns) { return (NS_META[ns] && NS_META[ns].label) || ns || '—'; }

async function login() {
  const errEl = document.getElementById('loginErr');
  errEl.textContent = '';
  const r = await fetch('/ui/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password: document.getElementById('pw').value }),
  });
  if (r.ok) {
    enterMain();
    load();
  } else {
    errEl.textContent = '認証に失敗しました。パスワードを確認してください。';
  }
}

function enterMain() {
  document.getElementById('login').style.display = 'none';
  document.getElementById('main').style.display = 'block';
}

function initNsBar() {
  const bar = document.getElementById('nsBar');
  bar.innerHTML = '';
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
  tbody.innerHTML = '';
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
  const meta = data.meta || {};
  const el = document.getElementById('detail');
  el.innerHTML = '';

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

  openDetailPanel();
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
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.getElementById('detail').classList.contains('open')) closeDetailPanel();
  });

  // 既存の HttpOnly cookie セッションが有効なら、ログイン画面を出さず一覧を直接表示する
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
