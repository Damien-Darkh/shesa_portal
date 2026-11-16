// richtext.js - rich-text editor for the profile text.
// Stores a safe subset of HTML. Pasted Markdown is converted automatically.

const ALLOWED = new Set(['P', 'H2', 'H3', 'H4', 'BLOCKQUOTE', 'STRONG', 'EM', 'U', 'S', 'CODE', 'UL', 'OL', 'LI', 'A', 'BR']);
const RENAME = { B: 'STRONG', I: 'EM', STRIKE: 'S', DEL: 'S', DIV: 'P', H1: 'H2', H5: 'H4', H6: 'H4' };

const escHtml = s => s
  .replace(/&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)/g, '&amp;')   // keeps entities like &copy; working
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');

function unwrap(node) {
  const parent = node.parentNode;
  while (node.firstChild) parent.insertBefore(node.firstChild, node);
  parent.removeChild(node);
}

/** Returns HTML containing only the allowed tags and http(s) links. */
export function sanitize(html) {
  const doc = new DOMParser().parseFromString(`<body>${html || ''}</body>`, 'text/html');
  const walk = parent => {
    [...parent.childNodes].forEach(child => {
      if (child.nodeType === Node.TEXT_NODE) return;
      if (child.nodeType !== Node.ELEMENT_NODE) { child.remove(); return; }
      walk(child);

      let node = child;
      if (RENAME[node.tagName]) {
        const repl = doc.createElement(RENAME[node.tagName]);
        while (node.firstChild) repl.appendChild(node.firstChild);
        node.replaceWith(repl);
        node = repl;
      }
      if (!ALLOWED.has(node.tagName)) { unwrap(node); return; }

      if (node.tagName === 'A') {
        const href = node.getAttribute('href') || '';
        if (!/^https?:\/\//i.test(href)) { unwrap(node); return; }
        [...node.attributes].forEach(a => node.removeAttribute(a.name));
        node.setAttribute('href', href);
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
      } else {
        [...node.attributes].forEach(a => node.removeAttribute(a.name));
      }
    });
  };
  walk(doc.body);
  return doc.body.innerHTML.trim();
}

/* ------------------------------------------------------------------ Markdown -> HTML (used on paste) */

function mdInline(src) {
  const codes = [];
  let s = src.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = escHtml(s);
  s = s.replace(/\\([\\`*_{}\[\]()#+\-.!~>|])/g, (_, c) => `&#${c.charCodeAt(0)};`);   // \* \# etc. stay literal
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/~~(.+?)~~/g, '<s>$1</s>')
    .replace(/&lt;(\/?)u&gt;/g, '<$1u>')
    .replace(/!?\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${escHtml(codes[i])}</code>`);
}

function listHtml(items) {
  let out = '';
  const stack = [];
  for (const it of items) {
    const tag = it.ordered ? 'ol' : 'ul';
    const lvl = Math.min(it.level, stack.length);
    while (stack.length > lvl + 1) out += `</li></${stack.pop()}>`;
    if (stack.length === lvl + 1) out += '</li>';
    else { out += `<${tag}>`; stack.push(tag); }
    out += `<li>${it.html}`;
  }
  while (stack.length) out += `</li></${stack.pop()}>`;
  return out;
}

export function mdToHtml(md) {
  const lines = md.replace(/\r\n?/g, '\n').split('\n');
  const out = [], para = [];
  const flush = () => { if (para.length) { out.push(`<p>${mdInline(para.join(' '))}</p>`); para.length = 0; } };
  const LI = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;
  let i = 0, m;

  while (i < lines.length) {
    const line = lines[i];

    if (/^```/.test(line)) {                                   // code block: one code line per paragraph
      flush(); i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        if (lines[i].trim()) out.push(`<p><code>${escHtml(lines[i])}</code></p>`);
        i++;
      }
      i++; continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); i++; continue; }   // dividers are not supported

    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {              // # -> title, ## -> heading, ### and deeper -> subheading
      flush();
      const tag = m[1].length === 1 ? 'h2' : m[1].length === 2 ? 'h3' : 'h4';
      out.push(`<${tag}>${mdInline(m[2].trim())}</${tag}>`);
      i++; continue;
    }

    if (/^\s*>/.test(line)) {
      flush();
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { q.push(lines[i].replace(/^(\s*>\s?)+/, '')); i++; }
      out.push(`<blockquote>${mdInline(q.join(' ').trim())}</blockquote>`);
      continue;
    }

    if (line.includes('|') && i + 1 < lines.length
        && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {   // table -> one paragraph per row
      flush();
      const rows = [line];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) { rows.push(lines[i]); i++; }
      rows.forEach((r, idx) => {
        const txt = r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim()).join(' | ');
        out.push(idx === 0 ? `<p><strong>${mdInline(txt)}</strong></p>` : `<p>${mdInline(txt)}</p>`);
      });
      continue;
    }

    if (LI.test(line)) {
      flush();
      const items = [];
      while (i < lines.length && (m = lines[i].match(LI))) {
        const text = m[3].replace(/^\[( |x|X)\]\s+/, (_, c) => (c === ' ' ? '☐ ' : '☑ '));   // task list
        items.push({ level: Math.floor(m[1].replace(/\t/g, '    ').length / 2), ordered: /\d/.test(m[2]), html: mdInline(text) });
        i++;
      }
      out.push(listHtml(items));
      continue;
    }

    para.push(line.trim());
    i++;
  }
  flush();
  return out.join('');
}

