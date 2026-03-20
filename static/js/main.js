/**
 * TradeReady — main.js
 * Real-time updates, sparklines, polling
 * CSP compliant — no eval()
 */

'use strict';

// ─── UTILITIES ────────────────────────────────────────────────────────────────
function formatCurrency(v) {
  if (v === null || v === undefined) return 'N/A';
  var n = parseFloat(v);
  if (isNaN(n)) return 'N/A';
  if (Math.abs(n) >= 1e9) return '$' + (n/1e9).toFixed(2) + 'B';
  if (Math.abs(n) >= 1e6) return '$' + (n/1e6).toFixed(2) + 'M';
  if (Math.abs(n) >= 1e3) return '$' + (n/1e3).toFixed(2) + 'K';
  if (Math.abs(n) < 0.01) return '$' + n.toFixed(6);
  return '$' + n.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
}

function formatPct(v) {
  if (v === null || v === undefined) return 'N/A';
  var n = parseFloat(v);
  if (isNaN(n)) return 'N/A';
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

// ─── TOAST ───────────────────────────────────────────────────────────────────
function showToast(msg, type) {
  type = type || 'primary';
  var c = document.getElementById('toastContainer');
  if (!c) {
    c = document.createElement('div');
    c.id = 'toastContainer';
    c.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    c.style.zIndex = '9999';
    document.body.appendChild(c);
  }
  var el = document.createElement('div');
  el.className = 'toast align-items-center text-bg-' + type + ' border-0 mb-2';
  el.setAttribute('role', 'alert');
  el.innerHTML = '<div class="d-flex"><div class="toast-body">' + msg +
    '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
  c.appendChild(el);
  var toast = new bootstrap.Toast(el, {delay: 3000});
  toast.show();
  el.addEventListener('hidden.bs.toast', function() { el.remove(); });
}

// ─── SPARKLINES ──────────────────────────────────────────────────────────────
var sparkCharts = {};

function renderSparkline(canvas, prices, isPositive) {
  if (!canvas || !prices || !prices.length) return;
  if (sparkCharts[canvas.id]) { sparkCharts[canvas.id].destroy(); }
  var step   = Math.max(1, Math.floor(prices.length / 25));
  var sample = prices.filter(function(_, i) { return i % step === 0; });
  var color  = isPositive ? '#0dff8c' : '#ff3a5c';
  sparkCharts[canvas.id] = new Chart(canvas, {
    type: 'line',
    data: {
      labels: sample.map(function(_, i) { return i; }),
      datasets: [{
        data: sample,
        borderColor: color,
        backgroundColor: color + '18',
        borderWidth: 1.5,
        fill: true,
        tension: 0.4,
        pointRadius: 0,
      }]
    },
    options: {
      responsive: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
    }
  });
}

function renderAllSparklines() {
  document.querySelectorAll('.sparkline-canvas').forEach(function(canvas) {
    try {
      var raw = canvas.getAttribute('data-sparkline');
      if (!raw) return;
      var prices   = JSON.parse(raw);
      var positive = canvas.getAttribute('data-positive') === 'True';
      renderSparkline(canvas, prices, positive);
    } catch(e) {}
  });
}

// ─── REAL-TIME PRICE UPDATES ─────────────────────────────────────────────────
function updatePrices(coins) {
  coins.forEach(function(coin) {
    document.querySelectorAll('[data-price-id="' + coin.id + '"]').forEach(function(el) {
      var newVal = formatCurrency(coin.price);
      if (el.textContent !== newVal) {
        el.textContent = newVal;
        el.classList.add('price-flash');
        var id = coin.id;
        setTimeout(function() {
          var target = document.querySelector('[data-price-id="' + id + '"]');
          if (target) target.classList.remove('price-flash');
        }, 600);
      }
    });
    document.querySelectorAll('[data-change-id="' + coin.id + '"]').forEach(function(el) {
      el.textContent = formatPct(coin.change24);
      el.className = el.className.replace(/\bpositive\b|\bnegative\b/g, '').trim();
      el.classList.add((parseFloat(coin.change24) || 0) >= 0 ? 'positive' : 'negative');
    });
  });
}

function fetchPrices() {
  fetch('/api/markets')
    .then(function(r) { return r.json(); })
    .then(function(resp) {
      if (!resp.data || !resp.data.length) return;
      updatePrices(resp.data);
      if (resp.last_updated) {
        var el = document.querySelector('.last-updated');
        if (el) el.textContent = 'Last updated: ' + resp.last_updated;
      }
    })
    .catch(function() {});
}

function fetchFearGreed() {
  fetch('/api/fear-greed')
    .then(function(r) { return r.json(); })
    .then(function(fg) {
      if (!fg || !fg.value) return;
      var valEl   = document.querySelector('.fg-value');
      var clsEl   = document.querySelector('.fg-class');
      var needle  = document.querySelector('.fg-gauge-needle');
      if (valEl)  valEl.textContent  = fg.value;
      if (clsEl)  clsEl.textContent  = fg.class;
      if (needle) needle.style.left  = fg.value + '%';

      // Update color
      var color = fg.value <= 24 ? '#ff3a5c' :
                  fg.value <= 49 ? '#ffc832' :
                  fg.value <= 74 ? '#ff7a30' : '#0dff8c';
      if (valEl) valEl.style.color = color;
      if (clsEl) clsEl.style.color = color;
    })
    .catch(function() {});
}

// ─── LOADING STATE POLLER ─────────────────────────────────────────────────────
// Polls /api/status every 3s until data ready, then reloads once
function startLoadingPoller() {
  if (!document.body || document.body.getAttribute('data-loading') !== 'true') return;

  var msg      = document.getElementById('loadingMsg');
  var attempts = 0;
  var maxAttempts = 60; // 3 minutes

  var interval = setInterval(function() {
    attempts++;

    fetch('/api/status')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.markets && data.markets_count > 0) {
          clearInterval(interval);
          if (msg) msg.textContent = 'Data ready! Loading...';
          // Small delay so user sees the message
          setTimeout(function() { window.location.reload(); }, 500);
        } else {
          // Update loading message with progress
          var secs = attempts * 3;
          if (msg) {
            msg.innerHTML =
              '<span class="spinner-border spinner-border-sm me-1"></span>' +
              'Fetching market data... (' + secs + 's)';
          }
        }
      })
      .catch(function() {});

    if (attempts >= maxAttempts) {
      clearInterval(interval);
      if (msg) {
        msg.innerHTML =
          '⚠ Taking too long. ' +
          '<a href="/" class="text-warning ms-1">Click to reload</a>';
      }
    }
  }, 3000); // poll every 3 seconds
}

