// layout.js - shared header, navigation and dialogs for every page. Data comes from the Django API (store.js).
// Pages do:   import { ready, ... } from './layout.js';   ready.then(ok => { if (!ok) return; ...page... });
import { api } from './api.js';
import { dbData, loadSession, refreshDepartments, refreshLeave, refreshBalances, refreshNotifications } from './store.js';
import { t, getLang, setLang, fmtDate, applyTranslations } from './i18n.js';
export { t, getLang, setLang, fmtDate, dbData };

// ---------------------------------------------------------- notifications --
export const getUnreadCount = () => (dbData.notifications || []).filter(n => !n.is_read).length;

export function updateNotificationBadge() {
  const c = getUnreadCount();
  const badge = document.querySelector('.nav-bell .badge');
  if (badge) { badge.textContent = String(c); badge.hidden = !c; }
  const bell = document.querySelector('.nav-bell');
  if (bell) { bell.hidden = !c; bell.setAttribute('aria-label', `Notifications, ${c} unread`); }
}

/** Marks notifications read (all, or the given ids). POST /api/notifications/read-all or /<id>/read. */
export async function markNotificationsRead(ids = null) {
  const targets = (dbData.notifications || []).filter(n => !n.is_read && (!ids || ids.includes(n.id)));
  if (!targets.length) return;
  if (!ids) await api('/api/notifications/read-all', { method: 'POST' });
  else await Promise.all(targets.map(n => api(`/api/notifications/${n.id}/read`, { method: 'POST' })));
  targets.forEach(n => { n.is_read = true; });
  updateNotificationBadge();
}

// ---------------------------------------------------------- leave --
/** Requests the current admin can act on (their own need another admin). */
export const getPendingLeaveCount = () =>
  (dbData.leaveRequests || []).filter(r => r.status === 'PENDING' && r.user_id !== dbData.currentUser?.id).length;

/** Refreshes every .js-leave-badge and the Admin Panel link label. */
export function updateLeaveBadge() {
  const c = getPendingLeaveCount();
  document.querySelectorAll('.js-leave-badge').forEach(b => { b.textContent = String(c); b.hidden = !c; });
  document.querySelectorAll('[data-nav="admin"]').forEach(a => {
    const label = c ? `Admin Panel, ${c} pending leave request${c > 1 ? 's' : ''}` : 'Admin Panel';
    a.setAttribute('aria-label', label); a.title = c ? `${c} pending leave request${c > 1 ? 's' : ''}` : '';
  });
}

/** Employee: files a leave request. POST /api/pto/requests/create. Throws ApiError on rule violations. */
export async function submitLeave({ leave_type, start_date, end_date, days_requested, reason = '' }) {
  const r = await api('/api/pto/requests/create', { method: 'POST', body: { leave_type, start_date, end_date, days_requested, reason } });
  await Promise.all([refreshLeave(), refreshBalances()]);
  updateLeaveBadge();
  return r;
}

/** Employee: withdraws a pending request. POST /api/pto/requests/<id>/cancel. */
export async function cancelLeave(id) {
  await api(`/api/pto/requests/${id}/cancel`, { method: 'POST' });
  await Promise.all([refreshLeave(), refreshBalances()]);
  updateLeaveBadge();
}

/** Admin: approves ('APPROVED') or denies ('DENIED') a request. POST /api/pto/requests/<id>/approve|reject. */
export async function decideLeave(id, status, comment = null) {
  const action = status === 'APPROVED' ? 'approve' : 'reject';
  await api(`/api/pto/requests/${id}/${action}`, { method: 'POST', body: { comment: comment || '' } });
  await Promise.all([refreshLeave(), refreshBalances()]);
  updateLeaveBadge();
}

// ---------------------------------------------------------- departments --
/** Ids of every department below `id` (a department can't be moved under itself). */
export function descendantIds(id) {
  const out = new Set();
  const walk = p => dbData.departments.filter(d => d.parent_id === p).forEach(d => { if (!out.has(d.id)) { out.add(d.id); walk(d.id); } });
  walk(id);
  return out;
}

