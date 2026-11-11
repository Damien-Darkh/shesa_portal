// My profile: read-only details (admins edit them), interface language, NAS password entry point.
import { ready, dbData, showFlash, getLang, setLang, refreshIcons } from '../layout.js';
import { api } from '../api.js';

(async () => {
  if (!await ready) return;
  const user = dbData.currentUser, $ = id => document.getElementById(id);

  const langSel = $('lang-select');
  langSel.value = getLang();
  langSel.addEventListener('change', async () => {
    try {
      await api('/api/me/', { method: 'PATCH', body: { language: langSel.value } });
      setLang(langSel.value);
      location.reload();
    } catch (err) { showFlash(err.message, 'error'); }
  });

  $('p-email').value = user.email;
  $('p-firstname').value = user.first_name || '';
  $('p-lastname').value = user.last_name || '';
  const p = user.profile || {};
  $('p-job').value = p.job_title || '';
  $('p-phone').value = p.phone || '';
  $('p-office').value = p.office_location || '';
  document.querySelectorAll('#profile-form input').forEach(i => { i.disabled = true; i.classList.add('readonly'); });

  if (user.dsm_username) {
    $('nas-section').hidden = false;
    $('nas-username').textContent = user.dsm_username;
  } else {
    $('no-nas-section').hidden = false;
  }
  refreshIcons();
})();
