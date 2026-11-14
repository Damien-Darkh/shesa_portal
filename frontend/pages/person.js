// Colleague profile. Everyone sees the public part. Administrators also get account, organisation,
// devices and leave history from /api/admin/users/<id>/.
import { ready, dbData, getIdParam, fullName, renderAvatar, esc, fmtDate, getLang, refreshIcons, confirmDialog, showFlash, setupBackLink, t } from '../layout.js';
import { api, ApiError } from '../api.js';

(async () => {
  if (!await ready) return;
  const $ = id => document.getElementById(id), me = dbData.currentUser;
  setupBackLink($('p-back'), { fallbackHref: 'directory.html', fallbackLabel: 'Back to directory', adminHash: '#employees', adminLabel: 'Back to employees' });

  const id = getIdParam();
  const base = dbData.usersDirectory.find(u => u.id === id);
  if (!base) { $('p-missing').hidden = false; return; }
  const u = base.id === me.id ? { ...base, ...me, profile: { ...base.profile, ...me.profile } } : base;
  const p = u.profile || {}, dept = dbData.departments.find(d => d.id === p.department_id);
  $('p-content').hidden = false;

  renderAvatar($('p-avatar'), { photoUrl: p.photo_url, firstName: u.first_name, lastName: u.last_name });
  $('p-name').textContent = fullName(u); $('p-job').textContent = p.job_title || '';
  $('p-email').textContent = u.email; $('p-email').href = `mailto:${u.email}`;
  $('p-phone').textContent = p.phone || '—'; if (p.phone) $('p-phone').href = `tel:${p.phone.replace(/[^\d+]/g, '')}`;
  $('p-dept').textContent = dept ? dept.name : '—'; $('p-office').textContent = p.office_location || '—';
  if (p.start_date) { $('p-start').textContent = fmtDate(p.start_date); $('p-start-wrap').hidden = false; }
  if (p.bio) { $('p-bio').textContent = p.bio; $('p-bio-wrap').hidden = false; }
  document.title = `${fullName(u)} - Employee Portal`;

  if (!me.is_admin) { refreshIcons(); return; }

  let detail;
  try { detail = await api(`/api/admin/users/${u.id}/`); }
  catch (err) { showFlash(err.message, 'error'); refreshIcons(); return; }

  const kv = (label, value) => `<div class="detail-item"><div><p class="label">${label}</p><p class="value">${value}</p></div></div>`;
  const mono = v => v ? `<span class="mono">${esc(v)}</span>` : '—';
  const dt = iso => iso ? new Date(iso).toLocaleString(getLang() === 'it' ? 'it-IT' : 'en-GB') : '—';
  const pill = (cls, text) => `<span class="status ${cls}">${text}</span>`;
  const link = (href, text) => `<a href="${href}">${esc(text)}</a>`;
  const kind = s => ({ PENDING: 'pending', DENIED: 'denied', CANCELLED: 'cancelled' }[s] || 'approved');
  const label = { pending: 'Pending', denied: 'Denied', approved: 'Approved', cancelled: 'Cancelled' };
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const devices = detail.devices || [];

  $('adm').hidden = false; $('adm-actions').hidden = false;
  $('a-edit').href = `edit_user.html?id=${u.id}`;
  const nas = $('a-nas'); nas.hidden = false;
  if (!detail.nas_account) { nas.disabled = true; nas.title = t('This employee has no NAS account'); }
  nas.addEventListener('click', async () => {
    if (!await confirmDialog({ title: 'Reset NAS password?', message: `Reset the NAS password for ${fullName(u)}? A temporary password is generated and they must set their own at next sign-in.`, confirmText: 'Reset password' })) return;
    try {
      const r = await api(`/api/admin/users/${u.id}/reset-nas-password`, { method: 'POST' });
      sessionStorage.setItem(`portal.tempPassword.${u.id}`, r.nas_temporary_password);
      location.href = `admin_user_created.html?id=${u.id}`;
    } catch (err) { showFlash(err.message, 'error'); }
  });

  const authentik = $('a-authentik'); authentik.hidden = false;
  if (!detail.authentik_account) { authentik.disabled = true; authentik.title = t('This employee has no Authentik account'); }
  authentik.addEventListener('click', async () => {
    if (!await confirmDialog({ title: 'Reset Authentik password?', message: `Reset the Authentik sign-in password for ${fullName(u)}? A temporary password is generated immediately.`, confirmText: 'Reset password' })) return;
    try {
      const r = await api(`/api/admin/users/${u.id}/reset-authentik-password`, { method: 'POST' });
      sessionStorage.setItem(`portal.authentikTempPassword.${u.id}`, r.authentik_temporary_password);
      location.href = `admin_user_created.html?id=${u.id}`;
    } catch (err) { showFlash(err.message, 'error'); }
  });

  $('p-pills').hidden = false;
  $('p-pills').innerHTML = pill(u.is_admin ? 'status--admin' : 'status--staff', u.is_admin ? 'Admin' : 'Staff')
    + pill(u.disabled ? 'status--off' : 'status--active', `<span class="pulse"></span>${u.disabled ? 'Disabled' : 'Active'}`);

  $('adm-account').innerHTML =
    kv('Identity ID', mono(detail.identity_id || 'Not assigned')) +
    kv('Status', u.disabled ? 'Disabled' : 'Active') + kv('Created', dt(detail.created_at)) +
    kv('Last profile update', dt(p.updated_at)) +
    kv('NAS username', detail.nas_account ? mono(detail.nas_account) : 'Not provisioned') +
    kv('Password change', detail.nas_account ? (detail.dsm_must_change_password ? 'Required at next sign-in' : 'Not required') : '—') +
    kv('Authentik username', detail.authentik_account ? mono(detail.authentik_account) : 'Not provisioned') +
    kv('VPN access', detail.is_admin ? t('Administrators always have VPN access') : (u.vpn_access ? t('Yes') : t('No'))) +
    kv('Devices', `${devices.filter(d => !d.is_revoked).length} / ${devices.length}`);
    

  const chain = []; for (let q = dept, n = 0; q && n < 20; q = dbData.departments.find(x => x.id === q.parent_id), n++) chain.unshift(q.name);
  const mgr = dept && dbData.usersDirectory.find(x => x.id === dept.manager_id);
  const manages = dbData.departments.filter(d => d.manager_id === u.id);
  const mates = dept ? dbData.usersDirectory.filter(x => !x.disabled && x.id !== u.id && x.profile?.department_id === dept.id).length : 0;
  $('adm-org').innerHTML =
    kv('Department', dept ? link(`admin_department.html?id=${dept.id}`, dept.name) : '—') +
    kv('Department path', chain.length ? esc(chain.join(' › ')) : '—') +
    kv('Manager', mgr && mgr.id !== u.id ? link(`person.html?id=${mgr.id}`, fullName(mgr)) : '—') +
    kv('Manages', manages.length ? manages.map(d => link(`admin_department.html?id=${d.id}`, d.name)).join(', ') : '—') +
    kv('Colleagues in department', mates);

  $('adm-devices').innerHTML = devices.length ? devices.map(d => `<tr><td>${esc(d.device_name)}</td><td class="mono">${esc(d.wg_address || '')}</td><td>${fmtDate(d.created_at)}</td>
    <td>${d.is_revoked ? pill('status--off', d.auto_revoked ? 'Disconnected (account disabled)' : 'Disconnected') : pill('status--active', '<span class="pulse"></span>Active')}</td></tr>`).join('')
    : '<tr><td colspan="4"><div class="empty-state"><i data-lucide="inbox"></i><span>No devices.</span></div></td></tr>';

  const bal = detail.leave_balances || [];
  $('adm-balances').hidden = !bal.length;
  $('adm-bal-body').innerHTML = bal.map(b => `<tr><td>${esc(cap(b.leave_type))}</td><td>${b.accrued_days}</td><td>${b.carryover_days}</td><td>${b.used_days}</td><td>${b.pending_days}</td>
    <td><strong>${b.available_days}</strong></td></tr>`).join('');
  const reqs = detail.leave_requests || [];
  $('adm-leave').innerHTML = reqs.length ? reqs.map(r => { const k = kind(r.status); return `<tr><td>${esc(cap(r.leave_type))}</td><td>${fmtDate(r.start_date)} &rarr; ${fmtDate(r.end_date)}</td><td>${r.days_requested}</td>
    <td style="white-space:normal;min-width:10rem;">${esc(r.reason || '')}${k === 'denied' && r.approver_comment ? `<div class="form-hint">${esc(r.approver_comment)}</div>` : ''}</td>
    <td>${pill('status--' + k, label[k])}</td></tr>`; }).join('')
    : '<tr><td colspan="5"><div class="empty-state"><i data-lucide="inbox"></i><span>No leave requests.</span></div></td></tr>';
  refreshIcons();
})();