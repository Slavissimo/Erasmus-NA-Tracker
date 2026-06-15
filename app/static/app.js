// ---- NA table filter ----
const filter = document.getElementById('filter');
if (filter) {
  const rows = Array.from(document.querySelectorAll('#agtable tbody tr'));
  filter.addEventListener('input', () => {
    const q = filter.value.toLowerCase().trim();
    rows.forEach(r => { r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none'; });
  });
}

// admin token from current URL (?admin=...), used for API calls
const ADMIN_TOKEN = new URLSearchParams(location.search).get('admin') || '';

// ---- Matrix filter via API ----
const mAction = document.getElementById('m-action');
const mRound = document.getElementById('m-round');
const mConfirmed = document.getElementById('m-confirmed');

async function refreshMatrix() {
  const params = new URLSearchParams();
  if (mAction && mAction.value) params.set('action_code', mAction.value);
  if (mRound && mRound.value) params.set('round', mRound.value);
  if (mConfirmed && mConfirmed.checked) params.set('only_confirmed', 'true');
  if (ADMIN_TOKEN) params.set('admin', ADMIN_TOKEN);
  const res = await fetch('/api/matrix?' + params.toString());
  const data = await res.json();
  const filtering = (mAction && mAction.value) || (mRound && mRound.value) || (mConfirmed && mConfirmed.checked);
  const codes = new Set(data.rows.map(r => r.code));
  document.querySelectorAll('.m-card').forEach(card => {
    if (!filtering) { card.classList.remove('hidden'); return; }
    card.classList.toggle('hidden', !codes.has(card.dataset.code));
  });
}
[mAction, mRound, mConfirmed].forEach(el => el && el.addEventListener('change', refreshMatrix));

// ---- Copy country list (for partner search) ----
const exportBtn = document.getElementById('m-export');
if (exportBtn) exportBtn.addEventListener('click', () => {
  const visible = Array.from(document.querySelectorAll('.m-card:not(.hidden):not(.empty)'))
    .map(c => c.dataset.country);
  if (!visible.length) { alert('No countries match the current filter.'); return; }
  navigator.clipboard.writeText(visible.join(', '));
  exportBtn.textContent = 'Copied: ' + visible.length + ' countries';
  setTimeout(() => exportBtn.textContent = 'Copy country list', 2000);
});

// ---- Confirm / reject findings (admin only) ----
function getToken() {
  if (ADMIN_TOKEN) return ADMIN_TOKEN;
  let t = sessionStorage.getItem('admin_token');
  if (!t) { t = prompt('Admin token:'); if (t) sessionStorage.setItem('admin_token', t); }
  return t;
}
document.querySelectorAll('.p-item').forEach(item => {
  const idx = item.dataset.idx;
  const confirmBtn = item.querySelector('.confirm');
  const rejectBtn = item.querySelector('.reject');
  if (confirmBtn) confirmBtn.addEventListener('click', async () => {
    const code = item.querySelector('.p-action-code').value;
    const round = item.querySelector('.p-round').value;
    if (!code) { alert('Select an action.'); return; }
    const token = getToken(); if (!token) return;
    const p = new URLSearchParams({ action_code: code, round, token });
    const res = await fetch(`/api/findings/${idx}/confirm?` + p, { method: 'POST' });
    if (res.ok) { item.style.opacity = .4; item.querySelector('.p-actions').innerHTML = '✓ Confirmed — refresh to update matrix'; }
    else { alert('Error: ' + (res.status === 401 ? 'invalid token' : res.status)); sessionStorage.removeItem('admin_token'); }
  });
  if (rejectBtn) rejectBtn.addEventListener('click', async () => {
    const token = getToken(); if (!token) return;
    const res = await fetch(`/api/findings/${idx}/reject?` + new URLSearchParams({ token }), { method: 'POST' });
    if (res.ok) { item.style.opacity = .3; item.querySelector('.p-actions').innerHTML = 'rejected'; }
    else { alert('Error'); sessionStorage.removeItem('admin_token'); }
  });
});

// ---- Admin login modal ----
const adminOpen = document.getElementById('admin-open');
const adminModal = document.getElementById('admin-modal');
if (adminOpen && adminModal) {
  const pass = document.getElementById('admin-pass');
  const go = document.getElementById('admin-go');
  const cancel = document.getElementById('admin-cancel');
  const open = () => { adminModal.hidden = false; pass.value = ''; pass.focus(); };
  const close = () => { adminModal.hidden = true; };
  const submit = () => {
    const v = pass.value.trim();
    if (!v) { pass.focus(); return; }
    // redirect to admin view; encode so special chars in the password survive
    location.href = '/?admin=' + encodeURIComponent(v);
  };
  adminOpen.addEventListener('click', open);
  cancel.addEventListener('click', close);
  go.addEventListener('click', submit);
  pass.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  adminModal.addEventListener('click', e => { if (e.target === adminModal) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !adminModal.hidden) close(); });
}