// ─── REFRESH BUTTON ───────────────────────────────────────────────────────────
function refreshData() {
  var btn = document.getElementById('refreshBtn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  }

  fetch('/api/refresh', {method: 'POST'})
    .then(function(r) { return r.json(); })
    .then(function() {
      showToast('Refreshing data...', 'success');
      // Poll status and reload when ready
      var checks = 0;
      var poll = setInterval(function() {
        checks++;
        fetch('/api/status')
          .then(function(r) { return r.json(); })
          .then(function(data) {
            if (data.markets_count > 0) {
              clearInterval(poll);
              window.location.reload();
            }
          })
          .catch(function() {});
        if (checks > 20) {
          clearInterval(poll);
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
          }
        }
      }, 2000);
    })
    .catch(function() {
      showToast('Refresh failed', 'danger');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
      }
    });
}

// ─── SEARCH ───────────────────────────────────────────────────────────────────
function initSearch() {
  var input = document.getElementById('searchInput');
  if (!input) return;
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') e.target.closest('form').submit();
  });
}

// ─── INIT ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  var isLoading = document.body.getAttribute('data-loading') === 'true';

  renderAllSparklines();
  initSearch();

  if (isLoading) {
    // Page is still waiting for first data — poll until ready
    startLoadingPoller();
  } else {
    // Data is loaded — start real-time updates
    fetchFearGreed();       // update F&G immediately on load
    fetchPrices();          // update prices immediately on load

    setInterval(fetchFearGreed, 60000);  // F&G every 60s
    setInterval(fetchPrices,    30000);  // prices every 30s
  }
});
