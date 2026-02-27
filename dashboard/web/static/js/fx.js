/* ============================================================
   MEWC Dashboard — FX / Background animations
   ============================================================ */

'use strict';

/* ── Particle Canvas ───────────────────────────────────── */
(function initParticles() {
  const canvas = document.getElementById('bgCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let W, H, particles = [], animId;

  const COLORS = ['rgba(255,149,0,', 'rgba(255,107,0,', 'rgba(108,77,255,', 'rgba(79,195,247,'];
  const COUNT  = Math.min(80, Math.floor(window.innerWidth / 16));

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function mkParticle() {
    const c = COLORS[Math.floor(Math.random() * COLORS.length)];
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      r: Math.random() * 1.4 + 0.3,
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.25,
      a: Math.random() * 0.5 + 0.1,
      da: (Math.random() - 0.5) * 0.003,
      color: c,
    };
  }

  function init() {
    resize();
    particles = Array.from({ length: COUNT }, mkParticle);
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // Draw connecting lines for nearby particles
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const p1 = particles[i], p2 = particles[j];
        const dx = p1.x - p2.x, dy = p1.y - p2.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.strokeStyle = `rgba(255,149,0,${0.06 * (1 - dist / 120)})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }

    // Draw particles
    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;
      p.a += p.da;
      if (p.a <= 0.05 || p.a >= 0.65) p.da *= -1;
      if (p.x < -10) p.x = W + 10;
      if (p.x > W + 10) p.x = -10;
      if (p.y < -10) p.y = H + 10;
      if (p.y > H + 10) p.y = -10;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color + p.a.toFixed(2) + ')';
      ctx.fill();
    }

    animId = requestAnimationFrame(draw);
  }

  window.addEventListener('resize', () => { resize(); });

  init();
  draw();
})();

/* ── Animated number counter ───────────────────────────── */
const CounterAnim = (() => {
  const active = new Map();

  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

  function animate(el, from, to, duration, fmt) {
    if (active.has(el)) cancelAnimationFrame(active.get(el));

    const start = performance.now();
    const range = to - from;

    function step(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const value = from + range * easeOut(progress);
      el.textContent = fmt(value);

      if (progress < 1) {
        active.set(el, requestAnimationFrame(step));
      } else {
        el.textContent = fmt(to);
        active.delete(el);
        el.classList.add('num-updated');
        setTimeout(() => el.classList.remove('num-updated'), 600);
      }
    }

    active.set(el, requestAnimationFrame(step));
  }

  return { animate };
})();

/* ── Smart number updater ──────────────────────────────── */
function setNumber(id, value, opts = {}) {
  const el = document.getElementById(id);
  if (!el) return;

  const {
    decimals = 4,
    prefix   = '',
    suffix   = '',
    animate  = true,
    duration = 600,
    colorize = false,
    threshold = 0,
  } = opts;

  const num = parseFloat(value);
  if (isNaN(num)) { el.textContent = prefix + String(value) + suffix; return; }

  const fmt = (v) => prefix + v.toFixed(decimals) + suffix;

  // Colorize
  if (colorize) {
    el.classList.toggle('positive', num > threshold);
    el.classList.toggle('negative', num < threshold);
    el.classList.toggle('neutral',  num === threshold);
  }

  // Get current displayed value
  const current = parseFloat(el.textContent.replace(/[^0-9.-]/g, '')) || 0;

  if (animate && Math.abs(num - current) > 1e-9 && current !== 0) {
    CounterAnim.animate(el, current, num, duration, fmt);
  } else {
    el.textContent = fmt(num);
    if (animate && current !== 0 && Math.abs(num - current) > 1e-9) {
      el.classList.add('num-updated');
      setTimeout(() => el.classList.remove('num-updated'), 600);
    }
  }
}

/* ── Countdown bar ─────────────────────────────────────── */
const CountdownBar = (() => {
  let totalMs = 5000, remaining = 5000, lastTick = 0, animId;

  function tick(now) {
    if (lastTick) {
      remaining -= (now - lastTick);
      remaining  = Math.max(0, remaining);
    }
    lastTick = now;

    const pct = (remaining / totalMs) * 100;
    const fill = document.getElementById('countdownFill');
    const label = document.getElementById('countdown');
    if (fill)  fill.style.width = pct + '%';
    if (label) label.textContent = Math.ceil(remaining / 1000) + 's';

    animId = requestAnimationFrame(tick);
  }

  return {
    start(ms) {
      totalMs = ms;
      remaining = ms;
      lastTick = 0;
      if (animId) cancelAnimationFrame(animId);
      animId = requestAnimationFrame(tick);
    },
    reset(ms) {
      remaining = ms || totalMs;
      lastTick = 0;
    },
  };
})();

/* ── Tab switcher ──────────────────────────────────────── */
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.tab-panel').forEach(p => {
        p.classList.toggle('active', p.id === 'tab-' + target);
      });
    });
  });
}

/* ── Toast ─────────────────────────────────────────────── */
let toastTimer;
function toast(msg, type = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = 'toast show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}

/* ── Modal ─────────────────────────────────────────────── */
function openModal(title, content) {
  const overlay = document.getElementById('modalOverlay');
  const body    = document.getElementById('modalBody');
  const titleEl = document.getElementById('modalTitle');
  if (!overlay || !body) return;
  if (titleEl) titleEl.textContent = title || '';
  body.innerHTML = content || '';
  overlay.classList.add('open');
}

function closeModal() {
  const overlay = document.getElementById('modalOverlay');
  if (overlay) overlay.classList.remove('open');
}

// Close on overlay click
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('modalOverlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal();
  });
  initTabs();
});
