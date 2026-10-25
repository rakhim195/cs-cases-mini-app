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
    'Special': '#ffd700',
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
  const REEL_MS = 7000;
  const REEL_CARD_W = 120;
  const REEL_GAP = 10;
  const REFERRAL_LINK_TEXT = 'Заходи и забирай 25 бесплатных попыток!';
  const BRAG_HEADER_NOTE = 'CS:GO Case Battle • Игра про топовые скины';
  const FALLBACK_IMG =
    'data:image/svg+xml;utf8,' +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">' +
      '<rect width="120" height="80" rx="10" fill="#16203c"/>' +
      '<text x="60" y="46" text-anchor="middle" font-size="26" fill="#3a4a75">?</text>' +
      '</svg>'
    );

  const state = {
    user: null, cases: [], inventory: [], view: 'cases', busy: false,
    botUsername: '', lastWinner: null,
  };

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

  // skin_id -> catalog entry, so inventory rows can resolve CDN images even
  // when the API payload omits them.
  const skinImageIndex = new Map();

  function indexSkins() {
    state.cases.forEach((kase) => {
      kase.items.forEach((item) => {
        if (!skinImageIndex.has(item.skin_id)) {
          skinImageIndex.set(item.skin_id, item);
        }
      });
    });
  }

  function skinImage(item, size, cls, alt) {
    const img = document.createElement('img');
    img.className = cls || '';
    img.alt = alt || '';
    img.loading = 'lazy';
    img.decoding = 'async';
    const meta = item.image ? item : skinImageIndex.get(item.skin_id);
    img.src = cdn(meta && meta.image, size || '256fx256f');
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
    $('screen-battle').classList.toggle('hidden', view !== 'battle');
    $('screen-upgrade').classList.toggle('hidden', view !== 'upgrade');
    $('screen-collection').classList.toggle('hidden', view !== 'collection');
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.classList.toggle('active', tab.getAttribute('data-view') === view);
    });
    window.scrollTo({ top: 0 });
    if (view === 'collection') refreshInventory();
    if (view === 'upgrade') initUpgradeScreen();
    if (view === 'battle') initBattleScreen();
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

      if (kase.tags && kase.tags.length) {
        const chip = document.createElement('span');
        chip.className = 'case-tag';
        chip.textContent = kase.tags[0];
        card.appendChild(chip);
      }

      const visual = document.createElement('div');
      visual.className = 'case-visual';
      visual.appendChild(skinImage(kase, '384fx384f', 'case-img', kase.name));
      card.appendChild(visual);

      const name = document.createElement('div');
      name.className = 'case-name';
      name.textContent = kase.hype_title || kase.name;
      card.appendChild(name);

      const sub = document.createElement('div');
      sub.className = 'case-subtitle';
      sub.textContent = kase.name;
      card.appendChild(sub);

      const price = document.createElement('span');
      price.className = 'case-price' + (kase.price === 0 ? ' free' : '');
      price.textContent = kase.price === 0 ? 'БЕСПЛАТНО • 24Ч' : money(kase.price);
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
    el.className = 'reel-item' +
      (isWinner ? ' win' : '') +
      (isElite(item.rarity) ? ' ultra' : '');
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

  function spinReel(reel, winnerIndex) {
    return new Promise((resolve) => {
      const track = $('reel-track');
      const windowEl = $('reel-window');
      const targetIndex =
        typeof winnerIndex === 'number' && winnerIndex >= 0 && winnerIndex < reel.length
          ? winnerIndex
          : reel.length - 1;
      track.innerHTML = '';
      reel.forEach((item, index) => {
        track.appendChild(buildReelItem(item, index === targetIndex));
      });

      // Jitter up to ~±40px so the winner never lands dead-center to the
      // exact pixel — the stop feels like physics, not a script.
      const jitter = (Math.random() - 0.5) * (REEL_CARD_W * 0.66);
      const winnerCenter =
        REEL_GAP + // track's left padding
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
      await spinReel(result.reel, result.winner_index);
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

  /* ---------- Result (drop) modal ---------- */

  function isElite(rarity) {
    return rarity === 'Covert' || rarity === 'Special';
  }

  // Knives and gloves both share the "Special" rarity — give them a legend label.
  function rarityRuLabel(item) {
    if (item.rarity !== 'Special') return RARITY_RU[item.rarity] || item.rarity;
    const en = (item.name_en || '').toLowerCase();
    const ru = (item.name || '').toLowerCase();
    if (en.includes('knife') || ru.includes('нож')) return 'Легендарный нож';
    if (en.includes('gloves') || en.includes('hand wraps') || ru.includes('перчат')) {
      return 'Легендарные перчатки';
    }
    return '★ Экстраординарное';
  }

  function spawnParticles(container, count) {
    for (let i = 0; i < count; i += 1) {
      const dot = document.createElement('span');
      dot.className = 'particle';
      dot.style.left = (4 + Math.random() * 92) + '%';
      dot.style.animationDuration = (1.6 + Math.random() * 1.8) + 's';
      dot.style.animationDelay = (Math.random() * 2.2) + 's';
      const size = 3 + Math.random() * 4;
      dot.style.width = size + 'px';
      dot.style.height = size + 'px';
      container.appendChild(dot);
    }
  }

  function countUpPrice(el, target) {
    const started = performance.now();
    const duration = 900;
    const step = (now) => {
      const k = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = money(target * eased);
      if (k < 1) requestAnimationFrame(step);
      else el.textContent = money(target);
    };
    requestAnimationFrame(step);
  }

  function showResult(winner) {
    hideModal('reel-modal');
    state.lastWinner = winner;
    const color = RARITY_COLORS[winner.rarity] || '#8b93a7';
    const elite = isElite(winner.rarity);
    const card = $('drop-card');
    card.style.setProperty('--rc', color);
    card.classList.toggle('elite', elite);
    card.innerHTML = '';

    const rarity = document.createElement('div');
    rarity.className = 'drop-rarity';
    rarity.textContent = rarityRuLabel(winner);
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
    card.appendChild(price);
    countUpPrice(price, Number(winner.price) || 0);

    if (elite) {
      spawnParticles(card, 22);
      hapticSuccess();
    }

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

  /* ---------- Brag (share) modal ---------- */

  function referralLink() {
    if (state.botUsername) {
      return 'https://t.me/' + state.botUsername + '?start=r' + USER_ID;
    }
    return window.location.origin + window.location.pathname + '?user_id=' + USER_ID;
  }

  function bragText(winner) {
    return 'Я выбил скин ' + winner.name + ' (' + money(winner.price) + ')';
  }

  function openShareModal(winner) {
    const color = RARITY_COLORS[winner.rarity] || '#8b93a7';
    const visual = $('brag-visual');
    visual.style.setProperty('--rc', color);
    $('brag-text').textContent = bragText(winner);
    $('brag-rarity').textContent = rarityRuLabel(winner);
    const img = $('brag-img');
    img.src = cdn(winner.image, '360fx360f');
    img.onerror = () => { img.onerror = null; img.src = FALLBACK_IMG; };
    showModal('share-modal');
  }

  async function shareToStory(winner) {
    await shareItemToStory(winner);
  }

  // Story caption always carries the personal referral (?start=r<USER_ID>)
  // so every friend who joins pays the sharer 5% of their drops.
  function storyCaption(item) {
    return 'Выбил «' + item.name + '» (' + money(item.price) +
      ') в @KeysikAppBot! Открой свой кейс по ссылке: ' + referralLink();
  }

  async function shareItemToStory(item) {
    if (!item) return;
    hapticImpact();
    const caption = storyCaption(item);
    if (tg && typeof tg.shareToStory === 'function') {
      try {
        tg.shareToStory({ media: cdn(item.image, '360fx360f'), text: caption });
        return;
      } catch (err) { /* fall through to the canvas card */ }
    }
    // No native shareToStory (browser preview or old client): render a
    // high-contrast story card and hand it over as a PNG download.
    try {
      const dataUrl = await buildStoryCard(item);
      const link = document.createElement('a');
      link.href = dataUrl;
      link.download = 'case-battle-' + (item.skin_id || 'drop') + '.png';
      document.body.appendChild(link);
      link.click();
      link.remove();
      toast('Карточка сохранена — выложи её в Stories!', 'success');
    } catch (err) {
      toast('Не удалось собрать карточку для Stories', 'error');
    }
    try {
      await navigator.clipboard.writeText(caption);
    } catch (err) { /* clipboard is best-effort */ }
  }

  function storyFont(px, weight) {
    return (weight || 700) + ' ' + px + 'px "Chakra Petch", Inter, sans-serif';
  }

  // 720x1280 portrait card: rarity glow, skin render, price, bot CTA.
  function buildStoryCard(item) {
    return new Promise((resolve, reject) => {
      const W = 720;
      const H = 1280;
      const canvas = document.createElement('canvas');
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext('2d');
      const color = RARITY_COLORS[item.rarity] || '#8b93a7';

      const bg = ctx.createLinearGradient(0, 0, 0, H);
      bg.addColorStop(0, '#141d38');
      bg.addColorStop(1, '#070b16');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);
      const glow = ctx.createRadialGradient(W / 2, 500, 40, W / 2, 500, 430);
      glow.addColorStop(0, color + '59');
      glow.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, W, H);

      ctx.textAlign = 'center';
      ctx.fillStyle = '#ffc233';
      ctx.font = storyFont(46);
      ctx.fillText('CS CASE BATTLE', W / 2, 150);
      ctx.fillStyle = '#8b93a7';
      ctx.font = '600 30px Inter, sans-serif';
      ctx.fillText('выбил в @KeysikAppBot', W / 2, 200);

      const finish = (skin) => {
        if (skin && skin.width) {
          const k = Math.min(560 / skin.width, 380 / skin.height);
          const w = skin.width * k;
          const h = skin.height * k;
          ctx.drawImage(skin, (W - w) / 2, 500 - h / 2, w, h);
        }
        const name = (item.is_stat_trak ? 'StatTrak™ ' : '') + item.name;
        ctx.fillStyle = '#ffffff';
        let size = 42;
        ctx.font = storyFont(size);
        while (ctx.measureText(name).width > 640 && size > 22) {
          size -= 2;
          ctx.font = storyFont(size);
        }
        ctx.fillText(name, W / 2, 742);
        ctx.fillStyle = color;
        ctx.font = storyFont(26, 700);
        ctx.fillText((RARITY_RU[item.rarity] || item.rarity).toUpperCase(), W / 2, 796);
        ctx.fillStyle = '#ffc233';
        ctx.font = storyFont(76);
        ctx.fillText(money(item.price), W / 2, 906);

        const ctaX = W / 2 - 250;
        const ctaY = 986;
        const cta = ctx.createLinearGradient(ctaX, ctaY, ctaX + 500, ctaY + 96);
        cta.addColorStop(0, '#ffe27a');
        cta.addColorStop(1, '#ff8a00');
        ctx.fillStyle = cta;
        if (ctx.roundRect) {
          ctx.beginPath();
          ctx.roundRect(ctaX, ctaY, 500, 96, 48);
          ctx.fill();
        } else {
          ctx.fillRect(ctaX, ctaY, 500, 96);
        }
        ctx.fillStyle = '#241300';
        ctx.font = storyFont(36);
        ctx.fillText('ОТКРОЙ СВОЙ КЕЙС', W / 2, ctaY + 60);
        ctx.fillStyle = '#8b93a7';
        ctx.font = '600 28px Inter, sans-serif';
        ctx.fillText('t.me/' + (state.botUsername || 'KeysikAppBot'), W / 2, 1160);

        try {
          resolve(canvas.toDataURL('image/png'));
        } catch (err) {
          reject(err);
        }
      };

      const skin = new Image();
      skin.crossOrigin = 'anonymous';
      skin.onload = () => finish(skin);
      skin.onerror = () => finish(null);
      skin.src = cdn(item.image, '512fx512f');
    });
  }

  function shareToFriend(winner) {
    const text = 'Я выбил ' + winner.name + ' за ' + money(winner.price) + '! ' +
      REFERRAL_LINK_TEXT;
    const url = 'https://t.me/share/url?url=' + encodeURIComponent(referralLink()) +
      '&text=' + encodeURIComponent(text);
    if (tg && typeof tg.openTelegramLink === 'function') tg.openTelegramLink(url);
    else window.open(url, '_blank');
  }

  $('btn-brag').addEventListener('click', () => {
    if (state.lastWinner) {
      hapticImpact();
      openShareModal(state.lastWinner);
    }
  });
  $('btn-story').addEventListener('click', () => {
    if (state.lastWinner) shareToStory(state.lastWinner);
  });
  $('btn-friend').addEventListener('click', () => {
    if (state.lastWinner) shareToFriend(state.lastWinner);
  });
  $('btn-result-story').addEventListener('click', () => {
    shareItemToStory(state.lastWinner);
  });

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
      const storyBtn = document.createElement('button');
      storyBtn.type = 'button';
      storyBtn.className = 'btn-inv-story';
      storyBtn.title = 'Поделиться в Stories';
      storyBtn.textContent = '📸';
      storyBtn.addEventListener('click', () => {
        shareItemToStory(Object.assign({}, item, {
          image: (catalogSkin(item.skin_id) || {}).image,
        }));
      });
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
      meta.appendChild(storyBtn);
      meta.appendChild(sell);
      body.appendChild(meta);
      card.appendChild(body);

      grid.appendChild(card);
    });
  }

  $('btn-go-cases').addEventListener('click', () => switchView('cases'));

  /* ---------- Upgrade screen ---------- */

  const UPGRADE_FACTOR = 0.95;
  const UPGRADE_MIN = 0.01;
  const UPGRADE_MAX = 0.80;
  const UPGRADE_WHEEL_R = 84;
  const UPGRADE_SPIN_MS = 4200;

  const upgradeState = {
    targets: [],
    selected: null,
    target: null,
    spinning: false,
    pointerTurns: 0,
    pointerAngle: 0,
  };

  // Must mirror services/upgrade.py success_chance exactly.
  function upgradeChance() {
    if (!upgradeState.selected || !upgradeState.target) return null;
    const sel = Number(upgradeState.selected.price);
    const tgt = Number(upgradeState.target.base_price);
    if (!(sel > 0) || !(tgt > 0)) return null;
    return Math.min(UPGRADE_MAX, Math.max(UPGRADE_MIN, (sel / tgt) * UPGRADE_FACTOR));
  }

  function catalogSkin(skinId) {
    return upgradeState.targets.find((t) => t.skin_id === skinId) || null;
  }

  async function initUpgradeScreen() {
    if (!upgradeState.targets.length) {
      try {
        const payload = await api('/api/upgrade/catalog');
        upgradeState.targets = payload.items;
      } catch (err) {
        toast(err.message, 'error');
      }
    }
    await refreshInventory();
    renderUpgradeSlots();
  }

  function fillUpgradeSlot(side, item, placeholder) {
    const slot = $(side === 'left' ? 'upg-slot-left' : 'upg-slot-right');
    const circle = slot.querySelector('.upg-slot-circle');
    const img = circle.querySelector('img');
    const meta = item && catalogSkin(item.skin_id);
    slot.style.setProperty('--rc', RARITY_COLORS[item ? item.rarity : 'Mil-Spec'] || '#8b93a7');
    if (item) {
      const src = item.image || (meta && meta.image);
      img.src = src ? cdn(src, '256fx256f') : FALLBACK_IMG;
      img.onerror = () => { img.onerror = null; img.src = FALLBACK_IMG; };
      img.classList.remove('hidden');
      circle.classList.remove('empty');
      slot.querySelector('.upg-slot-name').textContent =
        (item.is_stat_trak ? 'ST™ ' : '') + item.name;
      const value = item.price !== undefined ? item.price : item.base_price;
      slot.querySelector('.upg-slot-price').textContent = money(value);
    } else {
      img.classList.add('hidden');
      img.removeAttribute('src');
      circle.classList.add('empty');
      slot.querySelector('.upg-slot-name').textContent =
        side === 'left' ? 'Твой скин' : 'Цель';
      slot.querySelector('.upg-slot-price').textContent = placeholder;
    }
  }

  function setWheelArc(chance) {
    const C = 2 * Math.PI * UPGRADE_WHEEL_R;
    $('upg-arc').style.strokeDasharray = (chance * C) + ' ' + C;
  }

  function wheelStatus(main, sub) {
    $('upg-wheel-status').textContent = main;
    $('upg-wheel-sub').textContent = sub;
  }

  function renderUpgradeSlots() {
    fillUpgradeSlot('left', upgradeState.selected, 'выбери из инвентаря');
    fillUpgradeSlot('right', upgradeState.target, 'выбери скин');
    const chance = upgradeChance();
    const button = $('btn-upgrade');
    if (chance === null) {
      $('upg-percent').textContent = '—';
      $('upg-multiplier').textContent = '—';
      setWheelArc(0);
      wheelStatus('?', 'выбери скины');
      button.disabled = true;
      button.textContent = 'Апгрейд';
    } else {
      const percent = (chance * 100).toFixed(1);
      const mult = Number(upgradeState.target.base_price) / Number(upgradeState.selected.price);
      $('upg-percent').textContent = percent + '%';
      $('upg-multiplier').textContent = '×' + mult.toFixed(1);
      setWheelArc(chance);
      wheelStatus(percent + '%', 'шанс успеха');
      button.disabled = upgradeState.spinning;
      button.textContent = 'Апгрейд • ' + percent + '%';
    }
  }

  function openPicker(kind) {
    if (upgradeState.spinning) return;
    const isInv = kind === 'inv';
    const listEl = $(isInv ? 'pick-inv-list' : 'pick-target-list');
    listEl.innerHTML = '';
    const rows = isInv ? state.inventory : upgradeState.targets;
    if (!rows.length) {
      const note = document.createElement('div');
      note.className = 'pick-empty';
      note.textContent = isInv
        ? 'Инвентарь пуст — открой кейс, чтобы получить скин'
        : 'Каталог загружается…';
      listEl.appendChild(note);
      showModal(isInv ? 'pick-inv-modal' : 'pick-target-modal');
      return;
    }
    rows.forEach((item) => {
      const meta = catalogSkin(item.skin_id);
      const value = isInv ? item.price : item.base_price;
      const current = isInv
        ? upgradeState.selected && upgradeState.selected.item_id === item.item_id
        : upgradeState.target && upgradeState.target.skin_id === item.skin_id;
      const row = document.createElement('div');
      row.className = 'pool-row pick-row' + (current ? ' current' : '');
      row.style.setProperty('--rc', RARITY_COLORS[item.rarity] || '#8b93a7');
      row.appendChild(skinImage(
        Object.assign({}, item, { image: item.image || (meta && meta.image) }),
        '128fx128f', '', item.name
      ));
      const nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = (item.is_stat_trak ? 'ST™ ' : '') + item.name;
      const pr = document.createElement('span');
      pr.className = 'pr';
      pr.textContent = money(value);
      row.appendChild(nm);
      row.appendChild(pr);
      row.addEventListener('click', () => {
        hapticImpact();
        if (isInv) upgradeState.selected = item;
        else upgradeState.target = item;
        hideModal(isInv ? 'pick-inv-modal' : 'pick-target-modal');
        renderUpgradeSlots();
      });
      listEl.appendChild(row);
    });
    showModal(isInv ? 'pick-inv-modal' : 'pick-target-modal');
  }

  function animatePointerTo(degree) {
    return new Promise((resolve) => {
      const pointer = $('upg-pointer');
      upgradeState.pointerTurns += 5;
      const final = upgradeState.pointerTurns * 360 + degree;
      pointer.style.transition = 'none';
      pointer.style.transform = 'rotate(' + upgradeState.pointerAngle + 'deg)';
      void pointer.offsetWidth;
      pointer.style.transition =
        'transform ' + UPGRADE_SPIN_MS + 'ms cubic-bezier(0.12, 0.82, 0.16, 1)';
      pointer.style.transform = 'rotate(' + final + 'deg)';
      upgradeState.pointerAngle = final;
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        pointer.removeEventListener('transitionend', onEnd);
        resolve();
      };
      const onEnd = (event) => {
        if (event.propertyName === 'transform') finish();
      };
      pointer.addEventListener('transitionend', onEnd);
      setTimeout(finish, UPGRADE_SPIN_MS + 900);
    });
  }

  function applyUpgradeResult(result) {
    const wrap = $('upg-wheel-wrap');
    if (result.status === 'win') {
      wrap.classList.add('win');
      hapticSuccess();
      spawnParticles(wrap, 26);
      wheelStatus('ВЫИГРЫШ!', result.target_item.name);
      upgradeState.selected = result.target_item;
      toast('Апгрейд удался: ' + result.target_item.name, 'success');
    } else {
      wrap.classList.add('lose');
      hapticError();
      wheelStatus('ПРОИГРЫШ', 'скин сгорел');
      upgradeState.selected = null;
    }
    setTimeout(() => {
      wrap.classList.remove('win', 'lose');
      upgradeState.spinning = false;
      renderUpgradeSlots();
      refreshInventory();
      refreshUser();
    }, 1700);
  }

  async function spinUpgrade() {
    if (upgradeState.spinning || !upgradeState.selected || !upgradeState.target) return;
    upgradeState.spinning = true;
    const button = $('btn-upgrade');
    button.disabled = true;
    button.textContent = 'Крутим…';
    hapticImpact();
    try {
      const result = await api('/api/upgrade', {
        method: 'POST',
        body: JSON.stringify({
          user_id: USER_ID,
          selected_item_id: upgradeState.selected.item_id,
          target_skin_id: upgradeState.target.skin_id,
        }),
      });
      setWheelArc(result.chance);
      await animatePointerTo(result.roll_degree);
      applyUpgradeResult(result);
    } catch (err) {
      hapticError();
      toast(err.message, 'error');
      upgradeState.spinning = false;
      renderUpgradeSlots();
    }
  }

  $('upg-slot-left').addEventListener('click', () => openPicker('inv'));
  $('upg-slot-right').addEventListener('click', () => openPicker('target'));
  $('btn-upgrade').addEventListener('click', spinUpgrade);

  /* ---------- Daily bonus & streak ---------- */

  let dailyTimer = null;
  let dailyAutoShown = false;

  function stopDailyTimer() {
    if (dailyTimer) { clearInterval(dailyTimer); dailyTimer = null; }
  }

  function renderDailyModal(status) {
    const track = $('daily-track');
    track.innerHTML = '';
    $('daily-streak-count').textContent = status.streak;
    status.rewards.forEach((reward) => {
      const cell = document.createElement('div');
      const cellState = reward.day < status.day ? 'done'
        : reward.day === status.day ? 'current' : 'locked';
      cell.className = 'daily-cell ' + cellState;
      const dayEl = document.createElement('span');
      dayEl.className = 'dc-day';
      dayEl.textContent = cellState === 'done' ? '✓' : reward.day;
      const labelEl = document.createElement('span');
      labelEl.className = 'dc-label';
      labelEl.textContent = reward.label;
      cell.appendChild(dayEl);
      cell.appendChild(labelEl);
      track.appendChild(cell);
    });
    const button = $('btn-daily-claim');
    const countdown = $('daily-countdown');
    stopDailyTimer();
    if (status.can_claim) {
      button.disabled = false;
      button.textContent = 'Забрать: ' + status.rewards[status.day - 1].label;
      countdown.textContent = 'День ' + status.day + ' из 7 — бонус доступен!';
    } else {
      button.disabled = true;
      const tick = () => {
        const left = Math.max(0, new Date(status.next_claim_at).getTime() - Date.now());
        if (left <= 0) {
          stopDailyTimer();
          openDailyModal(true);
          return;
        }
        button.textContent = 'Бонус через ' + formatDuration(left);
      };
      tick();
      dailyTimer = setInterval(() => {
        if ($('daily-modal').classList.contains('hidden')) {
          stopDailyTimer();
          return;
        }
        tick();
      }, 1000);
      countdown.textContent = 'Следующий день стрика: ' + status.day + ' из 7';
    }
  }

  async function openDailyModal(force) {
    try {
      const status = await api('/api/daily/status/' + USER_ID);
      // Quiet probe for the session auto-open: show only when claimable.
      if (!force && !status.can_claim) return;
      renderDailyModal(status);
      showModal('daily-modal');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function claimDaily() {
    const button = $('btn-daily-claim');
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Забираем…';
    hapticImpact();
    try {
      const result = await api('/api/daily/claim', {
        method: 'POST',
        body: JSON.stringify({ user_id: USER_ID }),
      });
      hapticSuccess();
      if (result.drop) {
        hideModal('daily-modal');
        refreshUser();
        showResult(result.drop);
        return;
      }
      animateBalance(result.new_balance);
      toast('Бонус за день ' + result.day + ': +' + result.reward.label, 'success');
      const status = await api('/api/daily/status/' + USER_ID);
      renderDailyModal(status);
      refreshUser();
    } catch (err) {
      hapticError();
      toast(err.message, 'error');
      openDailyModal(true);
    }
  }

  $('btn-daily').addEventListener('click', () => {
    hapticImpact();
    openDailyModal(true);
  });
  $('btn-daily-claim').addEventListener('click', claimDaily);

  /* ---------- Case battles (1v1 / bot duels) ---------- */

  const battleState = {
    caseId: null,
    rounds: 2,
    vsBot: true,
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function battleCase() {
    return state.cases.find((k) => k.id === battleState.caseId) || null;
  }

  function updateBattleCost() {
    const kase = battleCase();
    const cost = kase ? kase.price * battleState.rounds : 0;
    $('battle-cost').textContent = 'Стоимость: ' + money(cost);
  }

  function renderBattleChips() {
    const wrap = $('battle-case-chips');
    wrap.innerHTML = '';
    state.cases
      .filter((k) => k.price > 0)
      .forEach((kase) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'battle-chip' + (kase.id === battleState.caseId ? ' active' : '');
        chip.style.setProperty('--accent', kase.accent || '#4b69ff');
        const img = document.createElement('img');
        img.src = cdn(kase.image, '128fx128f');
        img.alt = kase.name;
        chip.appendChild(img);
        const price = document.createElement('span');
        price.className = 'bc-price';
        price.textContent = kase.price === 0 ? 'FREE' : Math.round(kase.price) + ' ₽';
        chip.appendChild(price);
        chip.addEventListener('click', () => {
          hapticImpact();
          battleState.caseId = kase.id;
          renderBattleChips();
          updateBattleCost();
        });
        wrap.appendChild(chip);
      });
  }

  function renderLobby(battles) {
    const listEl = $('battle-lobby');
    listEl.innerHTML = '';
    $('battle-lobby-empty').classList.toggle('hidden', battles.length > 0);
    $('battle-lobby-count').textContent = battles.length + ' ' +
      plural(battles.length, 'лобби', 'лобби', 'лобби');
    battles.forEach((lobby) => {
      const card = document.createElement('div');
      card.className = 'battle-lobby-card';
      const img = document.createElement('img');
      img.src = cdn(lobby.case_image, '128fx128f');
      img.alt = lobby.case_name;
      const info = document.createElement('div');
      info.className = 'blc-info';
      const name = document.createElement('div');
      name.className = 'blc-name';
      name.textContent = lobby.creator_name;
      const meta = document.createElement('div');
      meta.className = 'blc-meta';
      meta.textContent = lobby.case_name + ' • ' + lobby.rounds + ' ' +
        plural(lobby.rounds, 'раунд', 'раунда', 'раундов') + ' • ' + money(lobby.cost);
      info.appendChild(name);
      info.appendChild(meta);
      const join = document.createElement('button');
      join.type = 'button';
      join.className = 'btn-primary blc-join';
      join.textContent = lobby.creator_id === USER_ID ? 'Открыть' : 'Войти';
      join.addEventListener('click', () => {
        if (lobby.creator_id === USER_ID) openExistingBattle(lobby.id);
        else joinBattle(lobby.id);
      });
      card.appendChild(img);
      card.appendChild(info);
      card.appendChild(join);
      listEl.appendChild(card);
    });
  }

  async function refreshLobby() {
    try {
      const payload = await api('/api/battles/active');
      renderLobby(payload.battles);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function initBattleScreen() {
    if (!battleState.caseId && state.cases.length) {
      battleState.caseId = state.cases.filter((k) => k.price > 0)[0].id;
    }
    renderBattleChips();
    updateBattleCost();
    refreshLobby();
  }

  async function createBattle() {
    const kase = battleCase();
    if (!kase || state.busy) return;
    state.busy = true;
    const button = $('btn-battle-create');
    button.disabled = true;
    button.textContent = 'Создаём…';
    hapticImpact();
    try {
      const result = await api('/api/battles/create', {
        method: 'POST',
        body: JSON.stringify({
          user_id: USER_ID,
          case_id: battleState.caseId,
          rounds: battleState.rounds,
          is_bot_opponent: battleState.vsBot,
        }),
      });
      animateBalance(result.new_balance);
      if (result.battle.status === 'finished') {
        await playBattleArena(result, USER_ID);
      } else {
        toast('Битва создана — ждём соперника', 'success');
        refreshLobby();
      }
    } catch (err) {
      hapticError();
      toast(err.message, 'error');
    } finally {
      state.busy = false;
      button.disabled = false;
      button.textContent = 'Создать битву';
    }
  }

  async function joinBattle(battleId) {
    if (state.busy) return;
    state.busy = true;
    hapticImpact();
    try {
      const result = await api('/api/battles/' + battleId + '/join', {
        method: 'POST',
        body: JSON.stringify({ user_id: USER_ID }),
      });
      animateBalance(result.new_balance);
      await playBattleArena(result, USER_ID);
      refreshLobby();
    } catch (err) {
      hapticError();
      toast(err.message, 'error');
    } finally {
      state.busy = false;
    }
  }

  async function openExistingBattle(battleId) {
    try {
      const result = await api('/api/battles/' + battleId + '/state');
      if (result.battle.status === 'finished') {
        await playBattleArena(result, USER_ID);
        refreshLobby();
      } else {
        toast('Соперник ещё не найден', 'success');
      }
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  function arenaDropCell() {
    const cell = document.createElement('div');
    cell.className = 'arena-drop spinning';
    return cell;
  }

  // Round-by-round synchronized reveal: both cells whirl through the case
  // pool, then settle on the real drop together.
  async function playBattleArena(statePayload, viewerId) {
    const b = statePayload.battle;
    const viewerIsP1 = b.creator_id === viewerId;
    $('arena-title').textContent = 'Битва: ' + b.case_name;
    $('arena-name-p1').textContent = viewerIsP1 ? 'Ты' : b.creator_name;
    $('arena-name-p2').textContent = viewerIsP1
      ? (b.is_bot ? 'Бот Кейсик' : b.opponent_name)
      : 'Ты';
    const p1Cells = [];
    const p2Cells = [];
    const p1Wrap = $('arena-drops-p1');
    const p2Wrap = $('arena-drops-p2');
    p1Wrap.innerHTML = '';
    p2Wrap.innerHTML = '';
    $('arena-sum-p1').textContent = '0 ₽';
    $('arena-sum-p2').textContent = '0 ₽';
    $('arena-col-p1').classList.remove('win', 'lose');
    $('arena-col-p2').classList.remove('win', 'lose');
    showModal('battle-arena-modal');

    const kase = state.cases.find((k) => k.id === b.case_id);
    const pool = kase ? kase.items : [];
    let sumP1 = 0;
    let sumP2 = 0;

    for (const round of statePayload.rounds) {
      const p1Cell = arenaDropCell();
      const p2Cell = arenaDropCell();
      p1Wrap.appendChild(p1Cell);
      p2Wrap.appendChild(p2Cell);
      p1Cells.push(p1Cell);
      p2Cells.push(p2Cell);
      hapticImpact();
      // Synchronized whirl on both sides.
      const spinner = setInterval(() => {
        const randomItem = pool[Math.floor(Math.random() * pool.length)];
        const randomItem2 = pool[Math.floor(Math.random() * pool.length)];
        for (const [cell, item] of [[p1Cell, randomItem], [p2Cell, randomItem2]]) {
          cell.innerHTML = '';
          if (item && item.image) {
            const img = document.createElement('img');
            img.src = cdn(item.image, '128fx128f');
            cell.appendChild(img);
          }
        }
      }, 90);
      await sleep(1100);
      clearInterval(spinner);
      // Settle both cells on the actual drops.
      settleCell(p1Cell, round.p1);
      settleCell(p2Cell, round.p2);
      sumP1 += round.p1 ? round.p1.price : 0;
      sumP2 += round.p2 ? round.p2.price : 0;
      $('arena-sum-p1').textContent = money(sumP1);
      $('arena-sum-p2').textContent = money(sumP2);
      await sleep(700);
    }

    await sleep(500);
    const viewerWon = b.winner_id === viewerId;
    const draw = b.winner_id === null;
    if (!draw) {
      (viewerIsP1 ? $('arena-col-p1') : $('arena-col-p2'))
        .classList.add(viewerWon ? 'win' : 'lose');
      (viewerIsP1 ? $('arena-col-p2') : $('arena-col-p1'))
        .classList.add(viewerWon ? 'lose' : 'win');
    }
    hapticSuccess();
    await sleep(900);
    hideModal('battle-arena-modal');
    showBattleResult(statePayload, viewerId, viewerIsP1, viewerWon, draw);
  }

  function settleCell(cell, drop) {
    cell.classList.remove('spinning');
    cell.classList.add('revealed');
    cell.innerHTML = '';
    if (!drop) {
      cell.textContent = '—';
      return;
    }
    cell.style.setProperty('--rc', RARITY_COLORS[drop.rarity] || '#8b93a7');
    if (drop.image) {
      const img = document.createElement('img');
      img.src = cdn(drop.image, '256fx256f');
      img.alt = drop.name;
      cell.appendChild(img);
    }
    const price = document.createElement('span');
    price.className = 'ad-price';
    price.textContent = money(drop.price);
    cell.appendChild(price);
  }

  function showBattleResult(statePayload, viewerId, viewerIsP1, viewerWon, draw) {
    const b = statePayload.battle;
    const title = $('battle-result-title');
    if (draw) {
      title.textContent = 'Ничья — скины остались у вас';
      title.style.color = '#8b93a7';
    } else if (viewerWon) {
      title.textContent = '🏆 Победа! Забирай всё';
      title.style.color = '#ffc233';
    } else {
      title.textContent = '💀 Поражение';
      title.style.color = '#eb4b4b';
    }
    const viewerTotal = viewerIsP1 ? b.total_p1_value : b.total_p2_value;
    const otherTotal = viewerIsP1 ? b.total_p2_value : b.total_p1_value;
    const otherName = viewerIsP1
      ? (b.is_bot ? 'Бот Кейсик' : b.opponent_name)
      : b.creator_name;
    $('battle-result-totals').textContent =
      'Ты: ' + money(viewerTotal) + ' • ' + otherName + ': ' + money(otherTotal);

    const skinsEl = $('battle-result-skins');
    skinsEl.innerHTML = '';
    // Won skins = every drop on the table when the viewer takes all.
    const wonSkins = viewerWon
      ? statePayload.rounds.flatMap((r) => [r.p1, r.p2]).filter(Boolean)
      : [];
    if (draw) {
      const own = statePayload.rounds
        .map((r) => (viewerIsP1 ? r.p1 : r.p2))
        .filter(Boolean);
      own.forEach((drop) => skinsEl.appendChild(resultSkinCard(drop)));
    } else if (viewerWon) {
      wonSkins.forEach((drop) => skinsEl.appendChild(resultSkinCard(drop)));
    } else {
      const note = document.createElement('div');
      note.className = 'battle-lose-note';
      note.textContent = 'Скины ушли сопернику. Реванш?';
      skinsEl.appendChild(note);
    }
    showModal('battle-result-modal');
  }

  function resultSkinCard(drop) {
    const card = document.createElement('div');
    card.className = 'brs-card';
    card.style.setProperty('--rc', RARITY_COLORS[drop.rarity] || '#8b93a7');
    if (drop.image) {
      const img = document.createElement('img');
      img.src = cdn(drop.image, '256fx256f');
      img.alt = drop.name;
      card.appendChild(img);
    }
    const name = document.createElement('span');
    name.className = 'brs-name';
    name.textContent = (drop.is_stat_trak ? 'ST™ ' : '') + drop.name;
    const price = document.createElement('span');
    price.className = 'brs-price';
    price.textContent = money(drop.price);
    card.appendChild(name);
    card.appendChild(price);
    return card;
  }

  $('btn-battle-create').addEventListener('click', createBattle);
  document.querySelectorAll('#battle-rounds-seg button').forEach((btn) => {
    btn.addEventListener('click', () => {
      hapticImpact();
      battleState.rounds = Number(btn.getAttribute('data-rounds'));
      document.querySelectorAll('#battle-rounds-seg button').forEach((b2) => {
        b2.classList.toggle('active', b2 === btn);
      });
      updateBattleCost();
    });
  });
  $('battle-vs-bot').addEventListener('change', (event) => {
    battleState.vsBot = event.target.checked;
  });
  $('btn-battle-claim').addEventListener('click', () => {
    hapticSuccess();
    hideModal('battle-result-modal');
    refreshUser();
    refreshInventory();
  });

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
        api('/api/config').catch(() => ({ bot_username: '' })),
      ]);
      state.cases = results[0].cases;
      state.user = results[1];
      state.botUsername = results[2].bot_username || '';
      indexSkins();
      renderHeader();
      renderGrid();
    } catch (err) {
      toast(err.message, 'error');
    }
    // Nudge once per session when a daily reward is waiting.
    if (!dailyAutoShown) {
      dailyAutoShown = true;
      openDailyModal(false);
    }
  }

  init();
})();
