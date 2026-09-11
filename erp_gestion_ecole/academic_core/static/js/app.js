/* ═══════════════════════════════════════════════════════════════
   UniManager — Main JavaScript
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ── Sidebar toggle ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  const toggleBtn = document.getElementById('sidebarToggle');
  const sidebar   = document.getElementById('sidebar');
  const content   = document.getElementById('content');

  if (toggleBtn && sidebar && content) {
    const COLLAPSED_KEY = 'sidebar_collapsed';
    const isMobile = () => window.innerWidth < 769;

    function applyState(collapsed) {
      if (isMobile()) {
        sidebar.classList.toggle('mobile-open', !collapsed);
      } else {
        sidebar.classList.toggle('collapsed', collapsed);
        content.classList.toggle('expanded', collapsed);
      }
    }

    // Restore saved state
    const saved = localStorage.getItem(COLLAPSED_KEY) === 'true';
    applyState(saved);

    toggleBtn.addEventListener('click', () => {
      const nowCollapsed = isMobile()
        ? sidebar.classList.contains('mobile-open')
        : !sidebar.classList.contains('collapsed');
      localStorage.setItem(COLLAPSED_KEY, nowCollapsed);
      applyState(nowCollapsed);
    });
  }

  // ── DataTables default init ───────────────────────────────
  document.querySelectorAll('[data-datatable]').forEach(el => {
    $(el).DataTable({
      language: {
        url: 'https://cdn.datatables.net/plug-ins/1.13.8/i18n/fr-FR.json'
      },
      responsive: true,
      pageLength: 15,
      lengthMenu: [10, 15, 25, 50, 100],
    });
  });

  // ── Auto-dismiss alerts ───────────────────────────────────
  document.querySelectorAll('.alert-dismissible').forEach(el => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      bsAlert.close();
    }, 5000);
  });

  // ── Tooltips ─────────────────────────────────────────────
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    bootstrap.Tooltip.getOrCreateInstance(el);
  });

  // ── AJAX CSRF setup ───────────────────────────────────────
  const csrfToken = document.querySelector('meta[name="csrf-token"]');
  if (csrfToken) {
    $.ajaxSetup({
      beforeSend: function (xhr, settings) {
        if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(settings.type)) {
          xhr.setRequestHeader('X-CSRFToken', csrfToken.content);
        }
      }
    });
  }

  // ── Confirm dialogs ───────────────────────────────────────
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', function (e) {
      if (!confirm(this.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });
});

// ── Utility: show toast notification ─────────────────────────
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container') || (() => {
    const c = document.createElement('div');
    c.id = 'toast-container';
    c.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    c.style.zIndex = 9999;
    document.body.appendChild(c);
    return c;
  })();

  const typeMap = { success: 'bg-success', danger: 'bg-danger', warning: 'bg-warning', info: 'bg-info' };
  const el = document.createElement('div');
  el.className = `toast align-items-center text-white ${typeMap[type] || 'bg-info'} border-0`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(el);
  const toast = new bootstrap.Toast(el, { delay: 4000 });
  toast.show();
  el.addEventListener('hidden.bs.toast', () => el.remove());
}

// ── Utility: format date FR ───────────────────────────────────
function formatDateFR(dateStr) {
  const d = new Date(dateStr);
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
}
