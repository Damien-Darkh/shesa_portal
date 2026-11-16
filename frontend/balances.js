// balances.js - leave balance table and editor, shared by the admin employee pages.
// Admins edit the yearly allowance (accrued) and carryover per leave type. The server recalculates "remaining".
import { api } from './api.js';
import { promptDialog, showFlash, refreshIcons, esc, t } from './layout.js';

const LABEL = { vacation: 'Vacation', sick: 'Sick', personal: 'Personal' };
const HALF_DAY_OK = v => Number.isFinite(v) && v >= 0 && (v * 2) % 1 === 0;

/**
 * Renders balance rows into a <tbody>. Each row has an Edit button.
 * onSaved() runs after a successful save, so the caller can reload its data.
 */
export function renderBalanceTable(tbody, balances, userId, onSaved) {
  tbody.innerHTML = balances.map(b => `<tr>
      <td>${esc(t(LABEL[b.leave_type] || b.leave_type))}</td>
      <td>${b.accrued_days}</td>
      <td>${b.carryover_days}</td>
      <td>${b.used_days}</td>
      <td>${b.pending_days}</td>
      <td><strong>${b.available_days}</strong></td>
      <td><button type="button" class="btn btn-outline btn-sm"
            data-type="${esc(b.leave_type)}" data-year="${b.year}"
            data-accrued="${b.accrued_days}" data-carry="${b.carryover_days}">
          <i data-lucide="pencil"></i> ${t('Edit')}</button></td>
    </tr>`).join('');
  refreshIcons();

  // Assigned (not addEventListener) so re-rendering never stacks handlers.
  tbody.onclick = async e => {
    const btn = e.target.closest('button[data-type]');
    if (!btn) return;
    const type = btn.dataset.type, year = Number(btn.dataset.year);
    const name = t(LABEL[type] || type);

    const accruedIn = await promptDialog({
      title: `${name} allowance ${year}`,
      message: 'Total days for the year, before carryover. Use multiples of 0.5.',
      label: 'Allowance (days)', placeholder: btn.dataset.accrued,
    });
    if (accruedIn === null || accruedIn === '') return;

    const carryIn = await promptDialog({
      title: `${name} carryover ${year}`,
      message: 'Days carried over from the previous year. Enter 0 if none.',
      label: 'Carryover (days)', placeholder: btn.dataset.carry,
    });
    if (carryIn === null) return;

    const accrued = Number(accruedIn), carry = carryIn === '' ? 0 : Number(carryIn);
    if (!HALF_DAY_OK(accrued) || !HALF_DAY_OK(carry)) {
      showFlash(t('Enter a non-negative number in steps of 0.5.'), 'error');
      return;
    }

    try {
      await api(`/api/admin/users/${userId}/leave-balances`, {
        method: 'PUT',
        body: { year, leave_type: type, accrued_days: accrued, carryover_days: carry },
      });
      showFlash(`${name} balance updated.`, 'success');
      if (onSaved) await onSaved();
    } catch (err) {
      showFlash(err.message, 'error');
    }
  };
}