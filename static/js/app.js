(() => {
  'use strict';

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) { tg.ready(); tg.expand(); }
  const tgUser = tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
  const qsUserId = new URLSearchParams(window.location.search).get('user_id');
  const USER_ID = Number(qsUserId || (tgUser && tgUser.id) || 123456789);

  const RARITY_COLORS = {
    'Mil-Spec': '#4b69ff',
    'Restricted': '#8847ff',
    'Classified': '#d32ce6',
    'Covert': '#eb4b4b',
    'Special': '#ffb900',
  };
  const RARITY_ORDER = ['Special', 'Covert', 'Classified', 'Restricted', 'Mil-Spec'];
  const REEL_MS = 6500;
  const REEL_CARD_W = 96;
  const REEL_GAP = 8;

  const state = { user: null, cases: [], busy: false };

  const $ = (id) => document.getElementById(id);

  function hapticImpact() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
  }
  function hapticSuccess() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
  }
  function hapticError() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value === null || value === undefined ? '' : String(value);
    return div.innerHTML;
  }

  function money(value) {
    const rounded = Math.round(Number(value) || 0);
    return rounded.toLocaleString('ru-RU').replace(/\u00a0/g, ' ') + ' \u20bd';
  }

  async function api(path, options) {
    const response = await fetch(path, Object.assign(
      { headers: { 'Content-Type': 'application/json' } }, options
    ));
    let payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok) {
      const message = payload && payload.detail ? String(payload.detail) : ('HTTP ' + response.status);
      throw new Error(message);
    }
    return payload;
  }

  let toastTimer = null;
  function toast(message, kind) {
    const el = $('toast');
    el.textContent = message;
    el.className = 'toast' + (kind ? ' ' + kind : '');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.classList.add('hidden'); toastTimer = null; }, 3200);
  }

  let lastBalance = null;
  function animateBalance(target) {
    const el = $('balance-pill');
    const from = lastBalance === null ? target : lastBalance;
    lastBalance = target;
    if (from === target) { el.textContent = money(target); return; }
    const started = performance.now();
    const duration = 650;
    const step = (now) => {
      const k = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = money(from + (target - from) * eased);
      if (k < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = money(target);
        el.classList.remove('bump');
        void el.offsetWidth;
        el.classList.add('bump');
      }
    };
    requestAnimationFrame(step);
  }

  function renderHeader() {
    const name = (tgUser && (tgUser.first_name || tgUser.username)) || (state.user && state.user.first_name) || 'Player ' + USER_ID;
    $('user-name').textContent = name;
    const avatar = $('user-avatar');
    if (tgUser && tgUser.photo_url) {
      avatar.innerHTML = '';
      const img = document.createElement('img');
      img.src = tgUser.photo_url;
      img.alt = '';
      avatar.appendChild(img);
    } else {
      avatar.textContent = String(name).charAt(0).toUpperCase();
    }
    $('inv-count').textContent = state.user ? state.user.inventory_count : 0;
    animateBalance(state.user ? state.user.balance : 0);
  }

  async function refreshUser() {
    try {
      state.user = await api('/api/user/' + USER_ID);
      renderHeader();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  function showModal(id) { $(id).classList.remove('hidden'); }
  function hideModal(id) { $(id).classList.add('hidden'); }

  function renderGrid() {
    const grid = $('case-grid');
    grid.innerHTML = '';
    state.cases.forEach((kase) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'case-card';
      card.style.setProperty('--accent', kase.accent || RARITY_COLORS['Mil-Spec']);
      card.innerHTML =
        '<div class="case-box"></div>' +
        '<div class="case-name">' + escapeHtml(kase.name) + '</div>' +
        '<div class="case-price' + (kase.price === 0 ? ' free' : '') + '">' +
        (kase.price === 0 ? 'FREE &middot; 24h' : money(kase.price)) +
        '</div>';
      card.addEventListener('click', () => openCaseModal(kase));
      grid.appendChild(card);
    });
  }

  function cooldownRemainingMs() {
    if (!state.user || !state.user.free_case_available_at) return 0;
    const readyAt = new Date(state.user.free_case_available_at).getTime();
    return Math.max(0, readyAt - Date.now());
  }

  function formatDuration(ms) {
    const totalSeconds = Math.ceil(ms / 1000);
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const pad = (n) => (n < 10 ? '0' + n : String(n));
    return h + ':' + pad(m) + ':' + pad(s);
  }

  let cooldownTimer = null;
  function stopCooldownTimer() {
    if (cooldownTimer) { clearInterval(cooldownTimer); cooldownTimer = null; }
  }

  function updateFreeCaseButton(kase) {
    const button = $('btn-open-case');
    const remaining = cooldownRemainingMs();
    if (kase.price !== 0) return;
    if (remaining > 0) {
      button.disabled = true;
      button.textContent = 'Free case ready in ' + formatDuration(remaining);
    } else {
      button.disabled = false;
      button.textContent = 'Open — Free';
    }
  }

  function openCaseModal(kase) {
    stopCooldownTimer();
    $('case-modal-name').textContent = kase.name;
    $('case-modal-sub').textContent = kase.price === 0
      ? 'Free once every ' + (kase.cooldown_hours || 24) + ' hours'
      : 'Price: ' + money(kase.price) + ' \u00b7 ' + kase.items.length + ' items';

    const pool = $('case-pool');
    pool.innerHTML = '';
    const byRarity = {};
    kase.items.forEach((item) => {
      (byRarity[item.rarity] = byRarity[item.rarity] || []).push(item);
    });
    RARITY_ORDER.forEach((rarity) => {
      const items = byRarity[rarity];
      if (!items) return;
      const color = RARITY_COLORS[rarity];
      const group = document.createElement('div');
      group.className = 'pool-group';
      group.style.color = color;
      group.textContent = rarity;
      pool.appendChild(group);
      items.sort((a, b) => b.base_price - a.base_price).forEach((item) => {
        const row = document.createElement('div');
        row.className = 'pool-row';
        row.style.setProperty('--rc', color);
        row.innerHTML =
          '<span class="dot"></span>' +
          '<span class="nm">' + escapeHtml(item.name) + '</span>' +
          '<span class="pr">' + money(item.base_price) + '</span>';
        pool.appendChild(row);
      });
    });

    const button = $('btn-open-case');
    if (kase.price === 0) {
      updateFreeCaseButton(kase);
      stopCooldownTimer();
      cooldownTimer = setInterval(() => {
        if ($('case-modal').classList.contains('hidden')) { stopCooldownTimer(); return; }
        updateFreeCaseButton(kase);
      }, 1000);
    } else {
      const affordable = state.user && state.user.balance >= kase.price;
      button.disabled = !affordable;
      button.textContent = affordable
        ? 'Open for ' + money(kase.price)
        : 'Not enough \u20bd (' + money(kase.price) + ')';
    }
    button.onclick = () => { if (!button.disabled) openCase(kase); };
    showModal('case-modal');
  }

  function buildReelItem(item, isWinner) {
    const color = RARITY_COLORS[item.rarity] || '#8b93a7';
    const el = document.createElement('div');
    el.className = 'reel-item' + (isWinner ? ' win' : '');
    el.style.setProperty('--rc', color);
    el.innerHTML =
      '<span class="ri-gem">\u25c6</span>' +
      '<span class="ri-name">' + escapeHtml(item.name) + '</span>';
    return el;
  }

  function showIdleReel(kase) {
    const track = $('reel-track');
    track.style.transition = 'none';
    track.style.transform = 'translateX(0px)';
    track.innerHTML = '';
    for (let i = 0; i < 14; i += 1) {
      const item = kase.items[Math.floor(Math.random() * kase.items.length)];
      track.appendChild(buildReelItem(item, false));
    }
  }

  function spinReel(reel) {
    return new Promise((resolve) => {
      const track = $('reel-track');
      const windowEl = $('reel-window');
      track.innerHTML = '';
      reel.forEach((item, index) => {
        track.appendChild(buildReelItem(item, index === reel.length - 1));
      });

      const targetIndex = reel.length - 1;
      const jitter = (Math.random() - 0.5) * (REEL_CARD_W * 0.55);
      const winnerCenter = targetIndex * (REEL_CARD_W + REEL_GAP) + REEL_CARD_W / 2 + jitter;
      const distance = winnerCenter - windowEl.clientWidth / 2;

      track.style.transition = 'none';
      track.style.transform = 'translateX(0px)';
      void track.offsetWidth;
      track.style.transition = 'transform ' + REEL_MS + 'ms cubic-bezier(0.08, 0.68, 0.09, 1)';
      track.style.transform = 'translateX(' + (-distance) + 'px)';

      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        track.removeEventListener('transitionend', onEnd);
        resolve();
      };
      const onEnd = (event) => {
        if (event.propertyName === 'transform') finish();
      };
      track.addEventListener('transitionend', onEnd);
      setTimeout(finish, REEL_MS + 1200);
    });
  }

  async function openCase(kase) {
    if (state.busy) return;
    state.busy = true;
    hideModal('case-modal');
    stopCooldownTimer();
    $('reel-title').textContent = 'Opening ' + kase.name;
    showIdleReel(kase);
    showModal('reel-modal');
    hapticImpact();
    try {
      const result = await api('/api/cases/open', {
        method: 'POST',
        body: JSON.stringify({ user_id: USER_ID, case_id: kase.id }),
      });
      await spinReel(result.reel);
      hapticSuccess();
      animateBalance(result.new_balance);
      showResult(result.winner);
    } catch (err) {
      hideModal('reel-modal');
      hapticError();
      toast(err.message, 'error');
      await refreshUser();
    } finally {
      state.busy = false;
    }
  }

  function showResult(winner) {
    hideModal('reel-modal');
    const color = RARITY_COLORS[winner.rarity] || '#8b93a7';
    const card = $('drop-card');
    card.style.setProperty('--rc', color);
    card.innerHTML =
      '<div class="drop-rarity">' + escapeHtml(winner.rarity) + '</div>' +
      '<div class="drop-name">' + (winner.is_stat_trak ? '<span class="st-badge">StatTrak&trade;</span> ' : '') +
      escapeHtml(winner.name) + '</div>' +
      '<div class="drop-wear">' + escapeHtml(winner.wear) + '</div>' +
      '<div class="drop-float">float ' + Number(winner.wear_float).toFixed(4) + '</div>' +
      '<div class="drop-price">' + money(winner.price) + '</div>';

    const sellButton = $('btn-sell');
    sellButton.disabled = false;
    sellButton.textContent = 'Sell for ' + money(winner.price);
    sellButton.onclick = async () => {
      sellButton.disabled = true;
      try {
        const result = await api('/api/items/sell', {
          method: 'POST',
          body: JSON.stringify({ user_id: USER_ID, item_id: winner.item_id }),
        });
        animateBalance(result.new_balance);
        hapticSuccess();
        toast('+' + money(result.sold_price) + ' credited', 'success');
        hideModal('result-modal');
        await refreshUser();
      } catch (err) {
        hapticError();
        toast(err.message, 'error');
        sellButton.disabled = false;
      }
    };

    $('btn-keep').onclick = () => {
      hideModal('result-modal');
      toast(winner.name + ' moved to vault');
      refreshUser();
    };
    showModal('result-modal');
  }

  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => hideModal(button.getAttribute('data-close')));
  });
  document.querySelectorAll('.modal-backdrop').forEach((backdrop) => {
    backdrop.addEventListener('click', (event) => {
      if (event.target !== backdrop) return;
      const id = backdrop.getAttribute('id');
      if (id === 'reel-modal' && state.busy) return;
      if (id === 'reel-modal') return;
      hideModal(id);
    });
  });

  async function init() {
    try {
      const results = await Promise.all([
        api('/api/cases'),
        api('/api/user/' + USER_ID),
      ]);
      state.cases = results[0].cases;
      state.user = results[1];
      renderHeader();
      renderGrid();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  init();
})();
