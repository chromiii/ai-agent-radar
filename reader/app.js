'use strict';

const byId = (id) => document.getElementById(id);
const { asOf, events, graph } = JSON.parse(byId('feed-data').textContent);
const storageKey = 'ai-agent-radar-reader-v1';
const stored = loadState();
const saved = new Map(Object.entries(stored.saved ?? {}));
const read = new Set(stored.read ?? []);
const current = new Map(events.map((row) => [row.id, row]));
for (const theme of graph.topics) {
  for (const child of theme.children) {
    for (const row of child.content) {
      const known = current.get(row.id);
      if (known) {
        const firstSeen = known.first_seen < row.first_seen ? known.first_seen : row.first_seen;
        const published = known.published ?? row.published;
        current.set(row.id, { ...known, first_seen: firstSeen, published, date: published ?? firstSeen,
          summary: known.summary || row.summary, urls: [...new Set([...known.urls, ...row.urls])] });
      } else {
        current.set(row.id, row);
      }
    }
  }
}

const board = byId('graph-board');
const results = byId('results');
const period = byId('period');
const onlyUnread = byId('unread');
let mode = 'graph';
let themeIndex = 0;
let childIndex = 0;

function loadState() {
  try {
    const state = JSON.parse(localStorage.getItem(storageKey));
    return state && typeof state === 'object' ? state : {};
  } catch {
    byId('storage-error').hidden = false;
    return {};
  }
}

function saveState() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({ ...stored, saved: Object.fromEntries(saved), read: [...read] }));
  } catch {
    byId('storage-error').hidden = false;
  }
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function buttonFor(text, pressed, id, onClick) {
  const node = element('button', text);
  node.id = id;
  node.type = 'button';
  if (pressed !== null) node.setAttribute('aria-pressed', pressed);
  node.addEventListener('click', onClick);
  return node;
}

function cardFor(row, location) {
  const card = element('article', '', 'card');
  const published = row.published ? `发布 ${row.published}` : '发布日期未标注';
  card.append(element('p', `${published} · 收录 ${row.first_seen}`, 'meta'), element('h3', row.title));
  if (row.summary) card.append(element('p', row.summary, 'excerpt'));
  const sources = element('div', '', 'sources');
  for (const url of row.urls) {
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol)) continue;
    const link = element('a', parsed.hostname);
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.title = parsed.href;
    sources.append(link);
  }
  const actions = element('div', '', 'actions');
  actions.append(
    buttonFor(saved.has(row.id) ? '已收藏' : '收藏', saved.has(row.id), `${location}-save-${row.id}`, () => {
      if (saved.has(row.id)) saved.delete(row.id);
      else saved.set(row.id, row);
      saveState();
      render();
    }),
    buttonFor(read.has(row.id) ? '标为未读' : '标为已读', null, `${location}-read-${row.id}`, () => {
      if (read.has(row.id)) read.delete(row.id);
      else read.add(row.id);
      saveState();
      render();
    }),
  );
  const footer = element('footer');
  footer.append(sources, actions);
  card.append(footer);
  return card;
}

function drawEdges() {
  const layer = byId('edges');
  const boardRect = board.getBoundingClientRect();
  layer.replaceChildren();
  if (!boardRect.width || layer.clientWidth === 0) return;
  const bounds = layer.getBoundingClientRect();
  function connect(from, targets, active) {
    const start = from.getBoundingClientRect();
    const x1 = start.right - bounds.left;
    const y1 = start.top + start.height / 2 - bounds.top;
    for (const target of targets) {
      const end = target.getBoundingClientRect();
      const x2 = end.left - bounds.left;
      const y2 = end.top + end.height / 2 - bounds.top;
      const center = (x1 + x2) / 2;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', `M ${x1} ${y1} C ${center} ${y1}, ${center} ${y2}, ${x2} ${y2}`);
      if (target === active || target.matches('article')) path.classList.add('active-edge');
      layer.append(path);
    }
  }

  const theme = byId(`theme-${themeIndex}`);
  const subtopic = byId(`subtopic-${childIndex}`);
  if (!theme || !subtopic) return;
  connect(theme, byId('subtopics').children, subtopic);
  connect(subtopic, byId('evidence').children);
}

function renderGraph() {
  board.hidden = !graph.topics.length;
  const status = byId('graph-status');
  if (!graph.topics.length) {
    status.textContent = '这份快照暂无可用的主题图谱。日报资料仍可在「全部内容」浏览。';
    return;
  }
  status.textContent = graph.method === 'ai'
    ? `AI 发现于 ${graph.generated_at} · 每周更新`
    : `用 ${graph.generated_at} 的 AI 趋势与学习卡生成 · 每周更新`;
  const theme = graph.topics[themeIndex];
  const child = theme.children[childIndex];
  const themeButtons = graph.topics.map((row, index) => buttonFor(
    row.label, index === themeIndex, `theme-${index}`, () => {
      themeIndex = index;
      childIndex = 0;
      render();
    },
  ));
  const childButtons = theme.children.map((row, index) => buttonFor(
    row.label, index === childIndex, `subtopic-${index}`, () => {
      childIndex = index;
      render();
    },
  ));
  for (const button of [...themeButtons, ...childButtons]) button.classList.add('node');
  byId('themes').replaceChildren(...themeButtons);
  byId('subtopics').replaceChildren(...childButtons);
  byId('evidence').replaceChildren(...child.content.map((row) => cardFor(current.get(row.id), 'graph')));
  requestAnimationFrame(drawEdges);
}

function renderArchive() {
  const days = Number(period.value);
  const cutoff = new Date(`${asOf}T00:00:00Z`);
  cutoff.setUTCDate(cutoff.getUTCDate() - Math.max(days - 1, 0));
  const earliest = days ? cutoff.toISOString().slice(0, 10) : '';
  const visible = mode === 'saved'
    ? [...saved.values()].map((row) => current.get(row.id) ?? row)
    : [...current.values()];
  const cards = visible.sort((a, b) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title))
    .filter((row) => row.date >= earliest && row.date <= asOf && (!onlyUnread.checked || !read.has(row.id)))
    .map((row) => cardFor(row, 'archive'));
  results.replaceChildren(...cards);
  byId('results-status').textContent = cards.length ? `${cards.length} 条` : '当前筛选没有条目。';
}

function render() {
  const active = document.activeElement.id;
  byId('topic-graph').hidden = mode !== 'graph';
  byId('archive').hidden = mode === 'graph';
  if (mode === 'graph') renderGraph();
  else renderArchive();
  if (active) (byId(active) ?? byId('results-status')).focus();
}

byId('snapshot').textContent = `内容快照 ${asOf}`;
for (const button of document.querySelectorAll('[data-mode]')) {
  button.addEventListener('click', () => {
    mode = button.dataset.mode;
    for (const tab of document.querySelectorAll('[data-mode]')) tab.setAttribute('aria-pressed', tab === button);
    if (mode === 'saved') {
      period.value = '0';
      onlyUnread.checked = false;
    }
    render();
  });
}
period.addEventListener('change', render);
onlyUnread.addEventListener('change', render);
new ResizeObserver(drawEdges).observe(board);
render();
