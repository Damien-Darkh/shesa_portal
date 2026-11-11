// Shows the one-time WireGuard config and QR code for a new device, and the Windows launcher if one exists.
import { ready, dbData, showFlash, refreshIcons } from '../layout.js';

(async () => {
  if (!await ready) return;
  const $ = id => document.getElementById(id);
  const id = new URLSearchParams(location.search).get('id');
  const raw = id ? sessionStorage.getItem(`portal.device.${id}`) : null;
  if (id) sessionStorage.removeItem(`portal.device.${id}`);   // shown once, then gone from the browser

  if (!raw) {
    $('device-title').textContent = 'Configuration no longer available';
    showFlash('The setup details for this device were already shown. Disconnect it and add a new device to get a new configuration.', 'info');
    refreshIcons();
    return;
  }
  const { device, config, qr_png_base64 } = JSON.parse(raw);
  $('device-title').textContent = `Set up "${device.device_name}"`;
  $('wg-config').value = config;

  // Replace the placeholder QR graphic with the real code from the server.
  const placeholder = document.querySelector('svg[width="180"]');
  if (placeholder && qr_png_base64) {
    const img = document.createElement('img');
    img.width = 180; img.height = 180; img.alt = 'WireGuard configuration QR code';
    img.src = `data:image/png;base64,${qr_png_base64}`;
    placeholder.replaceWith(img);
  }

  $('copy-btn').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('wg-config').value); } catch { /* clipboard blocked */ }
    $('copy-text').textContent = 'Copied!';
    setTimeout(() => { $('copy-text').textContent = 'Copy config'; }, 2000);
  });

  $('launcher-card').hidden = !device.launcher_available;
  if (device.launcher_available) $('launcher-btn').href = `/api/devices/${device.id}/launcher.cmd`;
  refreshIcons();
})();
