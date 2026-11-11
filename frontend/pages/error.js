// Shared script for the error pages: translations, icons, and the Back / Try again buttons.
import { applyTranslations } from '../i18n.js';

applyTranslations();
document.querySelectorAll('[data-action]').forEach(btn => btn.addEventListener('click', () => {
  if (btn.dataset.action === 'back') history.length > 1 ? history.back() : (location.href = '/index.html');
  if (btn.dataset.action === 'reload') location.reload();
}));
window.lucide && window.lucide.createIcons();