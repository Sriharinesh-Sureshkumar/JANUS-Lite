// JANUS-LITE dashboard interactions
// Uses event delegation throughout so it keeps working after
// dashboard.js replaces the table body with live query results.

function initSidebar() {
  const menuBtn = document.querySelector('[data-menu-toggle]');
  const sidebar = document.querySelector('[data-sidebar]');
  const overlay = document.querySelector('[data-sidebar-overlay]');
  if (!menuBtn || !sidebar || !overlay) return;

  function open() {
    sidebar.classList.add('open');
    overlay.classList.add('open');
  }
  function close() {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
  }

  menuBtn.addEventListener('click', open);
  overlay.addEventListener('click', close);
}

function initRowExpand() {
  const tbody = document.getElementById('bugs-tbody');
  if (!tbody) return;

  tbody.addEventListener('click', (event) => {
    const row = event.target.closest('.data-row');
    if (!row) return;

    const targetId = row.getAttribute('data-target');
    const detail = document.getElementById(targetId);
    if (!detail) return;

    const isOpen = detail.classList.contains('open');

    tbody.querySelectorAll('.data-row').forEach((r) => r.classList.remove('expanded'));
    tbody.querySelectorAll('.detail-row').forEach((d) => d.classList.remove('open'));

    if (!isOpen) {
      row.classList.add('expanded');
      detail.classList.add('open');
      window.__janusExpandedTarget = targetId;
    } else {
      window.__janusExpandedTarget = null;
    }
  });
}

// Reads whichever pills/search box are currently active and shows/hides
// rows accordingly. Safe to call again any time the table is re-rendered.
function applyDashboardFilters() {
  const statusPills = document.querySelectorAll('[data-filter-status]');
  const sourcePills = document.querySelectorAll('[data-filter-source]');
  const rows = document.querySelectorAll('[data-row-status]');
  if (!rows.length && !statusPills.length) return;

  const activeStatusPill = document.querySelector('[data-filter-status].selected');
  const activeSourcePill = document.querySelector('[data-filter-source].selected');
  const activeStatus = activeStatusPill ? activeStatusPill.getAttribute('data-filter-status') : 'all';
  const activeSource = activeSourcePill ? activeSourcePill.getAttribute('data-filter-source') : 'all';

  const search = document.querySelector('[data-search]');
  const query = search ? search.value.trim().toLowerCase() : '';

  rows.forEach((row) => {
    const status = row.getAttribute('data-row-status');
    const source = row.getAttribute('data-row-source');
    const text = row.getAttribute('data-row-text') || '';
    const matchesStatus = activeStatus === 'all' || status === activeStatus;
    const matchesSource = activeSource === 'all' || source === activeSource;
    const matchesQuery = !query || text.includes(query);
    const show = matchesStatus && matchesSource && matchesQuery;
    row.style.display = show ? '' : 'none';

    const detail = document.getElementById(row.getAttribute('data-target'));
    if (detail) detail.style.display = show ? '' : 'none';
  });
}

function initFilters() {
  const filterBar = document.querySelector('.filter-bar');
  if (!filterBar) return;

  filterBar.addEventListener('click', (event) => {
    const pill = event.target.closest('[data-filter-status], [data-filter-source]');
    if (!pill) return;

    const isStatus = pill.hasAttribute('data-filter-status');
    const groupSelector = isStatus ? '[data-filter-status]' : '[data-filter-source]';
    filterBar.querySelectorAll(groupSelector).forEach((p) => p.classList.remove('selected'));
    pill.classList.add('selected');
    applyDashboardFilters();
  });

  const search = document.querySelector('[data-search]');
  if (search) {
    search.addEventListener('input', applyDashboardFilters);
  }
}

// Exposed so dashboard.js can re-apply the active filter after every
// live refresh without having to re-implement pill/search state.
window.applyDashboardFilters = applyDashboardFilters;

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  initRowExpand();
  initFilters();
});