/** Employees and sub-departments that still depend on a department (what the server checks too). */
export function departmentUsage(id) {
  return { members: (dbData.usersDirectory || []).filter(u => u.profile?.department_id === id).length,
           children: dbData.departments.filter(d => d.parent_id === id).length };
}

export async function createDepartment(fields) {
  const d = await api('/api/departments/create', { method: 'POST', body: fields });
  await refreshDepartments();
  return d;
}

export async function updateDepartment(id, fields) {
  const d = await api(`/api/departments/${id}/`, { method: 'PATCH', body: fields });
  await refreshDepartments();
  return d;
}

export async function deleteDepartment(id) {
  await api(`/api/departments/${id}/`, { method: 'DELETE' });
  await refreshDepartments();
}

/** Add / edit department pop-up. Resolves with the saved department, or null. Server errors are shown inline. */
export function departmentDialog(id = null) {
  return new Promise(resolve => {
    const cur = dbData.departments.find(d => d.id === id) || null, uid = `dd${++dialogSeq}`, prev = document.activeElement;
    const banned = cur ? new Set([cur.id, ...descendantIds(cur.id)]) : new Set();   // can't move a department under itself
    const input = (key, max) => el('input', { type: 'text', class: 'form-input', id: `${uid}-${key}`, maxlength: String(max) });
    const select = (key, first, items, value) => {
      const s = el('select', { class: 'form-input', id: `${uid}-${key}` });
      s.add(new Option(first, '')); items.forEach(([v, l]) => s.add(new Option(l, v))); s.value = value ? String(value) : '';
      return s;
    };
    const group = (label, control, star) => el('div', { class: 'form-group' }, [
      el('label', { class: 'form-label', for: control.id, text: label }, star ? [el('span', { text: ' *', 'aria-hidden': 'true', style: 'color:#b91c1c' })] : []), control]);
    const name = input('n', 80), desc = input('d', 200);
    name.value = cur ? cur.name : ''; desc.value = cur ? cur.description || '' : '';
    const parent = select('p', 'None (top level)', dbData.departments.filter(d => !banned.has(d.id)).map(d => [d.id, d.name]), cur?.parent_id);
    const tree = cur ? new Set([cur.id, ...descendantIds(cur.id)]) : new Set();   // only people inside this department can manage it
    const candidates = (dbData.usersDirectory || []).filter(u => tree.has(u.profile?.department_id) && (!u.disabled || (cur && u.id === cur.manager_id)));
    const manager = select('m', 'No manager', candidates.map(u => [u.id, fullName(u)]), cur?.manager_id);
    const error = el('p', { class: 'error-text', role: 'alert' }); error.hidden = true;
    const form = el('form', { class: 'space-y', novalidate: '' }, [group('Name', name, true), group('Description', desc), group('Parent department', parent), group('Manager', manager),
      el('p', { class: 'form-hint', text: candidates.length ? 'The manager must be a member of this department or one of its sub-departments.' : 'No employees yet: add employees to this department, then pick a manager.' }), error]);
    form.style.marginTop = '1.25rem';
    const cancel = el('button', { type: 'button', class: 'btn btn-outline', text: 'Cancel' });
    const submit = el('button', { type: 'submit', class: 'btn btn-primary', text: cur ? 'Save changes' : 'Add department' });
    submit.style.marginTop = '0';
    form.append(el('div', { class: 'modal-actions' }, [cancel, submit]));
    const overlay = el('div', { class: 'modal-overlay', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': `${uid}-t` }, [
      el('div', { class: 'modal-card', style: 'max-width:32rem;' }, [el('h3', { class: 'modal-title', id: `${uid}-t`, text: cur ? 'Edit department' : 'Add department' }), form])]);
    const finish = v => { overlay.remove(); document.body.style.overflow = ''; if (prev && prev.isConnected && prev.focus) prev.focus(); resolve(v); };
    cancel.addEventListener('click', () => finish(null));
    overlay.addEventListener('click', e => { if (e.target === overlay) finish(null); });
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); finish(null); } else trapFocus(overlay, e); });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const nm = name.value.trim();
      if (!nm) { error.textContent = t('Enter a department name.'); error.hidden = false; name.focus(); return; }
      const f = { name: nm, description: desc.value.trim(), parent_id: Number(parent.value) || null };
      if (cur) f.manager_id = Number(manager.value) || null;
      submit.disabled = true;
      try {
        const saved = cur ? await updateDepartment(id, f) : await createDepartment(f);
        showFlash(`Department "${nm}" ${cur ? 'updated' : 'added'}.`, 'success');
        finish(saved);
      } catch (err) {
        error.textContent = t(err.message); error.hidden = false; submit.disabled = false;
        (err.message.toLowerCase().includes('name') ? name : parent).focus();
      }
    });
    document.body.append(overlay); document.body.style.overflow = 'hidden'; name.focus();
  });
}

