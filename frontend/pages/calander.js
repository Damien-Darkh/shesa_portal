// Employee leave calendar. Own leave shows its type; colleagues' approved leave shows only "Away".
// Events come from /api/pto/calendar/ for the visible range.
import { ready, dbData, esc, fullName, fmtDate, getLang, submitLeave, cancelLeave, confirmDialog, trapFocus, showFlash, refreshIcons, t } from '../layout.js';
import { api, ApiError } from '../api.js';

(async () => {
  if (!await ready) return;
  const $ = id => document.getElementById(id), me = dbData.currentUser, modal = $('leave-modal');
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const kind = s => ({ PENDING: 'pending', DENIED: 'denied', CANCELLED: 'cancelled' }[s] || 'approved');
  const label = { pending: 'Pending', denied: 'Denied', approved: 'Approved', cancelled: 'Cancelled' };
  const typeColor = { vacation: '#005f94', sick: '#b91c1c', personal: '#6d28d9' }, OTHERS = '#475569';
  const addDay = (s, n = 1) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const mine = () => dbData.leaveRequests.filter(r => r.user_id === me.id);
  const businessDays = (a, b) => { let n = 0; for (let d = new Date(a + 'T00:00:00Z'); d <= new Date(b + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1)) { const w = d.getUTCDay(); if (w && w !== 6) n++; } return n; };

  $('legend').innerHTML = Object.entries(typeColor).map(([k, c]) => `<span class="legend-item"><i style="background:${c}"></i>${cap(k)}</span>`).join('')
    + `<span class="legend-item"><i style="background:${OTHERS}"></i>Colleagues (approved)</span><span class="legend-item"><i class="dashed"></i>Pending (dashed)</span>`;

  let cal;
  async function events(info, ok, fail) {
    try {
      const { events: list } = await api(`/api/pto/calendar/?start=${info.startStr.slice(0, 10)}&end=${info.endStr.slice(0, 10)}`);
      ok(list.map(ev => {
        const c = ev.own ? typeColor[ev.leave_type] || typeColor.vacation : OTHERS;
        const title = ev.own ? cap(ev.leave_type) : `${ev.user_name} · ${t('Away')}`;
        return { id: ev.id, title, start: ev.start_date, end: addDay(ev.end_date), allDay: true, backgroundColor: c, borderColor: c,
          classNames: ev.status === 'PENDING' ? ['fc-pending'] : [] };
      }));
    } catch (error) { fail(error); }
  }
  function renderCalendar() {
    if (typeof FullCalendar === 'undefined') {
      $('calendar').innerHTML = '<div class="callout callout--warning" role="alert"><i data-lucide="triangle-alert"></i><div><strong>The calendar could not be loaded.</strong> Check your connection and <button type="button" class="btn btn-sm btn-outline" onclick="location.reload()">try again</button></div></div>';
      return refreshIcons();
    }
    cal = new FullCalendar.Calendar($('calendar'), {
      locale: getLang(), firstDay: 1, height: 'auto', dayMaxEvents: 3, selectable: true,
      initialView: window.innerWidth < 640 ? 'listMonth' : 'dayGridMonth',
      headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,listMonth' },
      events,
      select: info => openModal(info.startStr.slice(0, 10), addDay(info.endStr.slice(0, 10), -1)),
    });
    cal.render();
  }

  /* request modal: focus trapped, Esc / backdrop / Cancel close it */
  let lastFocus = null;
  function openModal(start, end) {
    const today = new Date().toISOString().slice(0, 10);
    $('l-start').value = start || today; $('l-end').value = end || start || today; $('l-end').min = $('l-start').value;
    $('l-error').hidden = true; lastFocus = document.activeElement;
    modal.classList.remove('hidden'); document.body.style.overflow = 'hidden'; $('l-type').focus();
  }
  function closeModal() {
    modal.classList.add('hidden'); document.body.style.overflow = ''; $('leave-form').reset();
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $('open-request').addEventListener('click', () => openModal());
  $('l-cancel').addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  modal.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); else trapFocus(modal, e); });
  $('l-start').addEventListener('change', () => { $('l-end').min = $('l-start').value; });

  $('leave-form').addEventListener('submit', async e => {
    e.preventDefault();
    const s = $('l-start').value, en = $('l-end').value, err = $('l-error');
    const fail = (m, f) => { err.textContent = t(m); err.hidden = false; $(f).focus(); };
    if (!s || !en) return fail('Choose both dates.', s ? 'l-end' : 'l-start');
    if (en < s) return fail("The end date can't be before the start date.", 'l-end');
    const days = businessDays(s, en);
    if (!days) return fail('Your selection only includes weekends.', 'l-start');
    if (mine().some(r => ['PENDING', 'APPROVED'].includes(r.status) && s <= r.end_date && en >= r.start_date)) return fail('This overlaps another request of yours.', 'l-start');
    try {
      await submitLeave({ leave_type: $('l-type').value, start_date: s, end_date: en, days_requested: days, reason: $('l-notes').value.trim() });
      closeModal(); renderMine(); cal && cal.refetchEvents();
      showFlash('Leave request submitted.', 'success');
    } catch (error) { fail(error.message, 'l-start'); }
  });

  /* my requests */
  function renderMine() {
    const rows = mine().sort((a, b) => b.created_at.localeCompare(a.created_at));
    $('my-tbody').innerHTML = rows.length ? rows.map(r => { const k = kind(r.status); return `<tr>
      <td>${esc(cap(r.leave_type))}</td><td>${fmtDate(r.start_date)} &rarr; ${fmtDate(r.end_date)}</td><td>${r.days_requested}</td>
      <td><span class="status status--${k}">${label[k]}</span></td>
      <td>${k === 'pending' ? `<button type="button" class="btn btn-outline btn-sm" data-cancel="${r.id}">Cancel request</button>` : ''}</td></tr>`; }).join('')
      : '<tr><td colspan="5"><div class="empty-state"><i data-lucide="inbox"></i><span>You haven\'t requested any leave yet.</span></div></td></tr>';
    refreshIcons();
  }
  $('my-tbody').addEventListener('click', async e => {
    const b = e.target.closest('button[data-cancel]'); if (!b) return;
    if (!await confirmDialog({ title: 'Cancel this request?', message: 'This withdraws your pending request. You can submit a new one at any time.', confirmText: 'Cancel request', cancelText: 'Keep request', danger: true })) return;
    try { await cancelLeave(Number(b.dataset.cancel)); renderMine(); cal && cal.refetchEvents(); showFlash('Request cancelled.', 'info'); }
    catch (error) { showFlash(error.message, 'error'); }
  });

  renderCalendar(); renderMine(); refreshIcons();
})();
