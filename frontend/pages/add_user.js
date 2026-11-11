// Admin: create an employee. The server creates the NAS account and returns a one-time temporary password,
// which is handed to the next page through sessionStorage (it is never stored on the server).
import { ready, dbData, requireAdmin, fillDepartmentSelect, renderAvatar, readImageFile, showFlash, refreshIcons, t } from '../layout.js';
import { api, ApiError } from '../api.js';
import { refreshPeople } from '../store.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;
  const $ = id => document.getElementById(id);
  fillDepartmentSelect($('u-dept'));

  const preview = () => renderAvatar($('avatar-preview-box'), { photoUrl: $('u-photo').value.trim(), firstName: $('u-firstname').value.trim(), lastName: $('u-lastname').value.trim() });
  ['u-firstname', 'u-lastname', 'u-photo'].forEach(x => $(x).addEventListener('input', preview));
  $('u-browse-btn').addEventListener('click', () => $('u-photo-file').click());
  $('u-photo-file').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    try { $('u-photo').value = await readImageFile(f); preview(); } catch (err) { showFlash(err.message, 'error'); }
    e.target.value = '';
  });

  $('add-user-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('form-error'); err.hidden = true;
    const fail = (msg, field) => { err.textContent = t(msg); err.hidden = false; $(field).focus(); };
    if (!$('u-email').value.trim()) return fail('Enter a valid email address.', 'u-email');
    try {
      const r = await api('/api/admin/users/', { method: 'POST', body: {
        email: $('u-email').value.trim(), first_name: $('u-firstname').value.trim(), last_name: $('u-lastname').value.trim(),
        is_admin: $('e-isadmin').checked, job_title: $('u-jobtitle').value.trim(), department_id: Number($('u-dept').value) || null,
        phone: $('u-phone').value.trim(), office_location: $('u-office').value.trim(),
        photo_url: $('u-photo').value.trim() || null, bio: $('u-bio').value.trim(),
        start_date: new Date().toISOString().slice(0, 10),
      } });
      if (r.nas_temporary_password) sessionStorage.setItem(`portal.tempPassword.${r.user.id}`, r.nas_temporary_password);
      if (r.authentik_temporary_password) sessionStorage.setItem(`portal.authentikTempPassword.${r.user.id}`, r.authentik_temporary_password);
      (r.warnings || []).forEach(w => sessionStorage.setItem('portal.flash', w));
      await refreshPeople();
      location.href = `admin_user_created.html?id=${r.user.id}`;
    } catch (error) {
      const field = error.message.includes('email') ? 'u-email' : 'u-firstname';
      fail(error.message, field);
    }
  });
  refreshIcons();
})();