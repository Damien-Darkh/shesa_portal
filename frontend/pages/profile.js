// My profile: contact details and website profile are editable by the employee.
// Job details are read-only (HR manages them). Publishing on the website needs explicit consent.
import { ready, dbData, showFlash, getLang, setLang, refreshIcons, renderAvatar, t } from '../layout.js';
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

  /* ---------- Website photo ---------- */
  const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
  const MAX_PHOTO = 5 * 1024 * 1024;

  function renderPhoto(url) {
    renderAvatar($('photo-preview'), { photoUrl: url, firstName: user.first_name, lastName: user.last_name });
    $('photo-remove').hidden = !url;
  }
  function photoError(msg) {
    $('photo-error').textContent = t(msg);
    $('photo-error').hidden = false;
  }

  $('photo-pick').addEventListener('click', () => $('photo-file').click());
  $('photo-file').addEventListener('change', async e => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    $('photo-error').hidden = true;
    if (!PHOTO_TYPES.includes(file.type)) return photoError('Use a JPEG, PNG or WebP image.');
    if (file.size > MAX_PHOTO) return photoError('Photo must be 5 MB or smaller.');

    const body = new FormData();
    body.append('photo', file);
    $('photo-pick').disabled = true;
    try {
      const r = await api('/api/me/photo', { method: 'POST', body });
      renderPhoto(r.photo_url);
      showFlash(t('Photo updated.'), 'success');
    } catch (err) {
      photoError(err.message);
    } finally {
      $('photo-pick').disabled = false;
    }
  });

  $('photo-remove').addEventListener('click', async () => {
    $('photo-error').hidden = true;
    try {
      await api('/api/me/photo', { method: 'DELETE' });
      renderPhoto(null);
      showFlash(t('Photo removed.'), 'success');
    } catch (err) {
      photoError(err.message);
    }
  });

  /* ---------- Projects ---------- */
  let projectCatalog = [];
  let chosen = [...(me.project_ids || [])];

  function renderProjects() {
    const titles = Object.fromEntries(projectCatalog.map(p => [p.id, p.title]));
    const available = projectCatalog.filter(p => !chosen.includes(p.id));

    const sel = $('project-select');
    const placeholder = !projectCatalog.length
      ? t('No projects found on the website')
      : available.length
        ? t('Choose a project')
        : t('No more projects to add');
    sel.replaceChildren(
      new Option(placeholder, ''),
      ...available.map(p => new Option(p.title, p.id)),
    );
    sel.disabled = !available.length;
    $('project-add').disabled = !available.length;

    const list = $('project-list');
    list.replaceChildren(...chosen.map(id => {
      const title = titles[id] || t('Unavailable project');
      const li = document.createElement('li');
      li.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:.5rem;'
        + 'padding:.5rem .75rem;border:1px solid var(--border-color);border-radius:.625rem;';
      const name = document.createElement('span');
      name.textContent = title;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn btn-outline btn-sm';
      remove.setAttribute('aria-label', `${t('Remove')} ${title}`);
      remove.innerHTML = '<i data-lucide="x"></i>';
      remove.addEventListener('click', () => {
        chosen = chosen.filter(x => x !== id);
        renderProjects();
      });
      li.append(name, remove);
      return li;
    }));
    $('project-empty').hidden = chosen.length > 0;
    refreshIcons();
  }

  $('project-add').addEventListener('click', () => {
    const id = $('project-select').value;
    if (!id || chosen.includes(id)) return;
    chosen.push(id);
    renderProjects();
    $('project-select').focus();
  });

  $('project-save').addEventListener('click', async () => {
    const err = $('project-error');
    err.hidden = true;
    const btn = $('project-save');
    btn.disabled = true;
    try {
      me = await api('/api/me/', { method: 'PATCH', body: { project_ids: chosen } });
      chosen = [...(me.project_ids || [])];
      renderProjects();
      (me.warnings || []).forEach(w => showFlash(w, 'info'));
      showFlash(t('Projects saved.'), 'success');
    } catch (ex) {
      err.textContent = t(ex.message);
      err.hidden = false;
    } finally {
      btn.disabled = false;
    }
  });

  // Initial state
  renderPhoto(me.photo_url);
  try {
    projectCatalog = (await api('/api/me/projects/')).projects;
  } catch (ex) {
    $('project-error').textContent = t(ex.message);
    $('project-error').hidden = false;
  }
  renderProjects();

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