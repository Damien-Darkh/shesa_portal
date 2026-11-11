// Forced NAS password change. Standalone page (no shell): while the password is temporary, the server only
// allows /api/me/ and this submit, so this page must not call anything else.
import { applyTranslations } from '../i18n.js';
import { api, ApiError } from '../api.js';
// Icons only: importing layout.js would load the session, which is blocked on this page.
const refreshIcons = () => window.lucide && window.lucide.createIcons();

applyTranslations();
const $ = id => document.getElementById(id);
let banned = [];

const rules = [
  ['At least 8 characters', v => v.length >= 8],
  ['Upper and lower case letters', v => /[a-z]/.test(v) && /[A-Z]/.test(v)],
  ['At least one number', v => /\d/.test(v)],
  ['Doesn\u2019t contain your name or username', v => v && !banned.some(b => v.toLowerCase().includes(b))],
  ['Both passwords match', v => v && v === $('confirm-pw').value],
];

function check() {
  let all = true;
  $('reqs').replaceChildren(...rules.map(([label, fn]) => {
    const ok = !!fn($('new-pw').value); all = all && ok;
    const li = document.createElement('li');
    li.className = ok ? 'ok' : '';
    li.innerHTML = `<i data-lucide="${ok ? 'circle-check' : 'circle'}"></i>`;
    li.append(label);
    return li;
  }));
  $('submit-btn').disabled = !all;
  refreshIcons();
}

document.querySelectorAll('.pw-toggle').forEach(btn => btn.addEventListener('click', () => {
  const input = $(btn.dataset.target), show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  btn.innerHTML = `<i data-lucide="${show ? 'eye-off' : 'eye'}"></i>`;
  refreshIcons();
}));

$('new-pw').addEventListener('input', check);
$('confirm-pw').addEventListener('input', check);

$('pw-form').addEventListener('submit', async e => {
  e.preventDefault();
  if ($('submit-btn').disabled) return;
  try {
    await api('/api/me/dsm-password', { method: 'POST', body: { new_password: $('new-pw').value, confirm_password: $('confirm-pw').value } });
    location.href = 'index.html';
  } catch (err) {
    alert(err instanceof ApiError ? err.message : 'Could not update the password.');
  }
});

(async () => {
  try {
    const me = await api('/api/me/');
    banned = [me.dsm_username, me.first_name, me.last_name].filter(x => x && x.length >= 3).map(x => x.toLowerCase());
  } catch { /* api() handles redirects */ }
  check();
})();
