// Directory: searchable list of active colleagues, filterable by department. Search text is read from ?q=.
import { ready, dbData, refreshIcons, esc, t } from '../layout.js';

(async () => {
  if (!await ready) return;
  const searchInput = document.getElementById('search-input');
  const dirGrid = document.getElementById('directory-grid');
  const deptSel = document.getElementById('dept-filter');

  function render(query = '') {
    const q = query.trim().toLowerCase();
    const filtered = dbData.usersDirectory.filter(u => !u.disabled
      && (!deptSel.value || String(u.profile.department_id) === deptSel.value)
      && (`${u.first_name} ${u.last_name}`.toLowerCase().includes(q)
        || u.email.toLowerCase().includes(q)
        || (u.profile.job_title || '').toLowerCase().includes(q)));

    dirGrid.innerHTML = !filtered.length
      ? `<p class="card-subtitle" role="status">${esc(t('No results found.'))}</p>`
      : filtered.map(u => `
        <a class="detail-item person-card" href="person.html?id=${u.id}" style="text-decoration:none;color:inherit;padding: 1rem; border: 1px solid var(--border-color); border-radius: 0.75rem;">
          <div class="avatar-box" style="width: 2.5rem; height: 2.5rem; font-size: 1rem;">${esc((u.first_name || '')[0] || '')}${esc((u.last_name || '')[0] || '')}</div>
          <div>
            <p class="value">${esc(u.first_name)} ${esc(u.last_name)}</p>
            <p class="label">${esc(u.profile.job_title || '')}</p>
            <p class="form-hint">${esc(u.email)}</p>
          </div>
        </a>`).join('');
    refreshIcons();
  }

  dbData.departments.forEach(d => deptSel.add(new Option(d.name, d.id)));
  deptSel.addEventListener('change', () => render(searchInput.value));
  searchInput.addEventListener('input', e => render(e.target.value));
  searchInput.value = new URLSearchParams(location.search).get('q') || '';
  render(searchInput.value);
})();