const looksLikeMarkdown = t =>
  /^(#{1,6}\s|\s*[-*+]\s|\s*\d+\.\s|\s*>|```)|\*\*[^*]+\*\*|~~[^~]+~~|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)]+\)/m.test(t);

// Text saved by the old plain-text field has no tags: turn blank-line groups into paragraphs.
const asHtml = html => /<\/?[a-z][^>]*>/i.test(html)
  ? html
  : html.split(/\n\s*\n/).filter(p => p.trim()).map(p => `<p>${escHtml(p.trim()).replace(/\n/g, '<br>')}</p>`).join('');

/* ------------------------------------------------------------------ editor */

export function createEditor(root, toolbar, { askUrl } = {}) {
  if (!root || !toolbar) throw new Error('Editor elements are missing from the page.');
  root.contentEditable = 'true';
  root.setAttribute('role', 'textbox');
  root.setAttribute('aria-multiline', 'true');
  try { document.execCommand('defaultParagraphSeparator', false, 'p'); } catch { /* not supported */ }

  // Keep the selection in the text when a toolbar button is pressed.
  toolbar.addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });

  const BLOCKS = new Set(['h2', 'h3', 'h4', 'p', 'blockquote']);

  toolbar.addEventListener('click', async e => {
    const btn = e.target.closest('button[data-cmd]');
    if (!btn) return;
    const cmd = btn.dataset.cmd;

    if (cmd === 'link') {
      const sel = window.getSelection();
      const range = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
      let url = askUrl ? await askUrl() : null;
      root.focus();
      if (range) { sel.removeAllRanges(); sel.addRange(range); }
      if (url) {
        url = url.trim();
        if (/^[a-z][a-z0-9+.-]*:/i.test(url) && !/^https?:/i.test(url)) url = '';   // blocks javascript: etc.
        else if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
        if (url) document.execCommand('createLink', false, url);
      }
    } else if (cmd === 'code') {
      root.focus();
      const text = window.getSelection().toString();
      if (text) document.execCommand('insertHTML', false, `<code>${escHtml(text)}</code>`);
    } else if (BLOCKS.has(cmd)) {
      root.focus();
      document.execCommand('formatBlock', false, `<${cmd}>`);
    } else {
      root.focus();
      document.execCommand(cmd);
    }
    root.dispatchEvent(new Event('input'));
  });

  root.addEventListener('paste', e => {
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain');
    if (looksLikeMarkdown(text)) document.execCommand('insertHTML', false, sanitize(mdToHtml(text)));
    else document.execCommand('insertText', false, text);
    root.dispatchEvent(new Event('input'));
  });

  return {
    getHTML: () => (root.textContent.trim() ? sanitize(root.innerHTML) : ''),
    setHTML: html => { root.innerHTML = sanitize(asHtml(html || '')); },
  };
}