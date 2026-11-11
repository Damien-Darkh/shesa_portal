// Shows the one-time NAS temporary password handed over by add_user / edit_user / reset.
import { ready, dbData, requireAdmin, showFlash, refreshIcons } from '../layout.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;
  const $ = id => document.getElementById(id);
  const id = new URLSearchParams(location.search).get('id');
  const user = dbData.usersDirectory.find(u => String(u.id) === id);
  const password = id ? sessionStorage.getItem(`portal.tempPassword.${id}`) : null;
  const authentikPassword = id ? sessionStorage.getItem(`portal.authentikTempPassword.${id}`) : null;
  if (id) sessionStorage.removeItem(`portal.tempPassword.${id}`);   // shown once
  if (id) sessionStorage.removeItem(`portal.authentikTempPassword.${id}`);   // shown once

  if (user) {
    $('created-subtext').textContent = `Account created for ${user.email}.`;
    $('dsm-user').textContent = user.dsm_username || '—';
  }
  if (password) {
    $('temp-pw').textContent = password;
  } else {
    $('temp-pw').textContent = '—';
    $('created-subtext').textContent = 'This temporary password was already shown or is no longer available. Use "Reset NAS password" on the employee page to issue a new one.';
  }

  if (user && (user.authentik_account || authentikPassword)) {
    $('authentik-section').hidden = false;
    $('authentik-user').textContent = user.authentik_account || '—';
    $('authentik-temp-pw').textContent = authentikPassword || '— (already shown; use "Reset Authentik password" on the employee page)';
  }
  const flash = sessionStorage.getItem('portal.flash');
  if (flash) { sessionStorage.removeItem('portal.flash'); showFlash(flash, 'info'); }

  $('copy-pw-btn').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('temp-pw').textContent); } catch { /* clipboard blocked */ }
    $('copy-pw-text').textContent = 'Copied!';
    setTimeout(() => { $('copy-pw-text').textContent = 'Copy Temporary Password'; }, 2000);
  });
  $('copy-authentik-pw-btn').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('authentik-temp-pw').textContent); } catch { /* clipboard blocked */ }
    $('copy-authentik-pw-text').textContent = 'Copied!';
    setTimeout(() => { $('copy-authentik-pw-text').textContent = 'Copy Authentik Password'; }, 2000);
  });
  refreshIcons();
})();