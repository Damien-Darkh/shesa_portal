
// Shows the one-time WireGuard config and QR code for a new device,
// and the setup files for each OS.
import { ready, showFlash, refreshIcons } from '../layout.js';

(async () => {
  if (!await ready) return;

  const $ = id => document.getElementById(id);
  const id = new URLSearchParams(location.search).get('id');

  const raw = id
    ? sessionStorage.getItem(`portal.device.${id}`)
    : null;

  if (id) {
    sessionStorage.removeItem(`portal.device.${id}`);
  }

  if (!raw) {
    $('device-title').textContent = 'Configuration no longer available';

    showFlash(
      'The setup details for this device were already shown. Disconnect it and add a new device to get a new configuration.',
      'info'
    );

    refreshIcons();
    return;
  }

  const { device, config, qr_png_base64, wireguard_backend } = JSON.parse(raw);

  $('device-title').textContent = `Set up "${device.device_name}"`;
  $('wg-config').value = config;

  // Display the real QR code.
  const placeholder = document.querySelector('#qr-box svg');

  if (placeholder && qr_png_base64) {
    const img = document.createElement('img');

    img.width = 180;
    img.height = 180;
    img.alt = 'WireGuard configuration QR code';
    img.src = `data:image/png;base64,${qr_png_base64}`;

    placeholder.replaceWith(img);
  }

  // Copy configuration.
  $('copy-btn').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('wg-config').value);
      $('copy-text').textContent = 'Copied!';
    } catch {
      showFlash('Unable to copy automatically. Please select and copy the configuration manually.', 'error');
    }

    setTimeout(() => {
      $('copy-text').textContent = 'Copy config';
    }, 2000);
  });

  // Determine backend.
  const backend = String(wireguard_backend || device.wireguard_backend || '')
    .toLowerCase();

  // Mock backend: show all launchers.
  // Other backends: respect availability reported by the server.
  const isMock = backend === 'mock';

  const showLauncher = isMock || !!device.launcher_available;

  $('launcher-card').hidden = !showLauncher;

  if (showLauncher) {
    const base = `/api/devices/${device.id}`;

    // Windows
    $('launcher-win').href = `${base}/launcher.cmd`;
    $('launcher-win').hidden = false;

    // macOS and Linux
    if (isMock || device.unix_launcher_available) {
      $('launcher-mac').href = `${base}/launcher.command`;
      $('launcher-mac').hidden = false;

      $('launcher-linux').href = `${base}/launcher.sh`;
      $('launcher-linux').hidden = false;
    }
  }

  refreshIcons();
})();
