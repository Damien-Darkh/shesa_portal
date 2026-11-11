// Create a VPN device for the signed-in user. The server returns the WireGuard config once; it is handed to
// device_created.html through sessionStorage and removed there.
import { ready, showFlash, refreshIcons } from '../layout.js';
import { api } from '../api.js';

(async () => {
  if (!await ready) return;
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