/** Delete flow: checks locally first, then asks, then calls the API. Resolves true if deleted. */
export async function deleteDepartmentFlow(id) {
  const d = dbData.departments.find(x => x.id === id);
  if (!d) return false;
  const use = departmentUsage(id);
  if (use.members || use.children) {
    await alertDialog({ title: "Can't delete this department",
      message: use.members ? `Move its ${use.members} employee${use.members > 1 ? 's' : ''} to another department first.` : 'Move or delete its sub-departments first.' });
    return false;
  }
  if (!await confirmDialog({ title: 'Delete department?', message: `Delete "${d.name}"? This can't be undone.`, confirmText: 'Delete', danger: true })) return false;
  try { await deleteDepartment(id); } catch (err) { await alertDialog({ title: "Can't delete this department", message: err.message }); return false; }
  showFlash(`Department "${d.name}" deleted.`, 'success');
  return true;
}

// ------------------------------------------------------------------ boot --
/**
 * Loads the session once and renders the shell. Resolves true when the page may continue, false when the
 * session is missing (the API helper has already sent the browser to /login or the password change page).
 */
export const ready = loadSession()
  .then(() => { initLayout(); return true; })
  .catch(err => { console.error(err); return false; });

// ------------------------------------------------------------------ config --

const LOGO_SRC = './logo_full.svg';
const LOGOUT_HREF = '/logout';

// filename -> which nav item is highlighted
const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', href: 'index.html',     icon: 'layout-dashboard' },
  { key: 'directory', label: 'Directory', href: 'directory.html', icon: 'users' },
  // Leave — disabled for now. Re-enable together with the Leave sections in index.html:
  // { key: 'calendar',  label: 'Calendar',  href: 'calander.html',  icon: 'calendar-days' },
  // Departments — disabled for now. Also uncomment the departments.html entry in PAGE_TO_NAV:
  // { key: 'departments', label: 'Departments', href: 'departments.html', icon: 'building-2' },
  { key: 'profile',   label: 'Profile',   href: 'profile.html',   icon: 'user' },
];
const ADMIN_ITEM = { key: 'admin', label: 'Admin Panel', href: 'admin.html', icon: 'shield' };

const PAGE_TO_NAV = {
  'index.html': 'dashboard',
  'add_device.html': 'dashboard',
  'device_created.html': 'dashboard',
  'directory.html': 'directory',
  // 'calander.html': 'calendar',
  // 'departments.html': 'departments',
  'profile.html': 'profile',
  'change_dsm_password.html': 'profile',
  'admin.html': 'admin',
  'add_user.html': 'admin',
  'edit_user.html': 'admin',
  'admin_user_created.html': 'admin',
};

