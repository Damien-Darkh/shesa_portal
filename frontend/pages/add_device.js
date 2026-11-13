// Create a VPN device for the signed-in user. Only reachable when VPN access is enabled for the account.
import { ready, dbData, showFlash, refreshIcons } from '../layout.js';
import { api } from '../api.js';

(async () => {
  if (!await ready) return;
  if (!dbData.currentUser.can_use_vpn) {
    sessionStorage.setItem('portal.flash', 'VPN access is not enabled for your account. Contact IT.');
    location.replace('index.html');
    return;
  }
  refreshIcons();
  document.getElementById('add-device-form').addEventListener('submit', async e => {
    e.preventDefault();
    const name = document.getElementById('device-name').value.trim();
    try {
      const r = await api('/api/devices/create', { method: 'POST', body: { device_name: name } });
      sessionStorage.setItem(`portal.device.${r.device.id}`, JSON.stringify(r));
      location.href = `device_created.html?id=${r.device.id}`;
    } catch (err) { showFlash(err.message, 'error'); }
  });
})();