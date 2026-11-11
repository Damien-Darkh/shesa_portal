// store.js - the in-memory state every page reads (same shape as the former mock data.js).
// It is filled from the API at page load and refreshed after changes. Nothing is persisted in the browser.
import { api } from './api.js';

export const dbData = {
  currentUser: null,
  usersDirectory: [],
  departments: [],
  leaveRequests: [],
  leaveBalances: [],
  notifications: [],
  timeAttendance: [],
  onboardingTasks: [],
};

const mapDevice = d => ({ ...d, user_id: d.owner_id, is_revoked: !!d.is_revoked, launcher_available: !!d.launcher_available });

export async function refreshMe() {
  const me = await api('/api/me/');
  const devices = (await api('/api/devices/')).devices.filter(d => d.owner_id === me.id).map(mapDevice);
  dbData.currentUser = {
    id: me.id, email: me.email, first_name: me.first_name, last_name: me.last_name,
    is_admin: me.is_admin, disabled: me.disabled, language: me.language,
    dsm_username: me.dsm_username, dsm_must_change_password: me.dsm_must_change_password,
    roles: (me.roles || []).map(name => ({ name })), profile: me.profile, devices,
  };
  try { localStorage.setItem('portal.lang', me.language || 'it'); } catch { /* storage unavailable */ }
  return dbData.currentUser;
}

export async function refreshPeople() {
  const { people } = await api('/api/people/');
  dbData.usersDirectory = people.map(p => ({ devices: [], ...p, profile: p.profile || {} }));
  return dbData.usersDirectory;
}

export async function refreshDepartments() {
  dbData.departments = (await api('/api/departments/')).departments;
  return dbData.departments;
}

export async function refreshLeave() {
  const path = dbData.currentUser?.is_admin ? '/api/pto/requests/?scope=team' : '/api/pto/requests/';
  dbData.leaveRequests = (await api(path)).requests;
  return dbData.leaveRequests;
}

export async function refreshBalances() {
  const { balances } = await api('/api/pto/balances/');
  dbData.leaveBalances = balances.map(b => ({ ...b, user_id: dbData.currentUser?.id }));
  return dbData.leaveBalances;
}

export async function refreshNotifications() {
  const { notifications } = await api('/api/notifications/');
  dbData.notifications = notifications.map(n => ({ ...n, notification_type: n.type }));
  return dbData.notifications;
}

/** Loads everything the shell and most pages need. Throws if the session is missing (api() redirects to /login). */
export async function loadSession() {
  await refreshMe();
  await Promise.all([refreshPeople(), refreshDepartments(), refreshLeave(), refreshBalances(), refreshNotifications()]);
  return dbData;
}
