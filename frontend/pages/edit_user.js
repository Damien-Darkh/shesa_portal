// Admin: edit one employee (profile, access, VPN, NAS, devices, disable, delete). Changes go straight to the API.
import { ready, dbData, requireAdmin, getIdParam, fullName, fillDepartmentSelect, showFlash, refreshIcons, t, confirmDialog, fmtDate, renderAvatar, readImageFile, setupBackLink } from '../layout.js';
import { api } from '../api.js';
import { refreshPeople } from '../store.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;

  const $ = id => document.getElementById(id);
  const me = dbData.currentUser;
  const id = getIdParam();

  setupBackLink($('eu-back'), {
    fallbackHref: 'admin.html',
    fallbackLabel: 'Back to employees',
    adminHash: '#employees',
    adminLabel: 'Back to employees',
  });

  const listed = dbData.usersDirectory.find(u => u.id === id);
  if (!listed) {
    $('eu-missing').hidden = false;
    refreshIcons();
    return;
  }
  $('eu-content').hidden = false;

  const self = id === me.id;
  let user;

  /* ---------- Data ---------- */

  // Always re-read from the server, so the form shows the stored state.
  const load = async () => {
    user = await api(`/api/admin/users/${id}/`);
    user.profile = user.profile || {};
  };

  /* ---------- Rendering ---------- */

  const header = () => {
    $('eu-name').textContent = fullName(user);
    $('eu-email').textContent = `${user.email} · ${user.identity_id || 'no identity ID yet'}`;
    $('eu-status').innerHTML =
      `<span class="status ${user.disabled ? 'status--off' : 'status--active'}">` +
      `<span class="pulse"></span>${user.disabled ? t('Disabled') : t('Active')}` +
      `${user.is_admin ? ' · Admin' : ''}</span>`;
  };

  const preview = () => renderAvatar($('avatar-preview-box'), {
    photoUrl: $('f-photo').value.trim(),
    firstName: $('f-first').value.trim(),
    lastName: $('f-last').value.trim(),
  });

  // Admins always have VPN. Others reflect the stored flag. Disabled accounts have neither.
  function renderAccessState() {
    const isAdminTarget = !!user.is_admin;
    const entitled = isAdminTarget || !!user.vpn_access;

    $('f-admin').checked = !!user.is_admin;
    $('f-admin').disabled = !!user.disabled || self;
    $('f-vpn').checked = entitled;
    $('f-vpn').disabled = isAdminTarget || !!user.disabled;
    $('vpn-note').textContent = isAdminTarget
      ? t('Administrators always have VPN access')
      : t("Turning this off disconnects the employee's VPN devices. They can be restored by turning it back on.");

    $('dev-form').querySelectorAll('input, button').forEach(el => { el.disabled = !entitled || !!user.disabled; });
    $('dev-hint').textContent = entitled ? '' : t('Enable VPN access for this employee before adding a device.');
    $('dev-hint').hidden = entitled;
  }

  function renderDisableState() {
    $('disable-label').textContent = user.disabled ? t('Enable employee') : t('Disable');
    $('disable-btn').classList.toggle('btn-red', !user.disabled);
    $('disable-btn').classList.toggle('btn-outline', !!user.disabled);
    $('disable-title').textContent = user.disabled ? t('Enable employee') : t('Disable employee');
    $('disable-desc').textContent = user.disabled
      ? t('The account is active again. Administrator and VPN access must be granted again.')
      : t('Removes their VPN devices, administrator rights and VPN access. The account is kept and can be re-enabled.');
    $('disable-btn').disabled = self;
  }

  function renderWebsite() {
    const on = !!user.show_on_website;
    $('w-status').textContent = on ? t('Published on the website') : t('Not published');
    $('w-hint').textContent = on
      ? t('Hiding removes the profile from the website. Only the employee can publish it again.')
      : t('The employee publishes their own profile from their profile page.');
    $('w-hide').hidden = !on || !!user.disabled;
    $('w-sync').hidden = !user.sanity_pending;
    $('w-sync-text').textContent = user.sanity_last_error
      ? t('The website is not up to date yet. It will retry automatically.')
      : t('Saved. The website will update shortly.');
  }

  const fill = () => {
    const p = user.profile;
    $('f-first').value = user.first_name || '';
    $('f-last').value = user.last_name || '';
    $('f-email').value = user.email;
    $('f-job').value = p.job_title || '';
    fillDepartmentSelect($('f-dept'), p.department_id);
    $('f-phone').value = p.phone || '';
    $('f-office').value = p.office_location || '';
    $('f-photo').value = p.photo_url || '';
    $('f-bio').value = p.bio || '';
    renderAccessState();
    renderDisableState();
    preview();
  };

  function renderDevices() {
    const rows = user.devices || [];
    $('dev-tbody').innerHTML = rows.length
      ? rows.map(d => `<tr>
          <td data-no-i18n>${String(d.device_name).replace(/</g, '&lt;')}</td>
          <td class="mono">${d.wg_address || ''}</td>
          <td>${fmtDate(d.created_at)}</td>
          <td><span class="status ${d.is_revoked ? 'status--off' : 'status--active'}"><span class="pulse"></span>${d.is_revoked ? t('Disconnected') : t('Active')}</span></td>
          <td><div class="btn-row">
            ${!d.is_revoked
              ? `<button type="button" class="btn btn-red btn-sm" data-act="revoke" data-id="${d.id}"><i data-lucide="power"></i> ${t('Disconnect')}</button>`
              : !d.auto_revoked
                ? `<button type="button" class="btn btn-outline btn-sm" data-act="reconnect" data-id="${d.id}"><i data-lucide="refresh-ccw"></i> ${t('Reconnect')}</button>`
                : ''}
            <button type="button" class="btn btn-red btn-sm" data-act="delete" data-id="${d.id}"><i data-lucide="trash-2"></i> ${t('Delete')}</button>
          </div></td>
        </tr>`).join('')
      : `<tr><td colspan="5"><div class="empty-state"><i data-lucide="inbox"></i><span>${t('No devices.')}</span></div></td></tr>`;
    refreshIcons();
  }

  // Single place that re-reads the server and redraws every section.
  const refreshAll = async () => {
    await Promise.all([load(), refreshPeople()]);
    header();
    fill();
    renderDevices();
  };

  /* ---------- Profile form ---------- */

  ['f-first', 'f-last', 'f-photo'].forEach(x => $(x).addEventListener('input', preview));
  $('f-browse').addEventListener('click', () => $('f-photo-file').click());
  $('f-remove').addEventListener('click', () => { $('f-photo').value = ''; preview(); });
  $('f-photo-file').addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      $('f-photo').value = await readImageFile(file);
      preview();
    } catch (err) {
      showFlash(err.message, 'error');
    }
    e.target.value = '';
  });

  $('profile-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('profile-error');
    err.hidden = true;
    try {
      const r = await api(`/api/admin/users/${id}/`, {
        method: 'PATCH',
        body: {
          email: $('f-email').value.trim(),
          first_name: $('f-first').value.trim(),
          last_name: $('f-last').value.trim(),
          job_title: $('f-job').value.trim(),
          department_id: Number($('f-dept').value) || null,
          phone: $('f-phone').value.trim(),
          office_location: $('f-office').value.trim(),
          photo_url: $('f-photo').value.trim() || null,
          bio: $('f-bio').value.trim(),
        },
      });
      await refreshAll();
      showFlash(`Saved changes for ${fullName(user)}.`, 'success');
      (r.warnings || []).forEach(w => showFlash(w, 'info'));
    } catch (error) {
      err.textContent = t(error.message);
      err.hidden = false;
      $('f-email').focus();
    }
  });

  /* ---------- Access form (administrator, VPN) ---------- */

  $('access-form').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      const body = { is_admin: $('f-admin').checked };
      if (!user.is_admin) body.vpn_access = $('f-vpn').checked;
      const r = await api(`/api/admin/users/${id}/`, { method: 'PATCH', body });
      await refreshAll();
      showFlash(`Saved changes for ${fullName(user)}.`, 'success');
      (r.warnings || []).forEach(w => showFlash(w, 'info'));
    } catch (error) {
      showFlash(error.message, 'error');
      await refreshAll();
    }
  });

  /* ---------- Devices ---------- */

  $('dev-tbody').addEventListener('click', async e => {
    const b = e.target.closest('button[data-act]');
    if (!b) return;
    const d = user.devices.find(x => x.id === Number(b.dataset.id));
    const action = b.dataset.act;

    if (action === 'delete' && !await confirmDialog({
      title: t('Delete device?'),
      message: `Permanently delete ${d.device_name}? This removes the VPN peer entirely and cannot be undone.`,
      confirmText: t('Delete'),
      danger: true,
    })) return;

    if (action === 'revoke' && !await confirmDialog({
      title: t('Disconnect device?'),
      message: `Disconnect ${d.device_name}? This device will lose VPN access immediately.`,
      confirmText: t('Disconnect'),
      danger: true,
    })) return;

    try {
      await api(`/api/devices/${d.id}/${action === 'delete' ? 'delete' : action}`, { method: 'POST' });
      await refreshAll();
    } catch (error) {
      showFlash(error.message, 'error');
    }
  });

  $('dev-form').addEventListener('submit', async e => {
    e.preventDefault();
    const name = $('dev-name').value.trim();
    if (!name) return;
    try {
      const r = await api(`/api/admin/users/${id}/devices`, { method: 'POST', body: { device_name: name } });
      sessionStorage.setItem(`portal.device.${r.device.id}`, JSON.stringify(r));
      location.href = `device_created.html?id=${r.device.id}`;
    } catch (error) {
      showFlash(error.message, 'error');
    }
  });

  /* ---------- show on website ------------ */
  $('w-hide').addEventListener('click', async () => {
    if (!await confirmDialog({
      title: t('Hide from website?'),
      message: `Hide ${fullName(user)} from the company website? Only the employee can publish the profile again.`,
      confirmText: t('Hide'),
      danger: true,
    })) return;
    try {
      const r = await api(`/api/admin/users/${id}/`, { method: 'PATCH', body: { show_on_website: false } });
      await refreshAll();
      showFlash(`${fullName(user)} is hidden from the website.`, 'success');
      (r.warnings || []).forEach(w => showFlash(w, 'info'));
    } catch (error) {
      showFlash(error.message, 'error');
    }
  });
  
  /* ---------- Danger zone: disable / enable, delete ---------- */

  $('disable-btn').addEventListener('click', async () => {
    const enabling = !!user.disabled;
    const ok = await confirmDialog({
      title: enabling ? t('Enable employee?') : t('Disable employee?'),
      message: enabling
        ? `Re-enable ${fullName(user)}? Their account becomes active again. Administrator and VPN access are not restored automatically.`
        : `Disable ${fullName(user)}? Their VPN devices are permanently deleted, from the VPN server and from the portal, and their administrator rights and VPN access are removed. They cannot sign in until re-enabled.`,
      confirmText: enabling ? t('Enable') : t('Disable'),
      danger: !enabling,
    });
    if (!ok) return;
    try {
      const r = await api(`/api/admin/users/${id}/`, { method: 'PATCH', body: { disabled: !enabling } });
      await refreshAll();
      showFlash(`${enabling ? 'Enabled' : 'Disabled'} ${fullName(user)}.`, 'success');
      (r.warnings || []).forEach(w => showFlash(w, 'info'));
    } catch (error) {
      showFlash(error.message, 'error');
    }
  });

  $('delete-btn').addEventListener('click', async () => {
    const devices = (user.devices || []).length;
    const extra = devices
      ? ` Their ${devices} VPN device${devices > 1 ? 's' : ''} will also be removed permanently.`
      : '';
    if (!await confirmDialog({
      title: t('Delete employee?'),
      message: `Permanently delete ${user.email} and all of their devices? This cannot be undone.${extra}`,
      confirmText: t('Delete'),
      danger: true,
    })) return;
    try {
      const r = await api(`/api/admin/users/${id}/`, { method: 'DELETE' });
      (r.warnings || []).forEach(w => sessionStorage.setItem('portal.flash', w));
      location.href = 'admin.html';
    } catch (error) {
      showFlash(error.message, 'error');
    }
  });

  /* ---------- NAS ---------- */

  $('nas-reset').addEventListener('click', async e => {
    e.preventDefault();
    if (!await confirmDialog({
      title: t('Reset NAS password?'),
      message: `Reset the NAS password for ${fullName(user)}? A temporary password is generated and they must set their own at next sign-in.`,
      confirmText: t('Reset password'),
    })) return;
    try {
      const r = await api(`/api/admin/users/${id}/reset-nas-password`, { method: 'POST' });
      sessionStorage.setItem(`portal.tempPassword.${id}`, r.nas_temporary_password);
      location.href = `admin_user_created.html?id=${id}`;
    } catch (error) {
      showFlash(error.message, 'error');
    }
  });

  /* ---------- Start ---------- */

  await load();
  if (self) {
    $('access-card').hidden = true;
    $('danger-card').hidden = true;
    $('self-note').hidden = false;
  }
  if (user.nas_account) {
    $('nas-card').hidden = false;
    $('nas-user').textContent = user.nas_account;
  }
  header();
  fill();
  renderDevices();
  refreshIcons();
})();