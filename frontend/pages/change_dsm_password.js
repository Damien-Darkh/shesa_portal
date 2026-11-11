// Change the NAS password (voluntary). Same rules as the forced page; the server validates the password too.
import { ready, alertDialog, showFlash, refreshIcons } from '../layout.js';
import { api } from '../api.js';

(async () => {
  if (!await ready) return;
  refreshIcons();
  document.getElementById('password-form').addEventListener('submit', async e => {
    e.preventDefault();
    const p1 = document.getElementById('new-pw').value, p2 = document.getElementById('confirm-pw').value;
    if (p1 !== p2) { showFlash('Passwords do not match.', 'error'); return; }
    try {
      await api('/api/me/dsm-password', { method: 'POST', body: { new_password: p1, confirm_password: p2 } });
      await alertDialog({ title: 'Password updated', message: 'Your NAS password has been updated.' });
      location.href = 'index.html';
    } catch (err) { showFlash(err.message, 'error'); }
  });
})();
