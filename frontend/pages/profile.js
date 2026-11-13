// My profile: contact details and website profile are editable by the employee.
// Job details are read-only (HR manages them). Publishing on the website needs explicit consent.
import { ready, dbData, showFlash, getLang, setLang, refreshIcons, t } from '../layout.js';
import { api } from '../api.js';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

(async () => {
  if (!await ready) return;
  const $ = id => document.getElementById(id);
  const user = dbData.currentUser;
  let me = await api('/api/me/');   // extended fields (emails, LinkedIn, website) live here

  /* ---------- Language ---------- */
  const langSel = $('lang-select');
  langSel.value = getLang();
  langSel.addEventListener('change', async () => {
    try {
      await api('/api/me/', { method: 'PATCH', body: { language: langSel.value } });
      setLang(langSel.value);
      location.reload();
    } catch (err) { showFlash(err.message, 'error'); }
  });

  /* ---------- Read-only job details ---------- */
  const dept = dbData.departments.find(d => d.id === user.profile.department_id);
  $('p-firstname').value = user.first_name || '';
  $('p-lastname').value = user.last_name || '';
  $('p-email').value = user.email;
  $('p-job').value = user.profile.job_title || '';
  $('p-dept').value = dept ? dept.name : '';
  $('p-office').value = user.profile.office_location || '';

  /* ---------- NAS ---------- */
  if (user.dsm_username) {
    $('nas-section').hidden = false;
    $('nas-username').textContent = user.dsm_username;
  } else {
    $('no-nas-section').hidden = false;
  }

  /* ---------- Render editable state from the server ---------- */
  function render() {
    $('c-phone').value = me.profile.phone || '';
    $('c-linkedin').value = me.linkedin_url || '';
    $('c-emails').value = (me.other_emails || []).join('\n');

    $('w-show').checked = !!me.show_on_website;
    $('w-bio').value = me.profile.bio || '';
    $('w-text').value = me.profile_text || '';
    $('w-consent').checked = false;
    updateConsentBox();

    $('sync-callout').hidden = !me.sanity_pending;
    $('sync-text').textContent = me.sanity_last_error
      ? t('Your changes are saved in the portal, but the company website has not been updated yet. It will retry automatically.')
      : t('Your changes are saved. The company website will update shortly.');
  }

  // Consent is only needed when turning visibility on, not when it's already public.
  function updateConsentBox() {
    $('consent-box').hidden = !($('w-show').checked && !me.show_on_website);
  }
  $('w-show').addEventListener('change', updateConsentBox);

  // Shared save: PATCH /api/me/, then refresh local state from the response.
  async function save(body, errEl, button) {
    errEl.hidden = true;
    button.disabled = true;
    try {
      me = await api('/api/me/', { method: 'PATCH', body });
      render();
      (me.warnings || []).forEach(w => showFlash(w, 'info'));
      showFlash(t('Changes saved.'), 'success');
    } catch (err) {
      errEl.textContent = t(err.message);
      errEl.hidden = false;
    } finally {
      button.disabled = false;
    }
  }

  /* ---------- Contact form ---------- */
  $('contact-form').addEventListener('submit', e => {
    e.preventDefault();
    const err = $('contact-error');
    const emails = $('c-emails').value.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    const bad = emails.find(x => !EMAIL_RE.test(x));
    if (bad) {
      err.textContent = t(`"${bad}" is not a valid email address.`);
      err.hidden = false;
      $('c-emails').focus();
      return;
    }
    save({
      phone: $('c-phone').value.trim(),
      linkedin_url: $('c-linkedin').value.trim(),
      other_emails: emails,
    }, err, e.submitter);
  });

  /* ---------- Website form ---------- */
  $('web-form').addEventListener('submit', e => {
    e.preventDefault();
    const err = $('web-error');
    const wantOn = $('w-show').checked;
    const newlyPublishing = wantOn && !me.show_on_website;

    if (newlyPublishing && !$('w-consent').checked) {
      err.textContent = t('Please confirm consent before publishing your profile.');
      err.hidden = false;
      $('w-consent').focus();
      return;
    }

    const body = {
      show_on_website: wantOn,
      bio: $('w-bio').value.trim(),
      profile_text: $('w-text').value.trim(),
    };
    if (newlyPublishing) body.website_consent = true;
    save(body, err, e.submitter);
  });

  render();
  refreshIcons();
})();