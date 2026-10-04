// ui-media.js — 影片與圖版的介面（兩版共用）。ui.html 本身只認得圖片，這支透過 window.FullyExt 的鉤子掛上：
//   網址卡的影片圖示與「多長／最高畫質」、影片的「要什麼」四選一、下載進度的階段、完成畫面的單位與畫質、
//   影片引擎自動更新（精靈一頁＋設定一列）、「Fully 能做什麼」、截圖用的影片狀態。
// 可以被疊上去的幾塊（站名、設定多幾列、精靈多一列、能做什麼的內容）透過 self() 讀最後那份 window.FullyExt。
(() => {
  const T = window.FullyTr, UI = window.FullyUI;
  if (!T || !UI) return;
  const tr = T.tr, esc = UI.esc, $ = UI.$, send = UI.send;
  const self = () => window.FullyExt || {};

  Object.assign(T.EN, {
    '正在轉成能播的格式': 'Converting to a playable format', '正在整理資料': 'Organizing the details', '正在截每個鏡頭': 'Saving a frame from each shot',
    '那一格畫面': 'the frame', '一張資料表': 'a spreadsheet', '個': '', '支': 'videos', '{n} 支': '{n} videos', '最高 {r}': 'up to {r}',
    '要這支影片的什麼？': 'What do you want from this video?', '影片': 'Video', '只要聲音': 'Audio only', '每個鏡頭截圖': 'A frame from each shot', '標題與留言': 'Titles & comments',
    '最高畫質，存好直接能播；有中英字幕會一起存。': 'Best quality, plays right away; Chinese/English subtitles are saved alongside.',
    '存成一首帶封面的音樂檔。': 'Saved as a music file with cover art.',
    '影片抓完，每換一個鏡頭截一張，<br>再拼成一張總覽圖。': 'Grabs the video, saves a frame at every cut,<br>then lays them out on one overview sheet.',
    '不抓影片：標題、觀看數、發布日、留言，<br>整理成一張表。': 'No video: titles, views, dates and comments,<br>organized into a spreadsheet.',
    '另外存 {t} 那一格畫面。': 'Also saves the frame at {t}.',
    '圖版': 'Board', '這不是公開的內容': "This isn't public",
    '自動跟上網站改版': 'Keep up with site changes', '每天在背景更新一次': 'Updates once a day in the background', '已關掉，一直用現在這版': 'Off — always using this version',
    '正在檢查更新…': 'Checking for updates…', '自動更新': 'Auto-update', '狀態': 'Status',
    '影片網站常改版，沒跟上就抓不到。Fully 每天在背景<br>更新一次影片引擎，只連 GitHub，不傳任何東西出去。': "Video sites change often; without updates, grabs break. Fully updates its<br>video engine once a day in the background — it only talks to GitHub and sends nothing out.",
    '只存你有權使用的內容': 'Only save what you have the right to use', 'Fully 只存公開看得到的內容': 'Fully only saves what’s publicly visible',
    'Fully 抓的是完整版，不是頁面上的縮圖。<br>網頁圖片原尺寸、整個圖版、影片最高畫質。<br>三步設定，一分鐘。': 'Fully saves the full version, not the thumbnail.<br>Web images at full size, whole boards, videos at best quality.<br>Three quick steps, one minute.',
    '<b>影片</b><br>上千個影片網站，公開看得到的都行。<br>抓最高畫質，存好直接能播。<br>也可以只要聲音、每個鏡頭截圖、標題與留言。': '<b>Video</b><br>Thousands of video sites — anything publicly visible.<br>Best quality, plays right away.<br>Or just the audio, a frame per shot, or titles & comments.',
    '<b>圖版</b><br>貼圖版的網址，整個圖版讀到底、一張不漏。<br>影片 pin 存影片本身，多頁的 pin 每一頁都存。': '<b>Boards</b><br>Paste a board link and Fully reads it to the very end.<br>Video pins are saved as videos; every page of a multi-page pin is saved.',
    '<b>順手</b><br>網址帶時間點（t=83）會另存那一格畫面。<br>一次貼很多行會排隊抓；失敗的可以一次重試。<br>追蹤一個網頁、圖版或影片清單，之後只抓新的。<br>右鍵選單「服務 → 用 Fully 抓」也可以。': '<b>Also</b><br>Links with a timestamp (t=83) also save that frame.<br>Paste many lines and they queue up; retry the failed ones at once.<br>Follow a page, board or playlist and Fully grabs only what’s new.<br>Right-click → Services → “Grab with Fully” works too.',
  });

  // ── 認得的影片站與圖版（跟引擎 video.py 的 HOSTS、pin_grab.py 的 claims 對齊；網址卡上只寫「影片」「圖版」）──
  const VIDEO_HOSTS = ['youtube.com', 'youtu.be', 'vimeo.com', 'bilibili.com', 'b23.tv', 'tiktok.com', 'douyin.com', 'instagram.com',
    'facebook.com', 'fb.watch', 'twitch.tv', 'dailymotion.com', 'youku.com', 'nicovideo.jp', 'rumble.com', 'streamable.com'];
  const hostOf = u => { try { return new URL(u).hostname.toLowerCase().replace(/^www\./, ''); } catch (e) { return ''; } };
  const isVideoHost = h => VIDEO_HOSTS.some(d => h === d || h.endsWith('.' + d));
  const isBoard = h => /(^|\.)pinterest\.[a-z.]+$/.test(h) || h === 'pin.it';
  const isVideoFile = u => { try { return /\.(mp4|mov|m4v|webm|mkv|m3u8)$/i.test(new URL(u).pathname); } catch (e) { return false; } };   // 直接指到影片檔（跟 video.py 的 is_video_file 對齊）

  const GET = { av: '最高畫質，存好直接能播；有中英字幕會一起存。', audio: '存成一首帶封面的音樂檔。',
                frames: '影片抓完，每換一個鏡頭截一張，<br>再拼成一張總覽圖。', data: '不抓影片：標題、觀看數、發布日、留言，<br>整理成一張表。' };
  const tParam = u => { const m = u.match(/[?&#](?:t|start)=(\d+h)?(\d+m)?(\d+)s?/); if (!m) return null;
    const t = (parseInt(m[1] || 0) * 3600) + (parseInt(m[2] || 0) * 60) + parseInt(m[3] || 0); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
  const urlNow = () => ($('url').value.split(/[\n\s,]+/).filter(u => /^https?:\/\//.test(u))[0] || '');
  const VID = '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9.5v5l4.5-2.5z"/></svg>';
  // 影片的「要什麼」：av＝影片本身（Swift 的預設）／audio／frames／data
  let pick = 'av';
  const setPick = m => { pick = m; paintGet(); };
  const dur = d => { const s = Math.round(d); return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };

  // 影片的「要什麼」四選一（放進 ui.html 的 #extAsk）
  function mountAsk() {
    $('extAsk').innerHTML = `<div class="t-title">${tr('要這支影片的什麼？')}</div>
      <div class="opts" style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:12px 8px">
        ${[['av', '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9.5v5l4.5-2.5z"/>', '影片'],
           ['audio', '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>', '只要聲音'],
           ['frames', '<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><rect x="13" y="13" width="8" height="7" rx="1.5"/>', '每個鏡頭截圖'],
           ['data', '<path d="M4 6h16M4 12h16M4 18h10"/>', '標題與留言']].map(([m, ic, t]) =>
          `<button class="opt${pick === m ? ' on' : ''}" data-mode="${m}" style="display:flex;align-items:center;gap:12px;font-size:13px;line-height:20px;color:var(--ink-mid);text-align:left"><span class="c" style="flex:0 0 32px;height:32px;border-radius:50%;box-shadow:var(--raise-sm);display:grid;place-items:center;transition:box-shadow .3s,transform .3s"><svg viewBox="0 0 24 24" style="width:16px;height:16px">${ic}</svg></span>${tr(t)}</button>`).join('')}
      </div>
      <div class="t-body" id="get" style="margin-top:16px"></div>`;
    $('extAsk').querySelectorAll('.opt').forEach(b => b.onclick = () => setPick(b.dataset.mode));
    paintGet();
  }
  function paintGet() {
    const m = pick, t = (m !== 'audio' && m !== 'data') ? tParam(urlNow()) : null;
    const g = $('get'); if (!g) return;
    g.innerHTML = tr(GET[m] || GET.av) + (t ? '<br>' + tr('另外存 {t} 那一格畫面。', { t }) : '');
    $('extAsk').querySelectorAll('.opt').forEach(b => { const on = b.dataset.mode === m; b.classList.toggle('on', on);
      b.style.color = on ? 'var(--ink)' : ''; b.style.fontWeight = on ? '600' : '';
      const c = b.querySelector('.c'); c.style.boxShadow = on ? 'var(--checked)' : 'var(--raise-sm)'; c.style.transform = on ? 'scale(1.1)' : ''; });
  }

  // 設定頁：影片引擎自動更新一列（放進 ui.html 的 #extSettings）；疊上去的那份可以在後面多幾列（settingsRows／bindSettings）
  let engine = {};
  const engineLine = () => { const st = engine.checking ? tr('正在檢查更新…') : `${engine.status || '—'}${engine.checkedAt ? '（' + engine.checkedAt + '）' : ''}`;
    return engine.auto !== false ? `${tr('每天在背景更新一次')}・${st}` : tr('已關掉，一直用現在這版'); };
  function renderSettings() {
    $('extSettings').innerHTML = `
      <button class="row" id="xAuto"><div class="l"><div class="t-body">${tr('自動跟上網站改版')}</div><div class="t-cap one" id="xEngineLine">${esc(engineLine())}</div></div><span class="sw${engine.auto !== false ? ' on' : ''}" id="xAutoSw"><i></i></span></button>`
      + (self().settingsRows?.() || '');
    $('xAuto').onclick = () => send('autoUpdate', { on: !$('xAutoSw').classList.contains('on') });
    self().bindSettings?.();
  }

  // 精靈：插一頁「自動跟上網站改版」；第一頁的介紹與三行換成連影片、圖版一起講的版本
  function mountWizard() {
    if (!document.querySelector('.wpage[data-p="engine"]')) {
      document.querySelector('.wpage[data-p="call"]').insertAdjacentHTML('beforebegin', `
      <div class="wpage" data-p="engine">
        <div class="t-display" id="xwT"></div>
        <div class="t-body" id="xwB"></div>
        <div class="wcard rows">
          <div class="r"><span class="t-cap" id="xwL1"></span><span class="t-body one" id="wyt">yt-dlp —</span></div>
          ${self().wizardRows?.() || ''}
          <div class="r"><span class="t-cap" id="xwL3"></span><span class="t-body one" id="wst">—</span></div>
        </div>
        <div class="wrow"><button class="sw on" id="wauto"><i></i></button><span class="t-body" id="xwAuto"></span><span style="flex:1"></span><button class="cap-key sm" id="wcheck"></button></div>
      </div>`);
      $('wauto').onclick = () => send('autoUpdate', { on: !$('wauto').classList.contains('on') });
      $('wcheck').onclick = () => send('checkUpdate');
    }
    $('xwT').textContent = tr('自動跟上網站改版');
    $('xwB').innerHTML = tr('影片網站常改版，沒跟上就抓不到。Fully 每天在背景<br>更新一次影片引擎，只連 GitHub，不傳任何東西出去。');
    $('xwL1').textContent = tr('影片'); $('xwL3').textContent = tr('狀態');
    $('xwAuto').textContent = tr('自動更新'); $('wcheck').textContent = tr('現在檢查');
    const terms = self().wizardTerms?.() || ['只存你有權使用的內容', 'Fully 只存公開看得到的內容', 'Fully 不上傳你的檔案'];
    const lis = $('termsList').querySelectorAll('li');
    terms.forEach((t, i) => { if (lis[i]) { lis[i].dataset.zh = t; lis[i].innerHTML = tr(t); } });
    const intro = document.querySelector('.wpage[data-p="welcome"] > .t-body');
    const it = self().wizardIntro?.() || 'Fully 抓的是完整版，不是頁面上的縮圖。<br>網頁圖片原尺寸、整個圖版、影片最高畫質。<br>三步設定，一分鐘。';
    if (intro) { intro.dataset.zh = it; intro.innerHTML = tr(it); }
    paintEngine();
  }
  function paintEngine() {
    if ($('wyt')) { $('wyt').textContent = `yt-dlp ${engine.ytdlp || '—'}${engine.source ? '・' + engine.source : ''}`;
      $('wst').textContent = engine.checking ? tr('正在檢查更新…') : `${engine.status || '—'}${engine.checkedAt ? '（' + engine.checkedAt + '）' : ''}`;
      $('wauto').classList.toggle('on', engine.auto !== false); }
    self().paintEngine?.(engine);
  }

  // 「Fully 能做什麼」
  function mountSites() {
    const blocks = self().siteBlocks?.() || ['貼上網址就好，Fully 會自己判斷。',
      '<b>影片</b><br>上千個影片網站，公開看得到的都行。<br>抓最高畫質，存好直接能播。<br>也可以只要聲音、每個鏡頭截圖、標題與留言。',
      '<b>圖版</b><br>貼圖版的網址，整個圖版讀到底、一張不漏。<br>影片 pin 存影片本身，多頁的 pin 每一頁都存。',
      '<b>任何網頁</b><br>掃出頁面上公開看得到的圖，<br>一張張換成原始尺寸，同時下載。',
      '<b>存下來之前</b><br>複製網址，右上角先跳一張預覽卡：<br>有幾張、能拿到多大、之前抓過沒。<br>只要其中幾張？按「挑幾張」。',
      '<b>存下來之後</b><br>告訴你拿到多大、是頁面上那張的幾倍。<br>單張圖直接在剪貼簿，⌘V 就貼。<br>一模一樣的圖不會存第二份。',
      '<b>順手</b><br>網址帶時間點（t=83）會另存那一格畫面。<br>一次貼很多行會排隊抓；失敗的可以一次重試。<br>追蹤一個網頁、圖版或影片清單，之後只抓新的。<br>右鍵選單「服務 → 用 Fully 抓」也可以。'];
    $('sitesBody').innerHTML = blocks.map(b => `<div class="t-body" data-i18n data-zh="${esc(b)}">${tr(b)}</div>`).join('');
  }

  window.FullyExt = {
    init() { mountWizard(); mountSites(); renderSettings(); },
    translate() { mountWizard(); mountSites(); renderSettings(); if ($('get')) mountAsk(); },
    classify(u) {
      const h = hostOf(u);
      if (isVideoHost(h) || isVideoFile(u)) return { label: tr('影片'), kind: 'video' };
      if (pick !== 'av') setPick('av');
      if (isBoard(h)) return { label: tr('圖版'), kind: 'image' };
      return null;
    },
    view(kind) { return kind === 'video' ? 'video' : null; },
    icon(kind) { return kind === 'video' ? VID : null; },
    histIcon(it) { return /影片|video/i.test(it.kind || '') || /audio|frames|data/.test(it.mode || '') ? VID : null; },
    startMode(kind) { return (kind === 'video' || kind === '*') ? pick : null; },
    askVisible(view) { if (view === 'video') { if (!$('get')) mountAsk(); else paintGet(); return true; } return false; },
    paint() {},
    // 預覽卡那行：影片＝長度＋最高畫質；清單＝幾支；不是公開的
    metaLine(p) {
      if (p.not_public) return tr('這不是公開的內容');
      if (!(p.list || p.duration || p.fps)) return null;
      const bits = [];
      if (p.list && p.count) bits.push(tr('{n} 支', { n: p.count }));
      else if (p.duration) bits.push(dur(p.duration));
      if (p.w && p.h) bits.push(tr('最高 {r}', { r: `${Math.min(p.w, p.h)}p${p.fps > 30 ? p.fps : ''}${p.hdr ? ' HDR' : ''}` }));
      return bits.join('・') || null;
    },
    onSource(ev) { if (ev.kind !== 'video') return false; UI.setText('0%'); UI.running(tr('下載中'), 0); return true; },
    stageText(st) { return /合併|轉檔|處理/.test(st) ? tr('正在轉成能播的格式') : /資料/.test(st) ? tr('正在整理資料') : /抽影格|接觸表/.test(st) ? tr('正在截每個鏡頭') : null; },
    unit(kind) { return kind === 'video' ? tr('個') : undefined; },
    doneExtras(ev) { return [ev.frame ? tr('那一格畫面') : '', ev.csv ? tr('一張資料表') : ''].filter(Boolean).join('、'); },
    proofX(ev) { return ev.res ? `${ev.res}${ev.fps > 30 ? ev.fps : ''}${ev.hdr ? ' HDR' : ''}` : ''; },
    noFollow(ev) { return /audio|data|frames/.test(ev.mode || ''); },
    wizardPages(base) { return ['welcome', 'dest', 'engine', 'call']; },
    onWizard(ev) { if (ev.auto !== undefined && $('wauto')) $('wauto').classList.toggle('on', !!ev.auto); },
    onEvent(ev) {
      if (ev.type === 'engine') {
        engine = ev;
        paintEngine();
        renderSettings();
        return true;
      }
      return false;
    },
    // 截圖用的影片網址：自己的網域、直接指到影片檔（官網截圖不露任何站名）
    demo(state) { if (state === 'video') { $('url').value = 'https://www.intention.ltd/made/fully.mp4'; $('url').dispatchEvent(new Event('input')); } },
    // 給疊上去的那份用：現在選的影片要法、重畫設定頁
    pickMode() { return pick; },
    refreshSettings() { renderSettings(); },
  };
})();
