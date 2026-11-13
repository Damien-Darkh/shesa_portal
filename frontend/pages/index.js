// Dashboard: profile card, notifications (marked read after 2s on screen), own VPN devices (if entitled).
import { ready, dbData, markNotificationsRead, refreshIcons, showFlash, confirmDialog, fmtDate, renderAvatar, getUnreadCount, updateNotificationBadge, t } from '../layout.js';
import { api } from '../api.js';
import { refreshMe } from '../store.js';

(async () => {
  if (!await ready) return;
  const $ = id => document.getElementById(id);
  const user = dbData.currentUser;

  // Show any message left by a redirect (e.g. from add_device.js).
  const flash = sessionStorage.getItem('portal.flash');
  if (flash) { sessionStorage.removeItem('portal.flash'); showFlash(flash, 'info'); }

  $('welcome-title').textContent = `Welcome back, ${user.first_name}`;
  $('profile-fullname').textContent = `${user.first_name} ${user.last_name}`;
  $('profile-job').textContent = user.profile.job_title || '';
  $('profile-id').textContent = `User ID: ${user.id}`;
  $('profile-role-badge').textContent = user.is_admin ? 'ADMIN' : 'STAFF';
  $('p-email').textContent = user.email;
  $('p-phone').textContent = user.profile.phone || '—';
  $('p-office').textContent = user.profile.office_location || '—';
  $('p-start').textContent = user.profile.start_date ? fmtDate(user.profile.start_date) : '—';
  $('p-bio').textContent = user.profile.bio || '—';
  renderAvatar(document.querySelector('.avatar-box'), {
    photoUrl: user.profile.photo_url, firstName: user.first_name, lastName: user.last_name,
  });

  /* Notifications */
  const notifList = $('notifications-list'), countBadge = $('unread-count');
  function renderNotifications() {
    const list = dbData.notifications;
    notifList.replaceChildren();
    if (!list.length) { notifList.innerHTML = `<p class="card-subtitle">${t('No notifications.')}</p>`; }
    list.forEach(n => {
      const row = document.createElement('div');
      row.className = 'detail-item';
      row.style.cssText = 'border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem;';
      const box = document.createElement('div');
      const title = document.createElement('p'); title.className = 'value';
      title.textContent = n.title;
      if (!n.is_read) { const b = document.createElement('span'); b.className = 'badge badge-inline'; b.textContent = t('New'); title.append(' ', b); }
      const msg = document.createElement('p'); msg.className = 'card-subtitle'; msg.textContent = n.message;
      box.append(title, msg); row.append(box); notifList.append(row);
    });
    const unread = getUnreadCount();
    countBadge.textContent = unread; countBadge.hidden = !unread;
    refreshIcons();
  }
  renderNotifications();
  if (getUnreadCount()) {
    let timer;
    const seen = new IntersectionObserver(([entry]) => {
      clearTimeout(timer);
      if (entry.isIntersecting) timer = setTimeout(async () => {
        seen.disconnect();
        await markNotificationsRead();
        renderNotifications(); updateNotificationBadge();
      }, 2000);
    }, { threshold: 0.6 });
    seen.observe(notifList.closest('.card'));
  }

  /* VPN devices: the section exists only for entitled users (admins always are). */
  const vpnAllowed = !!user.can_use_vpn;
  $('vpn-section').hidden = !vpnAllowed;

  async function changed(message) {
    await refreshMe();
    renderDevices();
    if (message) showFlash(message, 'success');
  }
  function renderDevices() {
    if (!vpnAllowed) return;
    const tbody = $('devices-tbody');
    const devices = dbData.currentUser.devices || [];
    tbody.replaceChildren();
    if (!devices.length) {
      const tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 5;
      td.innerHTML = `<div class="empty-state"><i data-lucide="inbox"></i><span>${t('No devices yet — add one above to get connected.')}</span></div>`;
      tr.append(td); tbody.append(tr); refreshIcons(); return;
    }
    devices.forEach(d => {
      const tr = document.createElement('tr');
      const tdName = document.createElement('td'); tdName.textContent = d.device_name;
      const tdAddr = document.createElement('td'); tdAddr.className = 'mono'; tdAddr.textContent = d.wg_address;
      const tdDate = document.createElement('td'); tdDate.textContent = fmtDate(d.created_at);
      const tdStatus = document.createElement('td');
      const pill = document.createElement('span');
      pill.className = 'status ' + (d.is_revoked ? 'status--off' : 'status--active');
      pill.append(Object.assign(document.createElement('span'), { className: 'pulse' }), document.createTextNode(d.is_revoked ? t('Disconnected') : t('Active')));
      tdStatus.append(pill);

      const tdActions = document.createElement('td');
      const actions = document.createElement('div'); actions.className = 'btn-row';
      if (!d.is_revoked) {
        const btn = document.createElement('button'); btn.type = 'button';
        btn.className = 'btn btn-red btn-sm'; btn.innerHTML = `<i data-lucide="power"></i> ${t('Disconnect')}`;
        btn.addEventListener('click', async () => {
          if (!await confirmDialog({ title: t('Disconnect device?'), message: `Disconnect ${d.device_name}? This device will lose VPN access immediately.`, confirmText: t('Disconnect'), danger: true })) return;
          try { await api(`/api/devices/${d.id}/revoke`, { method: 'POST' }); await changed(`'${d.device_name}' has been disconnected.`); }
          catch (err) { showFlash(err.message, 'error'); }
        });
        actions.append(btn);
      } else if (!d.auto_revoked) {
        const btn = document.createElement('button'); btn.type = 'button';
        btn.className = 'btn btn-outline btn-sm'; btn.innerHTML = `<i data-lucide="refresh-ccw"></i> ${t('Reconnect')}`;
        btn.addEventListener('click', async () => {
          try { await api(`/api/devices/${d.id}/reconnect`, { method: 'POST' }); await changed(`'${d.device_name}' has been reconnected.`); }
          catch (err) { showFlash(err.message, 'error'); }
        });
        actions.append(btn);
      }
      if (d.launcher_available) {
        const a = document.createElement('a');
        a.href = `/api/devices/${d.id}/launcher.cmd`;
        a.setAttribute('download', 'Connect Company Network.cmd');
        a.className = 'btn btn-outline btn-sm';
        a.innerHTML = `<i data-lucide="download"></i> ${t('Windows setup file')}`;
        actions.append(a);
      }
      tdActions.append(actions);
      tr.append(tdName, tdAddr, tdDate, tdStatus, tdActions);
      tbody.append(tr);
    });
    refreshIcons();
  }
  renderDevices();
  refreshIcons();
})();