/** Reads an image file as a data URL (stored as the profile photo). Size is limited to keep rows small. */
export function readImageFile(file, maxKB = 300) {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) return reject(new Error('Only image files are allowed.'));
    if (file.size > maxKB * 1024) return reject(new Error(`Image too large (max ${maxKB} KB).`));
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error('Could not read the image.'));
    r.readAsDataURL(file);
  });
}

/** Fills a <select> with the departments (used by add/edit employee). */
export function fillDepartmentSelect(sel, selectedId = null) {
  sel.replaceChildren(new Option(t('Select a department'), ''));
  dbData.departments.forEach(d => sel.add(new Option(d.name, d.id)));
  if (selectedId != null) sel.value = String(selectedId);
}

/** Keeps Tab inside a modal. Call from the modal's keydown handler. */
export function trapFocus(container, e) {
  if (e.key !== 'Tab') return;
  const f = [...container.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
    .filter(x => x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/** HTML-escape a value. Only needed where you still build strings for innerHTML. */
export const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function initials(first = '', last = '') {
  return ((first[0] || '') + (last[0] || '')).toUpperCase() || '--';
}

/** Fills an .avatar-box with a photo, falling back to initials. No innerHTML. */
export function renderAvatar(box, { photoUrl, firstName = '', lastName = '' }) {
  if (!box) return;
  const showInitials = () => {
    const span = document.createElement('span');
    span.textContent = initials(firstName, lastName);
    box.replaceChildren(span);
  };

  if (!photoUrl) return showInitials();

  const img = document.createElement('img');
  img.alt = `${firstName} ${lastName}`.trim();
  img.addEventListener('error', showInitials, { once: true });
  img.src = photoUrl; // set after the listener is attached
  box.replaceChildren(img);
}

/** Reads ?id=123 as an integer, or null. */
export function getIdParam(name = 'id') {
  const n = parseInt(new URLSearchParams(window.location.search).get(name), 10);
  return Number.isNaN(n) ? null : n;
}

export function getUserById(id) {
  return (dbData.usersDirectory || []).find(u => u.id === id) || null;
}

export function fullName(u) {
  return [u?.first_name, u?.last_name].filter(Boolean).join(' ') || u?.email || '';
}

/** Redirects non-admins away. Returns true if the page may continue. */
export function requireAdmin(redirectTo = 'index.html') {
  if (!dbData.currentUser || !dbData.currentUser.is_admin) {
    window.location.replace(redirectTo);
    return false;
  }
  return true;
}

/** Refreshes Lucide icons after any DOM change that adds <i data-lucide>. */
export function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

/**
 * Flash message, same look as base.html's .flash block.
 * category: 'success' | 'error'
 */
export function showFlash(message, category = 'success', { timeout = 5000 } = {}) {
  let host = document.getElementById('flash-host');
  if (!host) {
    host = document.createElement('div');
    host.id = 'flash-host';
    const main = document.querySelector('main') || document.body;
    main.prepend(host);
  }

  const box = document.createElement('div');
  const cat = ['error', 'warning', 'info'].includes(category) ? category : 'success';
  box.className = `flash flash-${cat}`;
  box.setAttribute('role', cat === 'error' || cat === 'warning' ? 'alert' : 'status');

  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', ({ error: 'triangle-alert', warning: 'triangle-alert', info: 'info' }[cat] || 'check'));
  const text = document.createElement('span');
  text.textContent = message;

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'flash-close';
  close.setAttribute('aria-label', 'Dismiss');
  close.textContent = '\u00d7';
  close.addEventListener('click', () => box.remove());

  box.append(icon, text, close);
  host.appendChild(box);
  refreshIcons();

  if (timeout) setTimeout(() => box.remove(), timeout);
  return box;
}

// ------------------------------------------------------------------ header --

function currentPage() {
  const file = window.location.pathname.split('/').pop() || 'index.html';
  return file.toLowerCase();
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.append(c);
  return node;
}

function navLink(item, activeKey) {
  const a = el('a', { href: item.href, 'data-nav': item.key, class: 'nav-link' + (item.key === activeKey ? ' active' : '') });
  if (item.key === activeKey) a.setAttribute('aria-current', 'page');
  a.append(el('i', { 'data-lucide': item.icon }), el('span', { text: item.label }));
  if (item.key === 'admin') { const b = el('span', { class: 'badge js-leave-badge' }); b.hidden = true; a.append(b); }
  return a;
}

function buildHeader() {
  const user = dbData.currentUser;
  const activeKey = PAGE_TO_NAV[currentPage()] || null;

  const items = [...NAV_ITEMS];
  if (user && user.is_admin) items.push(ADMIN_ITEM);

  // Brand
  const logo = el('img', { src: LOGO_SRC, alt: 'Company Logo' });
  const brand = el('div', { class: 'header-brand' },
    el('a', { class: 'brand-logo-img', href: 'index.html' }, logo));

  // Nav
  const nav = el('nav', { id: 'nav-links', 'aria-label': 'Main' });
  items.forEach(item => nav.append(navLink(item, activeKey)));

  if (user) {
    const unread = (dbData.notifications || []).filter(n => !n.is_read).length;
    const bell = el('a', { href: 'index.html#notifications', class: 'nav-link nav-bell', 'aria-label': `Notifications, ${unread} unread` });
    bell.append(el('i', { 'data-lucide': 'bell' }), el('span', { class: 'nav-bell-label', text: 'Notifications' }));
    const bellBadge = el('span', { class: 'badge', text: String(unread) });
    bellBadge.hidden = !unread;
    bell.append(bellBadge);
    bell.hidden = !unread;
    nav.append(bell);
    nav.append(el('span', { class: 'nav-user', text: user.email }));
    const logout = el('a', { href: LOGOUT_HREF, class: 'nav-link nav-logout' });
    logout.append(el('i', { 'data-lucide': 'log-out' }), el('span', { text: 'Log out' }));
    nav.append(logout);
  }

  // Hamburger (visible on small screens via injected CSS)
  const toggle = el('button', {
    type: 'button',
    class: 'nav-toggle',
    'aria-label': 'Toggle navigation',
    'aria-expanded': 'false',
    'aria-controls': 'nav-links',
  }, el('i', { 'data-lucide': 'menu' }));

  const container = el('div', { class: 'header-container' }, [brand, toggle, nav]);

  const setOpen = open => {
    nav.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.replaceChildren(el('i', { 'data-lucide': open ? 'x' : 'menu' }));
    refreshIcons();
  };
  toggle.addEventListener('click', () => setOpen(!nav.classList.contains('open')));
  nav.addEventListener('click', e => { if (e.target.closest && e.target.closest('a')) setOpen(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') setOpen(false); });
  document.addEventListener('click', e => {
    if (!e.composedPath().includes(container)) setOpen(false);
  });

  return container;
}

// Styles the header needs that style.css doesn't have yet. Safe to move into
// style.css later and delete this block.
const LAYOUT_CSS = `
.nav-link { display:inline-flex; align-items:center; gap:.4rem; }
.nav-link i, .nav-link svg { width:16px; height:16px; }
.nav-user { font-size:.8125rem; color:var(--text-muted); padding:0 .75rem 0 .5rem;
  margin-left:.25rem; border-left:1px solid var(--border-color); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; max-width:14rem; }
.nav-toggle { display:none; background:transparent; border:1px solid var(--border-color);
  border-radius:.625rem; padding:.5rem; cursor:pointer; color:#1e293b; line-height:0; }
.nav-toggle i, .nav-toggle svg { width:20px; height:20px; }

@media (max-width: 1023px) {
  .nav-toggle { display:inline-flex; }
  #nav-links { display:none; position:absolute; top:100%; left:0; right:0; flex-direction:column;
    align-items:stretch; gap:.25rem; padding:.75rem 1rem 1rem; background:#fff;
    border-bottom:1px solid var(--border-color); box-shadow:0 12px 24px rgba(15,23,42,.08); }
  #nav-links.open { display:flex; }
  .nav-user { border-left:0; margin:0; padding:.5rem 1rem; max-width:none; }
  .nav-bell-label { display:inline; }
  #nav-links .nav-bell .badge { position:static; }
}

#flash-host { display:flex; flex-direction:column; gap:.5rem; margin-bottom:1.25rem; }
.flash { display:flex; align-items:flex-start; gap:.625rem; padding:.75rem 1rem;
  border-radius:.75rem; font-size:.875rem; border:1px solid transparent; }
.flash i, .flash svg { width:16px; height:16px; margin-top:.15rem; flex-shrink:0; }
.flash span { flex:1; }
.flash-success { background:#ecfdf5; color:#047857; border-color:#a7f3d0; }
.flash-error { background:#fef2f2; color:#b91c1c; border-color:#fecaca; }
.flash-close { background:none; border:0; color:inherit; font-size:1.25rem; line-height:1;
  cursor:pointer; opacity:.6; }
.flash-close:hover { opacity:1; }

.flash-info { background:#e6f5fc; color:#0073b3; border-color:#b3e0f7; }
.flash-warning { background:#fffbeb; color:#92400e; border-color:#fcd34d; }
.badge { display:inline-flex; align-items:center; justify-content:center; min-width:1.15rem; height:1.15rem; padding:0 .35rem; border-radius:9999px; background:#dc2626; color:#fff; font-size:.6875rem; font-weight:700; line-height:1; }
.badge[hidden], .nav-bell[hidden] { display:none; }
.badge-inline { height:auto; padding:.1rem .45rem; background:var(--accent-text); margin-left:.4rem; vertical-align:middle; }
.nav-bell { position:relative; }
.nav-bell-label { display:none; }
.nav-bell .badge { position:absolute; top:0; right:0; }

.skip-link { position:absolute; left:.5rem; top:-4rem; z-index:100; background:#fff; color:var(--accent-text); font-weight:600; font-size:.875rem; padding:.6rem 1rem; border-radius:.625rem; border:2px solid var(--primary); transition:top .15s; }
.skip-link:focus { top:.5rem; }
main:focus { outline:none; }

.table-wrap { overflow-x:auto; border:1px solid var(--border-color); border-radius:.75rem; }
`;

function injectStyles() {
  if (document.getElementById('layout-styles')) return;
  const style = document.createElement('style');
  style.id = 'layout-styles';
  style.textContent = LAYOUT_CSS;
  document.head.appendChild(style);
}

/** Renders the header into #site-header (or replaces an existing header.header). */
export function initLayout() {
  injectStyles();

  const mount = document.getElementById('site-header') || document.querySelector('header.header');
  if (mount) {
    mount.className = 'header';
    mount.replaceChildren(buildHeader());
  }

  updateLeaveBadge();
  const main = document.querySelector('main');
  if (main) {
    main.id = main.id || 'main-content'; main.tabIndex = -1;
    if (!document.querySelector('.skip-link')) document.body.prepend(el('a', { class: 'skip-link', href: '#' + main.id, text: 'Skip to main content' }));
  }
  makeTablesFocusable();
  applyTranslations();
  refreshIcons();
}

/** Scrollable regions must be reachable by keyboard (tabindex + region + accessible name). */
function makeTablesFocusable() {
  document.querySelectorAll('.table-wrap').forEach(w => {
    const panel = w.closest('[role="tabpanel"]');
    const src = (panel && document.getElementById(panel.getAttribute('aria-labelledby'))) || w.closest('.card')?.querySelector('.card-title');
    const name = src ? [...src.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim() : '';
    w.tabIndex = 0; w.setAttribute('role', 'region'); w.setAttribute('aria-label', name || 'Data table');
  });
}

// ------------------------------------------------------------------ dialogs --
// Replaces confirm()/prompt()/alert(): styled, translated, focus-trapped, Esc/backdrop to cancel.
// confirmDialog -> Promise<boolean>; promptDialog -> Promise<string|null>; alertDialog -> Promise<true>.
let dialogSeq = 0;
function openDialog({ title, message = '', confirmText = 'Confirm', cancelText = 'Cancel', danger = false, alertOnly = false, input = null }) {
  return new Promise(resolve => {
    const id = `dlg${++dialogSeq}`, prev = document.activeElement;
    const overlay = el('div', { class: 'modal-overlay', role: danger || alertOnly ? 'alertdialog' : 'dialog', 'aria-modal': 'true', 'aria-labelledby': `${id}-t`, 'aria-describedby': `${id}-d` });
    const card = el('div', { class: 'modal-card' });
    card.append(el('h3', { class: 'modal-title', id: `${id}-t`, text: title }), el('p', { class: 'modal-description', id: `${id}-d`, text: message }));
    let field = null;
    if (input) {
      field = el('input', { type: 'text', class: 'form-input', id: `${id}-i`, maxlength: '200', placeholder: input.placeholder || '' });
      const group = el('div', { class: 'form-group' }, [el('label', { class: 'form-label', for: `${id}-i`, text: input.label }), field]);
      group.style.marginTop = '1rem'; card.append(group);
    }
    const cancel = el('button', { type: 'button', class: 'btn btn-outline', text: cancelText });
    const ok = el('button', { type: 'button', class: `btn ${danger ? 'btn-red' : 'btn-primary'}`, text: confirmText });
    ok.style.marginTop = '0';
    card.append(el('div', { class: 'modal-actions' }, alertOnly ? [ok] : [cancel, ok]));
    overlay.append(card);
    const cancelValue = input ? null : alertOnly;
    const finish = v => { overlay.remove(); document.body.style.overflow = ''; if (prev && prev.focus) prev.focus(); resolve(v); };
    ok.addEventListener('click', () => finish(input ? field.value.trim() : true));
    cancel.addEventListener('click', () => finish(cancelValue));
    overlay.addEventListener('click', e => { if (e.target === overlay) finish(cancelValue); });
    overlay.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.stopPropagation(); finish(cancelValue); }
      else if (e.key === 'Enter' && field && e.target === field) { e.preventDefault(); ok.click(); }
      else trapFocus(overlay, e);
    });
    document.body.append(overlay); document.body.style.overflow = 'hidden';
    (field || (danger && !alertOnly ? cancel : ok)).focus();
  });
}
export const confirmDialog = o => openDialog(o);
export const alertDialog = o => openDialog({ ...o, alertOnly: true, confirmText: o.confirmText || 'OK' });
export const promptDialog = o => openDialog({ ...o, input: { label: o.label, placeholder: o.placeholder } });

// ------------------------------------------------------------------ back links --
const BACK_LABELS = { 'directory.html': 'Back to directory', 'index.html': 'Back to dashboard', 'departments.html': 'Back to departments',
  'admin_department.html': 'Back to department', 'person.html': 'Back to colleague' };
/**
 * Points a "back" link at the page the visitor came from (same-origin referrer) with a matching label, instead of a fixed target.
 * The admin panel's tab isn't part of the referrer, so the caller says which tab to return to.
 */
export function setupBackLink(a, { fallbackHref, fallbackLabel, adminHash = '', adminLabel = 'Back to employees' }) {
  let href = fallbackHref, label = fallbackLabel;
  try {
    const r = new URL(document.referrer), file = r.pathname.split('/').pop() || 'index.html';
    if (r.origin === location.origin && r.href !== location.href) {
      if (file === 'admin.html') { href = 'admin.html' + adminHash; label = adminLabel; }
      else if (BACK_LABELS[file]) { href = file + r.search; label = BACK_LABELS[file]; }
    }
  } catch { /* no usable referrer: keep the fallback */ }
  a.setAttribute('href', href);
  const text = [...a.childNodes].reverse().find(n => n.nodeType === 3);
  if (text) text.nodeValue = ` ${label}`;
}

