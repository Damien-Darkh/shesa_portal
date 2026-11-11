// Admin: edit one employee (profile, access, NAS, devices, delete). Changes go straight to the API.
import { ready, dbData, requireAdmin, getIdParam, fullName, fillDepartmentSelect, showFlash, refreshIcons, t, confirmDialog, fmtDate, renderAvatar, readImageFile, setupBackLink } from '../layout.js';
import { api, ApiError } from '../api.js';
import { refreshPeople } from '../store.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;
  const $ = id => document.getElementById(id), me = dbData.currentUser, id = getIdParam();
  setupBackLink($('eu-back'), { fallbackHref: 'admin.html', fallbackLabel: 'Back to employees', adminHash: '#employees', adminLabel: 'Back to employees' });
  const listed = dbData.usersDirectory.find(u => u.id === id);
  if (!listed) { $('eu-missing').hidden = false; refreshIcons(); return; }
  $('eu-content').hidden = false;
  const self = id === me.id;
  let user;

  const load = async () => { user = await api(`/api/admin/users/${id}/`); user.profile = user.profile || {}; };
  const header = () => {
    $('eu-name').textContent = fullName(user); $('eu-email').textContent = user.email;
    $('eu-status').innerHTML = `<span class="status ${user.disabled ? 'status--off' : 'status--active'}"><span class="pulse"></span>${user.disabled ? 'Disabled' : 'Active'}${user.is_admin ? ' · Admin' : ''}</span>`;
  };
  const preview = () => renderAvatar($('avatar-preview-box'), { photoUrl: $('f-photo').value.trim(), firstName: $('f-first').value.trim(), lastName: $('f-last').value.trim() });
  const fill = () => {
    const p = user.profile;
    $('f-first').value = user.first_name || ''; $('f-last').value = user.last_name || ''; $('f-email').value = user.email;
    $('f-job').value = p.job_title || ''; fillDepartmentSelect($('f-dept'), p.department_id);
    $('f-phone').value = p.phone || ''; $('f-office').value = p.office_location || ''; $('f-photo').value = p.photo_url || ''; $('f-bio').value = p.bio || '';
    $('f-admin').checked = !!user.is_admin; $('f-disabled').checked = !!user.disabled;
    preview();
  };

  ['f-first', 'f-last', 'f-photo'].forEach(x => $(x).addEventListener('input', preview));
  $('f-browse').addEventListener('click', () => $('f-photo-file').click());
  $('f-remove').addEventListener('click', () => { $('f-photo').value = ''; preview(); });
  $('f-photo-file').addEventListener('change', async e => {
    const file = e.target.files[0]; if (!file) return;
    try { $('f-photo').value = await readImageFile(file); preview(); } catch (err) { showFlash(err.message, 'error'); }
    e.target.value = '';
  });

  $('profile-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('profile-error'); err.hidden = true;
    try {
      const r = await api(`/api/admin/users/${id}/`, { method: 'PATCH', body: {
        email: $('f-email').value.trim(), first_name: $('f-first').value.trim(), last_name: $('f-last').value.trim(),
        job_title: $('f-job').value.trim(), department_id: Number($('f-dept').value) || null, phone: $('f-phone').value.trim(),
        office_location: $('f-office').value.trim(), photo_url: $('f-photo').value.trim() || null, bio: $('f-bio').value.trim(),
      } });
      await Promise.all([load(), refreshPeople()]);
      header(); fill();
      showFlash(`Saved changes for ${fullName(user)}.`, 'success');
      (r.warnings || []).forEach(w => showFlash(w, 'info'));
    } catch (error) { err.textContent = t(error.message); err.hidden = false; $('f-email').focus(); }
  });

  $('access-form').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/admin/users/${id}/`, { method: 'PATCH', body: { is_admin: $('f-admin').checked, disabled: $('f-disabled').checked } });
      await Promise.all([load(), refreshPeople()]);
      header(); fill(); renderDevices();
      showFlash(`Saved changes for ${fullName(user)}.`, 'success');
    } catch (error) { showFlash(error.message, 'error'); }
  });

  function renderDevices() {
    const rows = user.devices || [];
    $('dev-tbody').innerHTML = rows.length ? rows.map(d => `<tr>
      <td data-no-i18n>${String(d.device_name).replace(/</g, '&lt;')}</td><td class="mono">${d.wg_address || ''}</td><td>${fmtDate(d.created_at)}</td>
      <td><span class="status ${d.is_revoked ? 'status--off' : 'status--active'}"><span class="pulse"></span>${d.is_revoked ? 'Disconnected' : 'Active'}</span></td>
      <td><div class="btn-row">
        ${!d.is_revoked ? `<button type="button" class="btn btn-red btn-sm" data-act="revoke" data-id="${d.id}"><i data-lucide="power"></i> Disconnect</button>`
          : !d.auto_revoked ? `<button type="button" class="btn btn-outline btn-sm" data-act="reconnect" data-id="${d.id}"><i data-lucide="refresh-ccw"></i> Reconnect</button>` : ''}
        <button type="button" class="btn btn-red btn-sm" data-act="delete" data-id="${d.id}"><i data-lucide="trash-2"></i> Delete</button></div></td></tr>`).join('')
      : '<tr><td colspan="5"><div class="empty-state"><i data-lucide="inbox"></i><span>No devices.</span></div></td></tr>';
    refreshIcons();
  }
  $('dev-tbody').addEventListener('click', async e => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const d = user.devices.find(x => x.id === Number(b.dataset.id));
    const action = b.dataset.act;
    if (action === 'delete' && !await confirmDialog({ title: 'Delete device?', message: `Permanently delete ${d.device_name}? This removes the VPN peer entirely and cannot be undone.`, confirmText: 'Delete', danger: true })) return;
    if (action === 'revoke' && !await confirmDialog({ title: 'Disconnect device?', message: `Disconnect ${d.device_name}? This device will lose VPN access immediately.`, confirmText: 'Disconnect', danger: true })) return;
    try {
      await api(`/api/devices/${d.id}/${action === 'delete' ? 'delete' : action}`, { method: 'POST' });
      await load(); renderDevices();
    } catch (error) { showFlash(error.message, 'error'); }
  });

  $('dev-form').addEventListener('submit', async e => {
    e.preventDefault();
    const name = $('dev-name').value.trim(); if (!name) return;
    try {
      const r = await api(`/api/admin/users/${id}/devices`, { method: 'POST', body: { device_name: name } });
      sessionStorage.setItem(`portal.device.${r.device.id}`, JSON.stringify(r));
      location.href = `device_created.html?id=${r.device.id}`;
    } catch (error) { showFlash(error.message, 'error'); }
  });

  $('delete-btn').addEventListener('click', async () => {
    if (!await confirmDialog({ title: 'Delete employee?', message: `Permanently delete ${user.email} and all of their devices? This cannot be undone.`, confirmText: 'Delete', danger: true })) return;
    try {
      const r = await api(`/api/admin/users/${id}/`, { method: 'DELETE' });
      (r.warnings || []).forEach(w => sessionStorage.setItem('portal.flash', w));
      location.href = 'admin.html';
    } catch (error) { showFlash(error.message, 'error'); }
  });

  $('nas-reset').addEventListener('click', async e => {
    e.preventDefault();
    if (!await confirmDialog({ title: 'Reset NAS password?', message: `Reset the NAS password for ${fullName(user)}? A temporary password is generated and they must set their own at next sign-in.`, confirmText: 'Reset password' })) return;
    try {
      const r = await api(`/api/admin/users/${id}/reset-nas-password`, { method: 'POST' });
      sessionStorage.setItem(`portal.tempPassword.${id}`, r.nas_temporary_password);
      location.href = `admin_user_created.html?id=${id}`;
    } catch (error) { showFlash(error.message, 'error'); }
  });

  await load();
  if (self) { $('access-card').hidden = true; $('danger-card').hidden = true; $('self-note').hidden = false; }
  if (user.nas_account) { $('nas-card').hidden = false; $('nas-user').textContent = user.nas_account; }
  header(); fill(); renderDevices(); refreshIcons();
})();
