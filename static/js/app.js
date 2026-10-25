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
  const RARITY_RU = {
    'Mil-Spec': 'Армейское качество',
    'Restricted': 'Запрещённое',
    'Classified': 'Засекреченное',
    'Covert': 'Тайное',
    'Special': '★ Экстраординарное',
  };
  const RARITY_ORDER = ['Special', 'Covert', 'Classified', 'Restricted', 'Mil-Spec'];
  const WEAR_RU = {
    'Factory New': ['Прямо с завода', 'FN'],
    'Minimal Wear': ['Немного поношенное', 'MW'],
    'Field-Tested': ['После полевых испытаний', 'FT'],
    'Well-Worn': ['Поношенное', 'WW'],
    'Battle-Scarred': ['Закалённое в боях', 'BS'],
  };
  const REEL_MS = 6500;
  const REEL_CARD_W = 120;
  const REEL_GAP = 10;
  const FALLBACK_IMG =
    'data:image/svg+xml;utf8,' +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">' +
      '<rect width="120" height="80" rx="10" fill="#16203c"/>' +
      '<text x="60" y="46" text-anchor="middle" font-size="26" fill="#3a4a75">?</text>' +
      '</svg>'
    );

  const state = { user: null, cases: [], inventory: [], view: 'cases', busy: false };

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

  function plural(n, one, few, many) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  }

  // Steam economy CDN supports /WxH resize suffixes on the raw image URL.
  function cdn(url, size) {
    if (!url) return FALLBACK_IMG;
    return size ? url + '/' + size : url;
  }

  function skinImage(item, size, cls, alt) {
    const img = document.createElement('img');
    img.className = cls || '';
    img.alt = alt || '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.src = cdn(item.image, size || '256fx256f');
    img.addEventListener('error', () => { img.src = FALLBACK_IMG; }, { once: true });
    return img;
  }

  function wearRu(wear) { return (WEAR_RU[wear] || [wear, wear])[0]; }
  function wearShort(wear) { return (WEAR_RU[wear] || [wear, '?'])[1]; }

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
    $('balance-top').textContent = money(target);
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

  /* ---------- Header / user ---------- */

  function renderHeader() {
    const name = (tgUser && (tgUser.first_name || tgUser.username)) ||
      (state.user && state.user.first_name) || 'Игрок ' + USER_ID;
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
    setInventoryBadge(state.user ? state.user.inventory_count : 0);
    animateBalance(state.user ? state.user.balance : 0);
  }

  function setInventoryBadge(count) {
    $('tab-inv-badge').textContent = count;
    $('tab-inv-badge').classList.toggle('hidden', !count);
    $('inv-count').textContent = count + ' ' + plural(count, 'предмет', 'предмета', 'предметов');
  }

  async function refreshUser() {
    try {
      state.user = await api('/api/user/' + USER_ID);
      renderHeader();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  /* ---------- Tabs ---------- */

  function switchView(view) {
    state.view = view;
    $('screen-cases').classList.toggle('hidden', view !== 'cases');
    $('screen-collection').classList.toggle('hidden', view !== 'collection');
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.classList.toggle('active', tab.getAttribute('data-view') === view);
    });
    window.scrollTo({ top: 0 });
    if (view === 'collection') refreshInventory();
  }

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      hapticImpact();
      switchView(tab.getAttribute('data-view'));
    });
  });

  /* ---------- Cases screen ---------- */

  function renderGrid() {
    const grid = $('case-grid');
    grid.innerHTML = '';
    $('cases-count').textContent = state.cases.length + ' ' +
      plural(state.cases.length, 'кейс', 'кейса', 'кейсов');
    state.cases.forEach((kase) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'case-card';
      card.style.setProperty('--accent', kase.accent || RARITY_COLORS['Mil-Spec']);
      const img = skinImage(kase, '256fx256f', 'case-img', kase.name);
      const name = document.createElement('div');
      name.className = 'case-name';
      name.textContent = kase.name;
      const price = document.createElement('div');
      price.className = 'case-price' + (kase.price === 0 ? ' free' : '');
      price.innerHTML = kase.price === 0
        ? 'Бесплатно &middot; 24ч'
        : escapeHtml(money(kase.price));
      card.appendChild(img);
      card.appendChild(name);
      card.appendChild(price);
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

  function updateFreeCaseButton() {
    const button = $('btn-open-case');
    const remaining = cooldownRemainingMs();
    if (remaining > 0) {
      button.disabled = true;
      button.textContent = 'Бесплатный кейс через ' + formatDuration(remaining);
    } else {
      button.disabled = false;
      button.textContent = 'Открыть бесплатно';
    }
  }

  function openCaseModal(kase) {
    stopCooldownTimer();
    $('case-modal-name').textContent = kase.name;
    $('case-modal-sub').textContent = kase.price === 0
      ? 'Бесплатно раз в ' + (kase.cooldown_hours || 24) + ' часов'
      : kase.items.length + ' ' + plural(kase.items.length, 'предмет', 'предмета', 'предметов') +
        ' &middot; шанс на нож';
    const heroImg = $('case-modal-img');
    heroImg.src = cdn(kase.image, '256fx256f');
    heroImg.onerror = () => { heroImg.onerror = null; heroImg.src = FALLBACK_IMG; };

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
      group.style.setProperty('--rc-group', color);
      group.textContent = RARITY_RU[rarity] || rarity;
      pool.appendChild(group);
      items.sort((a, b) => b.base_price - a.base_price).forEach((item) => {
        const row = document.createElement('div');
        row.className = 'pool-row';
        row.style.setProperty('--rc', color);
        row.appendChild(skinImage(item, '128fx128f', '', item.name));
        const nm = document.createElement('span');
        nm.className = 'nm';
        nm.textContent = item.name;
        const pr = document.createElement('span');
        pr.className = 'pr';
        pr.textContent = money(item.base_price);
        row.appendChild(nm);
        row.appendChild(pr);
        pool.appendChild(row);
      });
    });

    const button = $('btn-open-case');
    if (kase.price === 0) {
      updateFreeCaseButton();
      cooldownTimer = setInterval(() => {
        if ($('case-modal').classList.contains('hidden')) { stopCooldownTimer(); return; }
        updateFreeCaseButton();
      }, 1000);
    } else {
      const affordable = state.user && state.user.balance >= kase.price;
      button.disabled = !affordable;
      button.textContent = affordable
        ? 'Открыть за ' + money(kase.price)
        : 'Не хватает ' + money(kase.price - (state.user ? state.user.balance : 0));
    }
    button.onclick = () => { if (!button.disabled) openCase(kase); };
    showModal('case-modal');
  }

  /* ---------- Roulette ---------- */

  function buildReelItem(item, isWinner) {
    const color = RARITY_COLORS[item.rarity] || '#8b93a7';
    const el = document.createElement('div');
    el.className = 'reel-item' + (isWinner ? ' win' : '');
    el.style.setProperty('--rc', color);
    el.appendChild(skinImage(item, '256fx256f', '', item.name));
    const name = document.createElement('span');
    name.className = 'ri-name';
    name.textContent = (item.is_stat_trak ? 'ST™ ' : '') + item.name;
    el.appendChild(name);
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
      const jitter = (Math.random() - 0.5) * (REEL_CARD_W * 0.5);
      const winnerCenter =
        targetIndex * (REEL_CARD_W + REEL_GAP) + REEL_CARD_W / 2 + jitter;
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
    $('reel-title').textContent = 'Открываем: ' + kase.name;
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

  /* ---------- Result modal ---------- */

  function showResult(winner) {
    hideModal('reel-modal');
    const color = RARITY_COLORS[winner.rarity] || '#8b93a7';
    const card = $('drop-card');
    card.style.setProperty('--rc', color);
    card.innerHTML = '';

    const rarity = document.createElement('div');
    rarity.className = 'drop-rarity';
    rarity.textContent = RARITY_RU[winner.rarity] || winner.rarity;
    card.appendChild(rarity);
    card.appendChild(skinImage(winner, '360fx360f', 'drop-img', winner.name));

    const name = document.createElement('div');
    name.className = 'drop-name';
    name.innerHTML = (winner.is_stat_trak ? '<span class="st-badge">StatTrak&trade;</span>' : '') +
      escapeHtml(winner.name);
    card.appendChild(name);

    const wear = document.createElement('div');
    wear.className = 'drop-wear';
    wear.textContent = wearRu(winner.wear);
    card.appendChild(wear);

    const fl = document.createElement('div');
    fl.className = 'drop-float';
    fl.textContent = 'float ' + Number(winner.wear_float).toFixed(4);
    card.appendChild(fl);

    const price = document.createElement('div');
    price.className = 'drop-price';
    price.textContent = money(winner.price);
    card.appendChild(price);

    const sellButton = $('btn-sell');
    sellButton.disabled = false;
    sellButton.textContent = 'Продать за ' + money(winner.price);
    sellButton.onclick = () => sellItem(winner.item_id, winner.price, async () => {
      hideModal('result-modal');
    });

    $('btn-keep').onclick = () => {
      hideModal('result-modal');
      toast(winner.name + ' — в коллекцию', 'success');
      refreshUser();
    };
    showModal('result-modal');
  }

  /* ---------- Selling ---------- */

  async function sellItem(itemId, expectedPrice, done) {
    try {
      const result = await api('/api/items/sell', {
        method: 'POST',
        body: JSON.stringify({ user_id: USER_ID, item_id: itemId }),
      });
      animateBalance(result.new_balance);
      hapticSuccess();
      toast('+' + money(expectedPrice) + ' зачислено на баланс', 'success');
      await done();
      await refreshUser();
    } catch (err) {
      hapticError();
      toast(err.message, 'error');
    }
  }

  /* ---------- Collection screen ---------- */

  async function refreshInventory() {
    try {
      const payload = await api('/api/inventory/' + USER_ID);
      state.inventory = payload.items;
      renderInventory();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  function renderInventory() {
    const items = state.inventory;
    const grid = $('inv-grid');
    grid.innerHTML = '';
    const empty = $('inv-empty');
    const summary = $('vault-summary');
    empty.classList.toggle('hidden', items.length > 0);
    summary.classList.toggle('hidden', items.length === 0);
    grid.classList.toggle('hidden', items.length === 0);

    setInventoryBadge(items.length);

    const total = items.reduce((sum, item) => sum + (Number(item.price) || 0), 0);
    $('vault-total').textContent = money(total);

    items.forEach((item) => {
      const color = RARITY_COLORS[item.rarity] || '#8b93a7';
      const card = document.createElement('div');
      card.className = 'skin-card';
      card.style.setProperty('--rc', color);

      const visual = document.createElement('div');
      visual.className = 'skin-visual';
      visual.appendChild(skinImage(item, '256fx256f', '', item.name));
      if (item.is_stat_trak) {
        const st = document.createElement('span');
        st.className = 'st-marker';
        st.textContent = 'StatTrak™';
        visual.appendChild(st);
      }
      const wear = document.createElement('span');
      wear.className = 'wear-badge wear-' + wearShort(item.wear);
      wear.textContent = wearShort(item.wear);
      wear.title = wearRu(item.wear);
      visual.appendChild(wear);
      card.appendChild(visual);

      const body = document.createElement('div');
      body.className = 'skin-body';
      const name = document.createElement('div');
      name.className = 'skin-name';
      name.textContent = item.name;
      body.appendChild(name);

      const meta = document.createElement('div');
      meta.className = 'skin-meta';
      const price = document.createElement('span');
      price.className = 'skin-price';
      price.textContent = money(item.price);
      const sell = document.createElement('button');
      sell.type = 'button';
      sell.className = 'btn-sell';
      sell.textContent = 'Продать';
      sell.addEventListener('click', () => {
        sell.disabled = true;
        card.classList.add('sold-out');
        sellItem(item.item_id, item.price, async () => {
          state.inventory = state.inventory.filter((el) => el.item_id !== item.item_id);
          setTimeout(renderInventory, 280);
        });
      });
      meta.appendChild(price);
      meta.appendChild(sell);
      body.appendChild(meta);
      card.appendChild(body);

      grid.appendChild(card);
    });
  }

  $('btn-go-cases').addEventListener('click', () => switchView('cases'));

  /* ---------- Modals ---------- */

  function showModal(id) { $(id).classList.remove('hidden'); }
  function hideModal(id) { $(id).classList.add('hidden'); }

  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => hideModal(button.getAttribute('data-close')));
  });
  document.querySelectorAll('.modal-backdrop').forEach((backdrop) => {
    backdrop.addEventListener('click', (event) => {
      if (event.target !== backdrop) return;
      const id = backdrop.getAttribute('id');
      if (id === 'reel-modal') return;
      hideModal(id);
    });
  });

  /* ---------- Init ---------- */

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
