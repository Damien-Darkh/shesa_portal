// Sign-in page. Works before any session exists: it reads public config and starts the SSO flow.
import { applyTranslations, getLang, setLang, t } from '../i18n.js';

const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);

const messages = {
  sso: 'Sign-in failed. Try again, or contact IT if it keeps happening.',
  signedout: 'You have been signed out.',
};
if (messages[params.get('error')]) showNotice(messages[params.get('error')]);
if (params.has('signedout')) showInfo('You have been signed out.');

function showNotice(text) { $('notice-text').textContent = t(text); $('notice').hidden = false; }
function showInfo(text) { $('info-text').textContent = t(text); $('info').hidden = false; }

// Language choice is stored on this device until sign-in, then the saved profile language takes over.
const langSel = $('lang-select');
langSel.value = getLang();
langSel.addEventListener('change', () => { setLang(langSel.value); location.reload(); });

applyTranslations();

// Where the sign-in starts comes from the server, so the page doesn't hard-code the provider.
(async () => {
  const next = params.get('next');
  try {
    const res = await fetch('/api/auth/config/' + (next ? `?next=${encodeURIComponent(next)}` : ''), { credentials: 'same-origin' });
    if (!res.ok) throw new Error(String(res.status));
    const cfg = await res.json();
    if (!cfg.sso_enabled) { location.replace('/index.html'); return; }
    $('sso-btn').href = cfg.sso_url;
    $('sso-label').textContent = t(`Sign in with ${cfg.provider_name}`);
  } catch {
    $('sso-btn').removeAttribute('href');
    $('sso-btn').setAttribute('aria-disabled', 'true');
    $('sso-unavailable').hidden = false;
    showNotice('Could not start sign-in. Refresh the page or contact IT.');
  }
  window.lucide && window.lucide.createIcons();
})();
window.lucide && window.lucide.createIcons();