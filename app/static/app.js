// ---- Filter tabuľky NA ----
const filter = document.getElementById('filter');
if (filter) {
  const rows = Array.from(document.querySelectorAll('#agtable tbody tr'));
  filter.addEventListener('input', () => {
    const q = filter.value.toLowerCase().trim();
    rows.forEach(r => { r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none'; });
  });
}

// ---- Matica: filter cez API ----
const mAction = document.getElementById('m-action');
const mRound = document.getElementById('m-round');
const mConfirmed = document.getElementById('m-confirmed');
const mGrid = document.getElementById('matrix-result');

async function refreshMatrix() {
  const params = new URLSearchParams();
  if (mAction.value) params.set('action_code', mAction.value);
  if (mRound.value) params.set('round', mRound.value);
  if (mConfirmed.checked) params.set('only_confirmed', 'true');
  const res = await fetch('/api/matrix?' + params.toString());
  const data = await res.json();
  const filtering = mAction.value || mRound.value || mConfirmed.checked;
  const codes = new Set(data.rows.map(r => r.code));
  // ukáž len karty, ktoré sú v odpovedi (pri filtri); inak ukáž všetky
  document.querySelectorAll('.m-card').forEach(card => {
    if (!filtering) { card.classList.remove('hidden'); return; }
    card.classList.toggle('hidden', !codes.has(card.dataset.code));
  });
}
[mAction, mRound, mConfirmed].forEach(el => el && el.addEventListener('change', refreshMatrix));

// ---- Export zoznamu krajín (na partner search) ----
const exportBtn = document.getElementById('m-export');
if (exportBtn) exportBtn.addEventListener('click', () => {
  const visible = Array.from(document.querySelectorAll('.m-card:not(.hidden):not(.empty)'))
    .map(c => c.dataset.country);
  if (!visible.length) { alert('Žiadne krajiny pre aktuálny filter.'); return; }
  navigator.clipboard.writeText(visible.join(', '));
  exportBtn.textContent = 'Skopírované: ' + visible.length + ' krajín';
  setTimeout(() => exportBtn.textContent = 'Exportovať zoznam krajín', 2000);
});

// ---- Potvrdzovanie nálezov (vyžaduje admin token) ----
function getToken() {
  let t = sessionStorage.getItem('admin_token');
  if (!t) { t = prompt('Admin token na potvrdenie:'); if (t) sessionStorage.setItem('admin_token', t); }
  return t;
}
document.querySelectorAll('.p-item').forEach(item => {
  const idx = item.dataset.idx;
  item.querySelector('.confirm').addEventListener('click', async () => {
    const code = item.querySelector('.p-action-code').value;
    const round = item.querySelector('.p-round').value;
    if (!code) { alert('Vyber akciu.'); return; }
    const token = getToken(); if (!token) return;
    const p = new URLSearchParams({ action_code: code, round, token });
    const res = await fetch(`/api/findings/${idx}/confirm?` + p, { method: 'POST' });
    if (res.ok) { item.style.opacity = .4; item.querySelector('.p-actions').innerHTML = '✓ Potvrdené — obnov stránku'; }
    else { alert('Chyba: ' + (res.status === 401 ? 'neplatný token' : res.status)); sessionStorage.removeItem('admin_token'); }
  });
  item.querySelector('.reject').addEventListener('click', async () => {
    const token = getToken(); if (!token) return;
    const res = await fetch(`/api/findings/${idx}/reject?` + new URLSearchParams({ token }), { method: 'POST' });
    if (res.ok) { item.style.opacity = .3; item.querySelector('.p-actions').innerHTML = 'zamietnuté'; }
    else { alert('Chyba'); sessionStorage.removeItem('admin_token'); }
  });
});
