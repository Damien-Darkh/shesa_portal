// pages/admin_user_created.js
// Shows account state the server reports. Polls once per second until nothing is pending.
import { ready, requireAdmin, showFlash, refreshIcons, t } from '../layout.js';
import { api, ApiError } from '../api.js';

const POLL_MS = 1000;
const MAX_POLLS = 60;

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;

  const $ = id => document.getElementById(id);
  const id = new URLSearchParams(location.search).get('id');

  // The password exists only in this tab, right after creation. Read once, then removed.
  const passwordKey = `portal.tempPassword.${id}`;
  const password = id ? sessionStorage.getItem(passwordKey) : null;
  if (id) sessionStorage.removeItem(passwordKey);

  // Warnings from the create request. Shown once.
  const warningsKey = `portal.warnings.${id}`;
  const warnings = JSON.parse(sessionStorage.getItem(warningsKey) || '[]');
  sessionStorage.removeItem(warningsKey);

  const setStatus = (el, state, text) => {
    el.className = 'status ' + (state === 'on' ? 'status--active' : 'status--off');
    el.innerHTML = `<span class="pulse"></span>${text}`;
  };

  // Each row: its pending/settled state, derived from the server's user record.
  // A row is "pending" only while the server might still change it.
  function renderUser(user) {
    $('login-email').textContent = user.email;
    $('created-subtext').textContent = `Account for ${user.email}.`;

    if (user.identity_id) {
      $('identity-id').textContent = user.identity_id;
      $('identity-row').hidden = false;
    }
    if (user.nas_account) {
      $('nas-user').textContent = user.nas_account;
      $('nas-user-row').hidden = false;
    }

    const authentikDone = !!user.authentik_account;
    setStatus($('authentik-status'), authentikDone ? 'on' : 'off',
      authentikDone ? t('Created') : t('Not configured'));

    const nasDone = !!user.nas_account;
    setStatus($('nas-status'), nasDone ? 'on' : 'off',
      nasDone ? t('Created') : t('Not configured'));

    const emailDone = !!user.welcome_email_sent_at;
    setStatus($('email-status'), emailDone ? 'on' : 'off',
      emailDone ? t('Sent') : t('Not sent'));

    return {
      authentikPending: !authentikDone && !!user.authentik_pending,
      nasPending: !nasDone && !!user.nas_pending,
      emailPending: !emailDone && !!user.email_pending,
    };
  }

  // A value is pending only if the server still expects it to change.
  // Unconfigured integrations are settled immediately, so the page never waits on them.
  const stillPending = s => s.authentikPending || s.nasPending || s.emailPending;

  if (password) {
    $('temp-pw').textContent = password;
    $('password-section').hidden = false;
  } else {
    $('password-section').hidden = true;
    $('created-subtext').textContent +=
      ' ' + t('No temporary password is available in this session. Use "Reset password" on the employee page to issue one.');
  }

  if (warnings.length) {
    $('warnings-list').replaceChildren(...warnings.map(w => {
      const li = document.createElement('li');
      li.textContent = w;
      return li;
    }));
    $('warnings-card').hidden = false;
  }

  // Poll until nothing is pending, or the cap is reached.
  async function poll() {
    let polls = 0;
    while (true) {
      try {
        const user = await api(`/api/admin/users/${id}/`);
        const pending = renderUser(user);
        polls += 1;
        if (!stillPending(pending) || polls >= MAX_POLLS) break;
      } catch (err) {
        showFlash(err instanceof ApiError ? err.message : t('Could not load the employee.'), 'error');
        break;
      }
      await new Promise(r => setTimeout(r, POLL_MS));
    }
  }

  $('copy-pw-btn').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('temp-pw').textContent);
    } catch { /* clipboard blocked */ }
    $('copy-pw-text').textContent = t('Copied!');
    setTimeout(() => { $('copy-pw-text').textContent = t('Copy temporary password'); }, 2000);
  });

  refreshIcons();
  await poll();
})();