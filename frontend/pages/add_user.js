// Admin: create an employee. The server creates the NAS and Authentik accounts and returns one shared
// temporary password. It is handed to the next page through sessionStorage and never stored on the server.
import { ready, dbData, requireAdmin, fillDepartmentSelect, renderAvatar, readImageFile, showFlash, refreshIcons, t } from '../layout.js';
import { api } from '../api.js';
import { refreshPeople } from '../store.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;

  const $ = id => document.getElementById(id);
  fillDepartmentSelect($('u-dept'));

  const preview = () => renderAvatar($('avatar-preview-box'), {
    photoUrl: $('u-photo').value.trim(),
    firstName: $('u-firstname').value.trim(),
    lastName: $('u-lastname').value.trim(),
  });

  ['u-firstname', 'u-lastname', 'u-photo'].forEach(x => $(x).addEventListener('input', preview));
  $('u-browse-btn').addEventListener('click', () => $('u-photo-file').click());
  $('u-photo-file').addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      $('u-photo').value = await readImageFile(file);
      preview();
    } catch (err) {
      showFlash(err.message, 'error');
    }
    e.target.value = '';
  });

  $('add-user-form').addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('form-error');
    err.hidden = true;

    const fail = (msg, field) => {
      err.textContent = t(msg);
      err.hidden = false;
      $(field)?.focus();
    };

    const email = $('u-email').value.trim();
    if (!email) return fail('Enter a valid email address.', 'u-email');

    const body = {
      email,
      first_name: $('u-firstname').value.trim(),
      last_name: $('u-lastname').value.trim(),
      is_admin: $('e-isadmin').checked,
      job_title: $('u-jobtitle').value.trim(),
      department_id: Number($('u-dept').value) || null,
      phone: $('u-phone').value.trim(),
      office_location: $('u-office').value.trim(),
      photo_url: $('u-photo').value.trim() || null,
      bio: $('u-bio').value.trim(),
      start_date: new Date().toISOString().slice(0, 10),
    };

    try {
      const r = await api('/api/admin/users/', { method: 'POST', body });
      const id = r.user.id;

      // The password exists only in this tab. The next page reads it once and removes it.
      if (r.temporary_password) {
        sessionStorage.setItem(`portal.tempPassword.${id}`, r.temporary_password);
      }
      sessionStorage.setItem(`portal.warnings.${id}`, JSON.stringify(r.warnings || []));

      await refreshPeople();
      location.href = `admin_user_created.html?id=${id}`;
    } catch (error) {
      // The server names the field at fault. Anything else focuses the first name.
      const field = error.body?.field === 'email' ? 'u-email' : 'u-firstname';
      fail(error.message, field);
    }
  });

  refreshIcons();
})();