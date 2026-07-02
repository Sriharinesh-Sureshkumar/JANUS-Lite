// Data wiring for the JANUS-LITE dashboard.
//
// This app is public (visibility: PUBLIC), but `client.datastore.query()`
// still hits an authenticated endpoint even for public apps — there is no
// anonymous/public read path in lemma-sdk or the Lemma docs (checked the
// browser bundle source and the apps/data-and-files/access-scope docs).
// So instead of querying live from the browser, the pod-side pipeline runs
// `scripts/generate_static_data.py` (an authenticated CLI session) to bake
// the bugs table into site/data/bugs.json at deploy time. The dashboard
// just fetches that static file — no SDK, no auth, no live query.
//
// Tradeoff: data only updates on redeploy, not live. Fine for a demo.

(function () {
  const REFRESH_MS = 30000;
  const DATA_URL = 'data/bugs.json';

  const STATUS_BORDER_COLOR = {
    verified_and_fixed: '#4ADE80',
    rejected: '#F87171',
    triaged: '#FBBF24',
    new: '#818CF8',
    reproducing: '#38BDF8',
    escalated: '#FB923C',
  };

  let hasLoadedOnce = false;
  let lastUpdated = null;
  let dataGeneratedAt = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));
  }

  function attemptsClass(n) {
    const v = Number(n) || 0;
    if (v === 0) return 'attempts-0';
    if (v >= 3) return 'attempts-max';
    return 'attempts-mid';
  }

  function renderDiff(diffText) {
    if (!diffText) {
      return '<div class="diff-block"><div class="diff-line">No patch produced</div></div>';
    }
    const lines = diffText.split('\n').map((line) => {
      let cls = '';
      if (line.startsWith('+')) cls = 'diff-add';
      else if (line.startsWith('-')) cls = 'diff-del';
      return `<div class="diff-line ${cls}">${escapeHtml(line)}</div>`;
    });
    return `<div class="diff-block">${lines.join('')}</div>`;
  }

  function renderRow(bug) {
    const targetId = `detail-${bug.id}`;
    const hypothesis = bug.hypothesis || 'No hypothesis recorded yet.';
    const confidenceCell = bug.confidence
      ? `<span class="confidence-pill confidence-${bug.confidence}">${escapeHtml(bug.confidence)}</span>`
      : '<span class="dash">&mdash;</span>';
    const staticAnalysisCell = bug.static_analysis_findings
      ? '<span class="check-yes">&#10003;</span>'
      : '<span class="check-no">&mdash;</span>';
    const prCell = bug.pr_url
      ? `<a class="pr-link" href="${escapeHtml(bug.pr_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">&#128279;</a>`
      : '<span class="dash">&mdash;</span>';
    const resultCard = bug.pr_url
      ? `<div class="result-card fixed">Fix verified — PR opened<a href="${escapeHtml(bug.pr_url)}" target="_blank" rel="noopener">${escapeHtml(bug.pr_url)}</a></div>`
      : '';
    const borderColor = STATUS_BORDER_COLOR[bug.status] || '#475569';
    const searchText = `${hypothesis} ${bug.source_ref || ''}`.toLowerCase();

    return `
      <tr class="data-row" data-target="${targetId}" data-row-status="${bug.status}" data-row-source="${bug.source}" data-row-text="${escapeHtml(searchText)}">
        <td><span class="source-badge source-${bug.source}">${bug.source}</span></td>
        <td class="priority-${bug.priority}">${bug.priority}</td>
        <td class="hypothesis-cell">${escapeHtml(hypothesis)}</td>
        <td><span class="status-badge status-${bug.status}">${bug.status}</span></td>
        <td>${confidenceCell}</td>
        <td>${staticAnalysisCell}</td>
        <td class="mono-cell ${attemptsClass(bug.attempts)}">${bug.attempts || 0}</td>
        <td>${prCell}</td>
      </tr>
      <tr class="detail-row" id="${targetId}">
        <td colspan="8">
          <div class="detail-panel" style="border-left:2px solid ${borderColor}">
            <div class="detail-col-left">
              <div>
                <div class="detail-label">Hypothesis</div>
                <div class="detail-text">${escapeHtml(hypothesis)}</div>
              </div>
              <div>
                <div class="detail-label">Repro test</div>
                <div class="code-block">${escapeHtml(bug.repro_test || 'No repro test written yet.')}</div>
              </div>
              <div>
                <div class="detail-label">Patch diff</div>
                ${renderDiff(bug.patch_diff)}
              </div>
            </div>
            <div class="detail-col-right">
              <div>
                <div class="detail-label">Evidence log</div>
                <div class="evidence-block">${escapeHtml(bug.evidence_log || 'No evidence log yet.')}</div>
              </div>
              <div>
                <div class="detail-label">Static analysis findings</div>
                <div class="findings-block">${escapeHtml(bug.static_analysis_findings || 'Not yet run.')}</div>
              </div>
              ${resultCard}
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  function setText(selector, value) {
    const el = document.querySelector(selector);
    if (el) el.textContent = value;
  }

  function computeCounts(bugs) {
    const counts = {
      total: bugs.length,
      new: 0,
      triaged: 0,
      reproducing: 0,
      rejected: 0,
      verified_and_fixed: 0,
      escalated: 0,
    };
    bugs.forEach((b) => {
      if (Object.prototype.hasOwnProperty.call(counts, b.status)) counts[b.status]++;
    });
    return counts;
  }

  function renderMetrics(counts) {
    setText('#metric-total', counts.total);
    setText('#metric-triaged', counts.triaged);
    setText('#metric-rejected', counts.rejected);
    setText('#metric-fixed', counts.verified_and_fixed);
  }

  function renderFlow(counts) {
    setText('#flow-new', counts.new);
    setText('#flow-triaged', counts.triaged);
    setText('#flow-reproducing', counts.reproducing);
    setText('#flow-fixed', counts.verified_and_fixed);
    setText('#flow-rejected', counts.rejected);
  }

  function renderTable(bugs) {
    const tbody = document.getElementById('bugs-tbody');
    if (!tbody) return;

    if (!bugs.length) {
      tbody.innerHTML = '<tr><td colspan="8" style="padding:24px 16px;color:var(--text-muted)">No bugs recorded yet.</td></tr>';
      return;
    }

    tbody.innerHTML = bugs.map(renderRow).join('');

    const expanded = window.__janusExpandedTarget;
    if (expanded) {
      const detail = document.getElementById(expanded);
      const row = tbody.querySelector(`[data-target="${expanded}"]`);
      if (detail && row) {
        detail.classList.add('open');
        row.classList.add('expanded');
      }
    }

    if (window.applyDashboardFilters) window.applyDashboardFilters();
  }

  function setBanner(kind, message) {
    const banner = document.getElementById('state-banner');
    if (!banner) return;
    banner.textContent = message;
    banner.className = `state-banner ${kind}`;
    banner.style.display = '';
  }

  function clearBanner() {
    const banner = document.getElementById('state-banner');
    if (!banner) return;
    banner.style.display = 'none';
  }

  function tickLastUpdated() {
    const el = document.getElementById('last-updated-text');
    if (!el || !lastUpdated) return;
    const seconds = Math.max(0, Math.round((Date.now() - lastUpdated.getTime()) / 1000));
    const fetchedAgo = seconds < 2 ? 'just now' : `${seconds}s ago`;
    el.textContent = dataGeneratedAt
      ? `Data generated ${dataGeneratedAt} · checked ${fetchedAgo}`
      : `Last updated ${fetchedAgo}`;
  }

  async function loadBugs() {
    if (!hasLoadedOnce) setBanner('loading', 'Loading bugs…');
    try {
      // cache: 'no-store' bypasses the browser's HTTP cache entirely, since
      // this platform serves every static asset with a 1-year immutable
      // Cache-Control header regardless of whether the file actually changed.
      const res = await fetch(DATA_URL, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      const bugs = payload.items || [];

      const counts = computeCounts(bugs);
      renderMetrics(counts);
      renderFlow(counts);
      renderTable(bugs);

      hasLoadedOnce = true;
      lastUpdated = new Date();
      dataGeneratedAt = payload.generated_at || null;
      clearBanner();
    } catch (err) {
      console.error('[janus-lite] failed to load bugs', err);
      const reason = err && err.message ? err.message : 'unknown error';
      setBanner('error', `Failed to load bugs from ${DATA_URL}: ${reason}. Retrying in 30s.`);
      if (!hasLoadedOnce) {
        const tbody = document.getElementById('bugs-tbody');
        if (tbody) {
          tbody.innerHTML = '<tr><td colspan="8" style="padding:24px 16px;color:var(--text-muted)">Unable to load bugs right now.</td></tr>';
        }
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('bugs-tbody')) return; // not the dashboard page

    loadBugs();
    setInterval(loadBugs, REFRESH_MS);
    setInterval(tickLastUpdated, 1000);
  });
})();
