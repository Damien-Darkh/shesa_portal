// Admin panel: employees, leave approvals, leave calendar, departments. Decisions go through the API.
import { ready, dbData, requireAdmin, renderAvatar, esc, fullName, getUserById, decideLeave, showFlash, refreshIcons, trapFocus, fmtDate, getLang, promptDialog, departmentDialog, descendantIds, updateLeaveBadge } from '../layout.js';
import { api, ApiError } from '../api.js';

(async () => {
  if (!await ready) return;
  if (!requireAdmin()) return;
  const me = dbData.currentUser;
  const $ = id => document.getElementById(id);
  const users = (dbData.usersDirectory || []).filter(u =>
    (u.email || '').trim().toLowerCase() !== 'admin@shesa.local'
  );
  const kind = s => s === 'PENDING' ? 'pending' : s === 'DENIED' ? 'denied' : s === 'CANCELLED' ? 'cancelled' : 'approved';
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const label = { pending: 'Pending', denied: 'Denied', approved: 'Approved', cancelled: 'Cancelled' };

  /* ---------- Employees ---------- */
  function renderEmployees() {
    const tbody = $('users-tbody');
    tbody.replaceChildren();

    if (!users.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.innerHTML = '<div class="empty-state"><i data-lucide="inbox"></i><span>No employees yet. Add one to get started.</span></div>';
      tr.append(td);
      tbody.append(tr);
      refreshIcons();
      return;
    }

    users.forEach(u => {
      const tr = document.createElement('tr');
      tr.dataset.href = `person.html?id=${u.id}`;
      tr.style.cursor = 'pointer';

      // Name, avatar and job title
      const tdName = document.createElement('td');
      const wrap = document.createElement('div');
      wrap.className = 'name-cell';

      const avatar = document.createElement('div');
      avatar.className = 'avatar-box avatar-sm';
      renderAvatar(avatar, {
        photoUrl: u.profile?.photo_url,
        firstName: u.first_name,
        lastName: u.last_name,
      });

      const text = document.createElement('div');
      const nameLine = document.createElement('div');
      const nameLink = document.createElement('a');
      nameLink.href = `person.html?id=${u.id}`;
      nameLink.textContent = (u.first_name || u.last_name) ? fullName(u) : '—';
      nameLine.append(nameLink);

      const job = document.createElement('div');
      job.className = 'form-hint';
      job.style.margin = '0';
      job.textContent = u.profile?.job_title || '';

      text.append(nameLine, job);
      wrap.append(avatar, text);
      tdName.append(wrap);

      // Identity ID (permanent, shown for recognition)
      const tdId = document.createElement('td');
      tdId.className = 'mono';
      tdId.textContent = u.identity_id || '—';

      // Email
      const tdEmail = document.createElement('td');
      tdEmail.textContent = u.email;

      // Role
      const tdRole = document.createElement('td');
      tdRole.innerHTML = `<span class="status ${u.is_admin ? 'status--admin' : 'status--staff'}">${u.is_admin ? 'Admin' : 'Staff'}</span>`;

      // Devices
      const tdDev = document.createElement('td');
      tdDev.textContent = `${u.device_count ?? 0} active`;

      // Status
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = `<span class="status ${u.disabled ? 'status--off' : 'status--active'}"><span class="pulse"></span>${u.disabled ? 'Disabled' : 'Active'}</span>`;

      tr.append(tdName, tdId, tdEmail, tdRole, tdDev, tdStatus);
      tbody.append(tr);
    });

    refreshIcons();
  }
  $('users-tbody').addEventListener('click', e => {
    const row = e.target.closest('tr[data-href]');
    if (row && !e.target.closest('a')) location.href = row.dataset.href;
  });

  /* ---------- Leave approvals ---------- */
  let filter = 'pending';
  function renderLeave() {
    const rows = dbData.leaveRequests.filter(r => filter === 'all' || r.status === 'PENDING')
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    $('leave-tbody').innerHTML = rows.length ? rows.map(r => {
      const k = kind(r.status), own = r.user_id === me.id;
      const actions = k !== 'pending' ? '' : own ? '<span class="form-hint">Your own request</span>'
        : `<div class="btn-row">
            <button type="button" class="btn btn-sm btn-primary" style="margin-top:0;width:auto;" data-act="approve" data-id="${r.id}"><i data-lucide="check"></i> Approve</button>
            <button type="button" class="btn btn-sm btn-red" data-act="deny" data-id="${r.id}"><i data-lucide="x"></i> Deny</button></div>`;
      const name = fullName(getUserById(r.user_id) || { email: '' });
      return `<tr><td>${esc(name)}</td><td>${esc(cap(r.leave_type))}</td>
        <td>${fmtDate(r.start_date)} &rarr; ${fmtDate(r.end_date)}</td><td>${r.days_requested}</td>
        <td style="white-space:normal;min-width:10rem;">${esc(r.reason || '')}${k === 'denied' && r.approver_comment ? `<div class="form-hint">Denied: ${esc(r.approver_comment)}</div>` : ''}</td>
        <td><span class="status status--${k}">${label[k]}</span></td><td>${actions}</td></tr>`;
    }).join('') : `<tr><td colspan="7"><div class="empty-state"><i data-lucide="inbox"></i><span>${filter === 'pending' ? 'No pending requests.' : 'No requests yet.'}</span></div></td></tr>`;
    refreshIcons();
  }
  $('leave-tbody').addEventListener('click', async e => {
    const btn = e.target.closest('button[data-act]'); if (!btn) return;
    const r = dbData.leaveRequests.find(x => x.id === Number(btn.dataset.id));
    const approve = btn.dataset.act === 'approve';
    const comment = approve ? '' : await promptDialog({ title: 'Deny this request?', message: 'You can add a reason for the employee.', label: 'Reason (optional)', confirmText: 'Deny', danger: true });
    if (comment === null) return;
    try {
      await decideLeave(r.id, approve ? 'APPROVED' : 'DENIED', comment || null);
      showFlash(`${approve ? 'Approved' : 'Denied'} ${fullName(getUserById(r.user_id))}'s request.`, approve ? 'success' : 'info');
      renderLeave(); cal && cal.refetchEvents();
    } catch (error) { showFlash(error.message, 'error'); }
  });
  document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => {
    filter = b.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(x => { x.classList.toggle('btn-primary', x === b); x.classList.toggle('btn-outline', x !== b); });
    renderLeave();
  }));

  /* ---------- Leave calendar (events come from the API; sick leave is shown to admins) ---------- */
  const palette = ['#0099e6', '#7c3aed', '#d97706', '#059669', '#dc2626', '#db2777', '#0f766e', '#4f46e5'];
  const colorOf = id => palette[(id - 1) % palette.length];
  const addDay = s => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10); };
  users.forEach(u => $('cal-employee').add(new Option(fullName(u), u.id)));
  $('cal-legend').innerHTML = users.map(u => `<span class="legend-item"><i style="background:${colorOf(u.id)}"></i>${esc(fullName(u))}</span>`).join('')
    + '<span class="legend-item"><i style="background:#64748b"></i>Approved (solid)</span><span class="legend-item"><i class="dashed"></i>Pending (dashed)</span>';

  let cal;
  async function calendarEvents(info, ok, fail) {
    try {
      const { events } = await api(`/api/pto/calendar/?start=${info.startStr.slice(0, 10)}&end=${info.endStr.slice(0, 10)}`);
      ok(events
        .filter(ev => (ev.status === 'APPROVED' || $('cal-pending').checked) && (!$('cal-employee').value || String(ev.user_id) === $('cal-employee').value))
        .map(ev => ({ id: ev.id, title: `${ev.user_name} · ${cap(ev.leave_type || 'vacation')}`, start: ev.start_date, end: addDay(ev.end_date), allDay: true,
          backgroundColor: colorOf(ev.user_id), borderColor: colorOf(ev.user_id), classNames: ev.status === 'PENDING' ? ['fc-pending'] : [],
          extendedProps: { ev } })));
    } catch (error) { fail(error); }
  }
  function renderCalendar() {
    if (typeof FullCalendar === 'undefined') {
      $('calendar').innerHTML = '<div class="callout callout--warning" role="alert"><i data-lucide="triangle-alert"></i><div><strong>The calendar could not be loaded.</strong> Check your connection and <button type="button" class="btn btn-sm btn-outline" onclick="location.reload()">try again</button></div></div>';
      return refreshIcons();
    }
    if (cal) return cal.updateSize();
    const today = new Date().toISOString().slice(0, 10);
    cal = new FullCalendar.Calendar($('calendar'), {
      locale: getLang(), firstDay: 1,
      initialView: window.innerWidth < 640 ? 'listMonth' : 'dayGridMonth',
      initialDate: today,
      headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,listMonth' },
      height: 'auto', dayMaxEvents: 3,
      events: calendarEvents,
      eventClick: ({ event }) => openLeave(event.extendedProps.ev),
    });
    cal.render();
  }
  $('cal-employee').addEventListener('change', () => cal && cal.refetchEvents());
  $('cal-pending').addEventListener('change', () => cal && cal.refetchEvents());

  /* ---------- Leave details pop-up ---------- */
  const modal = $('leave-modal');
  let lastFocus = null;
  function openLeave(ev) {
    const k = kind(ev.status), row = (l, v) => `<div class="detail-item"><div><p class="label">${l}</p><p class="value">${v}</p></div></div>`;
    $('lm-title').textContent = ev.user_name;
    $('lm-sub').textContent = ev.leave_type ? `${cap(ev.leave_type)} leave` : 'Leave';
    $('lm-status').innerHTML = `<span class="status status--${k}">${label[k]}</span>`;
    const full = dbData.leaveRequests.find(r => r.id === ev.id);
    $('lm-body').innerHTML = row('Dates', `${fmtDate(ev.start_date)} &rarr; ${fmtDate(ev.end_date)}`)
      + (full ? row('Duration', `${full.days_requested} day${full.days_requested > 1 ? 's' : ''}`) : '')
      + (full?.reason ? row('Reason', esc(full.reason)) : '')
      + (full && k === 'denied' && full.approver_comment ? row('Decision note', esc(full.approver_comment)) : '');
    lastFocus = document.activeElement;
    modal.classList.remove('hidden'); document.body.style.overflow = 'hidden';
    $('lm-close').focus();
  }
  function closeLeave() {
    modal.classList.add('hidden'); document.body.style.overflow = '';
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $('lm-close').addEventListener('click', closeLeave);
  modal.addEventListener('click', e => { if (e.target === modal) closeLeave(); });
  modal.addEventListener('keydown', e => trapFocus(modal, e));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeLeave(); });

  /* ---------- Departments ---------- */
  const deptById = id => dbData.departments.find(d => d.id === id);
  function renderDepartments() {
    const active = id => users.filter(u => !u.disabled && u.profile?.department_id === id).length;
    $('dept-tbody').innerHTML = dbData.departments.map(d => {
      const m = getUserById(d.manager_id), direct = active(d.id), total = direct + [...descendantIds(d.id)].reduce((sum, c) => sum + active(c), 0);
      return `<tr data-href="admin_department.html?id=${d.id}" style="cursor:pointer;">
        <td><a href="admin_department.html?id=${d.id}">${esc(d.name)}</a></td><td style="white-space:normal;min-width:10rem;">${esc(d.description || '')}</td>
        <td>${d.parent_id && deptById(d.parent_id) ? esc(deptById(d.parent_id).name) : '—'}</td><td>${m ? esc(fullName(m)) : '—'}</td>
        <td>${total}${total !== direct ? ` <span class="form-hint" style="display:inline;margin:0;">(${direct} direct)</span>` : ''}</td></tr>`;
    }).join('');
  }
  $('d-add').addEventListener('click', async () => { if (await departmentDialog()) renderDepartments(); $('d-add').focus(); });
  $('dept-tbody').addEventListener('click', e => {
    const row = e.target.closest('tr[data-href]');
    if (row && !e.target.closest('a')) location.href = row.dataset.href;
  });

  /* ---------- Tabs (#employees | #leave | #calendar | #departments) ---------- */
  const names = ['employees', 'leave', 'calendar', 'departments'];
  const tabEls = () => [...document.querySelectorAll('.tab')];
  function show(name, focus = false) {
    if (!names.includes(name)) name = 'employees';
    names.forEach(n => { $('panel-' + n).hidden = n !== name; });
    tabEls().forEach(tb => { const on = tb.dataset.tab === name; tb.setAttribute('aria-selected', String(on)); tb.tabIndex = on ? 0 : -1; if (on && focus) tb.focus(); });
    if (name === 'calendar') renderCalendar();
    if (location.hash.slice(1) !== name) history.replaceState(null, '', '#' + name);
  }
  tabEls().forEach(tb => tb.addEventListener('click', () => show(tb.dataset.tab)));
  $('admin-tabs').addEventListener('keydown', e => {
    const tabs = tabEls(), i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    const to = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault(); show(tabs[to].dataset.tab, true);
  });
  window.addEventListener('hashchange', () => show(location.hash.slice(1)));

  renderEmployees(); renderLeave(); renderDepartments(); updateLeaveBadge();
  show(location.hash.slice(1));
  refreshIcons();
})();
