const filter = document.getElementById('filter');
const rows = Array.from(document.querySelectorAll('#agtable tbody tr'));
filter.addEventListener('input', () => {
  const q = filter.value.toLowerCase().trim();
  rows.forEach(r => {
    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
});
