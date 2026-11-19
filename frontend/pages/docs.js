// Admin documentation: renders docs/manual.md with a contents list, in-page search and a download link.
import { ready, requireAdmin, refreshIcons, showFlash } from '../layout.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;

  const $ = id => document.getElementById(id);
  const toc = $('docs-toc');
  const body = $('docs-body');
  const status = $('docs-status');

  let source = '';
  try {
    const res = await fetch('/api/docs/manual.md', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    source = await res.text();
  } catch (err) {
    status.textContent = 'The manual could not be loaded.';
    showFlash(`Manual unavailable (${err.message}).`, 'error');
    return;
  }

  marked.setOptions({ gfm: true, breaks: false });
  const html = DOMPurify.sanitize(marked.parse(source));
  body.innerHTML = html;

  // Build the table of contents from h2 and h3 headings, and give each heading an id.
  const slug = (text, seen) => {
    let base = text.toLowerCase().replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-') || 'section';
    let id = base, n = 2;
    while (seen.has(id)) id = `${base}-${n++}`;
    seen.add(id);
    return id;
  };
  const seen = new Set();
  const items = [];
  body.querySelectorAll('h2, h3').forEach(h => {
    h.id = slug(h.textContent, seen);
    items.push({ id: h.id, text: h.textContent, level: h.tagName === 'H2' ? 2 : 3 });
  });

  const list = document.createElement('ul');
  items.forEach(item => {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = `#${item.id}`;
    a.textContent = item.text;
    a.className = item.level === 3 ? 'lvl-3' : '';
    li.append(a);
    list.append(li);
  });
  toc.replaceChildren(list);

  // Highlight the section in view.
  const links = new Map([...toc.querySelectorAll('a')].map(a => [a.getAttribute('href').slice(1), a]));
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      links.forEach(a => a.removeAttribute('aria-current'));
      const a = links.get(entry.target.id);
      if (a) { a.setAttribute('aria-current', 'true'); a.scrollIntoView({ block: 'nearest' }); }
    });
  }, { rootMargin: '0px 0px -70% 0px' });
  body.querySelectorAll('h2, h3').forEach(h => observer.observe(h));

  // Search: highlights matches in the body and hides contents entries without a match.
  const originalHtml = body.innerHTML;
  const search = $('docs-search');
  search.addEventListener('input', () => {
    const q = search.value.trim();
    body.innerHTML = originalHtml;
    if (!q) {
      status.textContent = '';
      links.forEach(a => { a.parentElement.hidden = false; });
      return;
    }
    const pattern = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    let hits = 0;
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);
    textNodes.forEach(node => {
      if (!pattern.test(node.nodeValue)) { pattern.lastIndex = 0; return; }
      pattern.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0, m;
      while ((m = pattern.exec(node.nodeValue))) {
        hits++;
        frag.append(node.nodeValue.slice(last, m.index));
        const mark = document.createElement('mark');
        mark.textContent = m[0];
        frag.append(mark);
        last = m.index + m[0].length;
      }
      frag.append(node.nodeValue.slice(last));
      node.replaceWith(frag);
    });
    body.querySelectorAll('h2, h3').forEach(h => { h.id = h.id; });
    status.textContent = hits ? `${hits} match${hits === 1 ? '' : 'es'}.` : 'No matches.';
    const first = body.querySelector('mark');
    if (first) first.scrollIntoView({ block: 'center' });
  });

  // Mobile contents toggle.
  $('toc-toggle').addEventListener('click', e => {
    const open = !toc.classList.contains('open');
    toc.classList.toggle('open', open);
    e.currentTarget.setAttribute('aria-expanded', String(open));
  });
  toc.addEventListener('click', () => {
    if (window.innerWidth < 900) { toc.classList.remove('open'); $('toc-toggle').setAttribute('aria-expanded', 'false'); }
  });

  status.textContent = '';
  refreshIcons();
})();