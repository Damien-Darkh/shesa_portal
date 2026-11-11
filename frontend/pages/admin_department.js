// Department detail for admins: summary, members, edit and delete.
import { ready, dbData, requireAdmin, getIdParam, getUserById, fullName, renderAvatar, esc, fmtDate, departmentDialog, deleteDepartmentFlow, descendantIds, refreshIcons, setupBackLink } from '../layout.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;
  const $ = id => document.getElementById(id), id = getIdParam();
  setupBackLink($('dp-back'), { fallbackHref: 'admin.html#departments', fallbackLabel: 'Back to departments', adminHash: '#departments', adminLabel: 'Back to departments' });
  const byId = x => dbData.departments.find(d => d.id === x);
  if (!byId(id)) { $('dp-missing').hidden = false; refreshIcons(); return; }
  $('dp-content').hidden = false;

  const users = dbData.usersDirectory || [];
  const link = (href, text) => `<a href="${href}">${esc(text)}</a>`;
  const row = (icon, label, value) => `<div class="detail-item"><i data-lucide="${icon}" class="icon"></i><div><p class="label">${label}</p><p class="value">${value}</p></div></div>`;

  function render() {
    const d = byId(id);
    if (!d) { location.href = 'admin.html#departments'; return; }
    const direct = users.filter(u => u.profile?.department_id === id);
    const active = x => users.filter(u => !u.disabled && u.profile?.department_id === x).length;
    const total = active(id) + [...descendantIds(id)].reduce((s, c) => s + active(c), 0);
    const chain = []; for (let p = byId(d.parent_id), n = 0; p && n < 20; p = byId(p.parent_id), n++) chain.unshift(p.name);
    const mgr = getUserById(d.manager_id), parent = byId(d.parent_id), subs = dbData.departments.filter(x => x.parent_id === id);

    document.title = `${d.name} - Employee Portal`;
    $('dp-crumb').textContent = chain.length ? chain.join(' › ') : 'Department';
    $('dp-name').textContent = d.name; $('dp-desc').textContent = d.description || ''; $('dp-desc').hidden = !d.description;
    $('dp-summary').innerHTML =
      row('user', 'Manager', mgr ? link(`person.html?id=${mgr.id}`, fullName(mgr)) : '—') +
      row('building-2', 'Parent department', parent ? link(`admin_department.html?id=${parent.id}`, parent.name) : 'Top level') +
      row('users', 'Direct members', active(id)) +
      row('users', 'Total members', `${total} <span class="form-hint" style="display:inline;margin:0;">Including sub-departments</span>`) +
      row('building-2', 'Sub-departments', subs.length ? subs.map(s => link(`admin_department.html?id=${s.id}`, s.name)).join(', ') : '—');

    direct.sort((a, b) => (b.id === d.manager_id) - (a.id === d.manager_id) || fullName(a).localeCompare(fullName(b)));
    $('dp-members').innerHTML = direct.length ? direct.map(u => {
      const p = u.profile || {};
      return `<article class="card" style="padding:1.25rem;">
        <div class="name-cell" style="align-items:flex-start;gap:.9rem;">
          <div class="avatar-box" data-uid="${u.id}" style="width:3.5rem;height:3.5rem;font-size:1.1rem;flex-shrink:0;"></div>
          <div style="min-width:0;">
            <p class="value" style="margin:0;"><a href="person.html?id=${u.id}">${esc(fullName(u))}</a></p>
            <p class="label" style="margin:.1rem 0 0;">${esc(p.job_title || '')}</p>
            <div class="btn-row" style="margin-top:.5rem;gap:.4rem;">
              <span class="status ${u.is_admin ? 'status--admin' : 'status--staff'}">${u.is_admin ? 'Admin' : 'Staff'}</span>
              ${u.id === d.manager_id ? '<span class="status status--admin">Manager</span>' : ''}
              ${u.disabled ? '<span class="status status--off">Disabled</span>' : ''}
            </div>
          </div>
        </div>
        <div class="space-y" style="margin-top:1rem;">
          ${row('mail', 'Email', link('mailto:' + u.email, u.email))}
          ${row('phone', 'Phone', p.phone ? link('tel:' + p.phone.replace(/[^\d+]/g, ''), p.phone) : '—')}
          ${row('map-pin', 'Office Location', esc(p.office_location || '—'))}
          ${row('calendar', 'Start Date', p.start_date ? fmtDate(p.start_date) : '—')}
        </div>
        ${p.bio ? `<p class="bio-text" style="margin-top:.9rem;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${esc(p.bio)}</p>` : ''}
        <div class="btn-row" style="margin-top:1rem;">
          <a class="btn btn-outline btn-sm" href="person.html?id=${u.id}"><i data-lucide="user"></i> View profile</a>
          <a class="btn btn-outline btn-sm" href="edit_user.html?id=${u.id}"><i data-lucide="pencil"></i> Edit</a>
        </div></article>`;
    }).join('') : '<p class="card-subtitle">No members in this department.</p>';

    direct.forEach(u => renderAvatar(document.querySelector(`.avatar-box[data-uid="${u.id}"]`), { photoUrl: u.profile?.photo_url, firstName: u.first_name, lastName: u.last_name }));
    refreshIcons();
  }

  $('dp-edit').addEventListener('click', async () => { if (await departmentDialog(id)) render(); $('dp-edit').focus(); });
  $('dp-delete').addEventListener('click', async () => { if (await deleteDepartmentFlow(id)) location.href = 'admin.html#departments'; });
  render();
})();
