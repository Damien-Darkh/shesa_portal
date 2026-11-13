// api.js - the only place that talks to the Django JSON API. Same origin, so the session cookie is sent
// automatically; writes send the CSRF token. Expired sessions go to /login; a pending NAS password change
// goes to force_password_change.html (the server enforces this too).

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

const cookie = name => {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : '';
};

let csrfReady = null;
const ensureCsrf = () => (csrfReady ??= fetch('/api/csrf/', { credentials: 'same-origin' }).catch(() => {}));

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { Accept: 'application/json' };
  if (method !== 'GET' && method !== 'HEAD') {
    await ensureCsrf();
    headers['X-CSRFToken'] = cookie('csrftoken');
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';

  const res = await fetch(path, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }

  if (res.status === 401) {
    if (!location.pathname.endsWith('/login')) location.href = '/login';
    throw new ApiError(401, 'Sign-in required', data);
  }
  if (res.status === 403 && data?.code === 'password_change_required') {
    if (!location.pathname.endsWith('force_password_change.html')) location.href = '/force_password_change.html';
    throw new ApiError(403, data.error, data);
  }
  if (!res.ok) throw new ApiError(res.status, data?.error || `Request failed (${res.status})`, data);
  return data;
}
