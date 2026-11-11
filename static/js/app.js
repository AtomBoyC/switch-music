/* Switch Music 2.0 Frontend Controller */

const PLATFORM_LABELS = {
  ytm: 'YouTube Music',
  spotify: 'Spotify',
  netease: '网易云音乐',
  qqmusic: 'QQ音乐',
  kugou: '酷狗音乐',
  applemusic: 'Apple Music',
};

// Platforms whose public playlists can be read without logging in.
const LINK_READ_PLATFORMS = ['netease', 'qqmusic', 'kugou', 'applemusic'];
const ALL_PLATFORMS = ['ytm', 'spotify', 'netease', 'qqmusic', 'kugou', 'applemusic'];

const COOKIE_GUIDES = {
  ytm: {
    summary: '💡 15 秒获取 YouTube Music 连接信息（支持 cURL / 请求头 / Cookie）',
    html: `
      <ol>
        <li>浏览器打开并登录 <a href="https://music.youtube.com" target="_blank" style="color:#60a5fa;">music.youtube.com</a>，按 F12 打开开发者工具的 <strong>Network (网络)</strong> 面板。</li>
        <li>点击页面上的任意分类标签（如 <code>Relax</code>）或按 <code>Cmd+R</code> 刷新页面。</li>
        <li>右键任意一条发往 <code>music.youtube.com</code> 的请求（如 <code>browse?...</code>） → <strong>Copy → Copy as cURL</strong>，粘贴到下方保存即可！</li>
      </ol>
    `,
    btnClass: 'btn-ytm',
  },
  netease: {
    summary: '💡 15 秒获取网易云音乐登录态（用于读取私密歌单 / 我喜欢 & 创建写入歌单）',
    html: `
      <ol>
        <li>浏览器打开并登录 <a href="https://music.163.com" target="_blank" style="color:#f87171;">music.163.com</a>（若只从公开歌单往外导出，可免登录直接使用第 1 步「链接直读」）。</li>
        <li>打开开发者工具 <strong>Network (网络)</strong> 面板，刷新页面或点击「我的音乐」。</li>
        <li>找到任意一条 <code>music.163.com/weapi/...</code> 请求，<strong>右键 → Copy → Copy as cURL</strong>（或直接粘贴含 <code>MUSIC_U=...</code> 的 Cookie），粘贴到下方即可！</li>
      </ol>
    `,
    btnClass: 'btn-netease',
  },
  qqmusic: {
    summary: '💡 15 秒获取 QQ音乐登录态（用于读取私密歌单 / 我喜欢 & 创建写入歌单）',
    html: `
      <ol>
        <li>浏览器打开并登录 <a href="https://y.qq.com" target="_blank" style="color:#34d399;">y.qq.com</a>（若只从公开歌单往外导出，可免登录直接使用第 1 步「链接直读」）。</li>
        <li>打开开发者工具 <strong>Network (网络)</strong> 面板，点击顶部「我的音乐」或刷新页面。</li>
        <li>找到任意一条 <code>u.y.qq.com</code> 或 <code>u6.y.qq.com</code> 请求，<strong>右键 → Copy → Copy as cURL</strong>（需包含 <code>uin/wxuin</code> 与 <code>qm_keyst/qqmusic_key</code>），粘贴到下方保存！</li>
      </ol>
    `,
    btnClass: 'btn-qqmusic',
  },
  kugou: {
    summary: '💡 备选方式：手动粘贴酷狗 token（推荐优先使用上方扫码登录）',
    html: `
      <ol>
        <li>推荐直接使用上方 <strong>「酷狗 App 扫码登录」</strong>，无需任何手动操作。</li>
        <li>如已通过其他工具（如 KuGouMusicApi）取得客户端登录态，可粘贴 <code>{"token": "...", "userid": 123}</code> JSON 或 <code>token=...; userid=...</code> 到下方。</li>
        <li>注意：网页版 <code>kugou.com</code> 的 Cookie 一般不能用于客户端歌单接口，验证失败时请改用扫码登录。</li>
      </ol>
    `,
    btnClass: 'btn-kugou',
  },
  applemusic: {
    summary: '💡 30 秒获取 Apple Music 登录态（用于读取资料库歌单 & 创建写入歌单，无需开发者账号）',
    html: `
      <ol>
        <li>用 Chrome / Safari 打开并登录 <a href="https://music.apple.com" target="_blank" style="color:#fb7185;">music.apple.com</a>（需有效的 Apple Music 订阅）。只从公开歌单往外导出时，可免登录直接使用第 1 步「链接直读」。</li>
        <li>按 F12 打开开发者工具 <strong>Network (网络)</strong> 面板，在左侧点击「资料库 → 歌单」或刷新页面。</li>
        <li>筛选 <code>amp-api</code>，右键任意一条发往 <code>amp-api.music.apple.com</code> 的请求 → <strong>Copy → Copy as cURL</strong>（需包含 <code>media-user-token</code> 请求头），粘贴到下方保存！</li>
        <li>说明：该方式使用网页版播放器的非官方接口；Apple 官方接口不支持从歌单中删除单曲，因此 Apple Music 歌单去重仅支持扫描。</li>
      </ol>
    `,
    btnClass: 'btn-applemusic',
  },
};

// State
let platformStatuses = {};
let activeAuthDrawer = null;

let loadedTracks = [];
let loadedSourcePlatform = 'csv';
let scannedSourceGroups = [];
let editingTrackIndex = null;

let selectedTargetPlatform = 'ytm';
let currentJobId = null;
let currentJobData = null;
let pollTimer = null;
let resultFilter = 'all';

// In preview mode: track_index -> { skip: bool, candidate: obj | null }
let previewOverrides = {};

// Manual search modal state
let manualModalTrackIdx = null;
let manualModalCandidates = [];

// Deduplicator state
let scannedDupGroups = [];
let scannedDupTotal = 0;
let scannedDupPlaylistId = '';
let scannedDupPlatform = 'ytm';

window.addEventListener('DOMContentLoaded', async () => {
  setupDragAndDrop();
  await refreshAllPlatformsStatus(false);

  const params = new URLSearchParams(window.location.search);
  if (params.get('spotify_connected') === '1') {
    window.history.replaceState({}, '', '/');
    switchSourceTab('account');
    document.getElementById('srcAccountPlatformSelect').value = 'spotify';
    loadSourceAccountPlaylists(false);
  }
});

// ---------------------------------------------------------------------------
// UI Utilities
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatMs(ms) {
  if (!ms || ms <= 0) return '';
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function showAlert(elId, type, text) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `alert alert-${type} show`;
  el.textContent = text;
}

function hideAlert(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = 'alert';
}

function switchMainView(viewName) {
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === viewName);
  });
  ['migrate', 'dedupe', 'export', 'sync'].forEach(v => {
    const el = document.getElementById(`view_${v}`);
    if (el) el.style.display = v === viewName ? 'block' : 'none';
  });

  if (viewName === 'dedupe') {
    loadDedupePlaylists(false);
  } else if (viewName === 'export') {
    loadExportPlaylists(false);
  } else if (viewName === 'sync') {
    loadSyncSourcePlaylists();
    loadSyncTargetPlaylists();
    loadSyncTasks();
    loadHistoryList();
  }
}

// ---------------------------------------------------------------------------
// 1. Multi-Platform Connection Hub & Auth Drawer
// ---------------------------------------------------------------------------

async function refreshAllPlatformsStatus(showFeedback = false) {
  try {
    const res = await fetch('/api/platforms/status');
    const data = await res.json();
    platformStatuses = data.platforms || {};

    ALL_PLATFORMS.forEach(pid => {
      const st = platformStatuses[pid] || {};
      const card = document.getElementById(`platCard_${pid}`);
      const sub = document.getElementById(`platSub_${pid}`);
      if (!card || !sub) return;
      if (st.connected) {
        card.classList.add('connected');
        sub.textContent = st.user_name ? `已连接: ${st.user_name}` : '已连接 (点击管理)';
      } else {
        card.classList.remove('connected');
        sub.textContent = LINK_READ_PLATFORMS.includes(pid)
          ? '未登录 · 支持链接直读'
          : '未连接 · 点击配置';
      }
    });

    if (platformStatuses.spotify && platformStatuses.spotify.client_id) {
      document.getElementById('spClientId').value = platformStatuses.spotify.client_id;
    }
    if (activeAuthDrawer) {
      updateDrawerButtons(activeAuthDrawer);
    }
    if (showFeedback) {
      showAlert('sourceAlert', 'info', '✅ 已刷新所有音乐平台的连接状态');
    }
  } catch (err) {
    console.error(err);
  }
}

function toggleAuthDrawer(plat) {
  if (activeAuthDrawer === plat) {
    closeAuthDrawer();
    return;
  }
  activeAuthDrawer = plat;
  document.querySelectorAll('.plat-card').forEach(c => c.classList.remove('active-drawer'));
  const card = document.getElementById(`platCard_${plat}`);
  if (card) card.classList.add('active-drawer');

  const drawer = document.getElementById('authDrawerCard');
  drawer.style.display = 'block';
  document.getElementById('authDrawerTitle').textContent = `连接管理 · ${PLATFORM_LABELS[plat]}`;
  document.getElementById('cookieAuthMsg').textContent = '';

  if (plat === 'spotify') {
    document.getElementById('cookieAuthForm').style.display = 'none';
    document.getElementById('spotifyAuthForm').style.display = 'block';
    const st = platformStatuses.spotify || {};
    const hint = document.getElementById('spScopeHint');
    if (st.connected && !st.has_write_scope) {
      hint.style.color = 'var(--warning)';
      hint.textContent = '⚠️ 当前旧缓存仅含只读权限，若要向 Spotify 写入歌单请重新点击授权登录';
    } else if (st.connected) {
      hint.style.color = 'var(--success)';
      hint.textContent = `✅ 当前已授权双向读写 (${st.user_name})`;
    } else {
      hint.textContent = '';
    }
  } else {
    document.getElementById('spotifyAuthForm').style.display = 'none';
    document.getElementById('cookieAuthForm').style.display = 'block';
    document.getElementById('kugouQrBox').style.display = plat === 'kugou' ? 'flex' : 'none';
    const g = COOKIE_GUIDES[plat];
    document.getElementById('cookieGuideSummary').textContent = g.summary;
    document.getElementById('cookieGuideBody').innerHTML = g.html;
    // Kugou: the QR login is primary, so keep the manual-token guide collapsed.
    document.getElementById('cookieGuideSummary').parentElement.open = plat !== 'kugou';
    const btn = document.getElementById('saveCookieAuthBtn');
    btn.className = `btn ${g.btnClass}`;
    btn.textContent = `验证并保存 ${PLATFORM_LABELS[plat]} 连接`;
  }
  if (plat !== 'kugou') stopKugouQrPolling();
  updateDrawerButtons(plat);
}

// ---------------------------------------------------------------------------
// Kugou QR-code login
// ---------------------------------------------------------------------------

let kugouQrTimer = null;

function stopKugouQrPolling() {
  if (kugouQrTimer) {
    clearInterval(kugouQrTimer);
    kugouQrTimer = null;
  }
}

async function startKugouQrLogin() {
  stopKugouQrPolling();
  const btn = document.getElementById('kugouQrBtn');
  const msg = document.getElementById('kugouQrMsg');
  const img = document.getElementById('kugouQrImg');
  btn.disabled = true;
  msg.style.color = 'var(--text-muted)';
  msg.textContent = '⏳ 正在生成二维码...';
  try {
    const res = await fetch('/api/platforms/kugou/qrcode', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '生成二维码失败');
    if (!String(data.qrcode_img || '').startsWith('data:image/')) throw new Error('二维码图片数据无效');
    img.src = data.qrcode_img;
    img.style.display = 'block';
    msg.textContent = '📱 请使用酷狗音乐 App 扫码';
    btn.textContent = '刷新二维码';
    const key = data.key;
    kugouQrTimer = setInterval(() => pollKugouQr(key), 2000);
  } catch (err) {
    msg.style.color = 'var(--danger)';
    msg.textContent = `❌ ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function pollKugouQr(key) {
  const msg = document.getElementById('kugouQrMsg');
  try {
    const res = await fetch(`/api/platforms/kugou/qrcode/${encodeURIComponent(key)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '检查扫码状态失败');
    if (data.status === 4 && data.connected) {
      stopKugouQrPolling();
      document.getElementById('kugouQrImg').style.display = 'none';
      msg.style.color = 'var(--success)';
      msg.textContent = `✅ ${data.message}`;
      await refreshAllPlatformsStatus(false);
      if (selectedTargetPlatform === 'kugou') loadTargetPlaylists(false);
    } else if (data.status === 0) {
      stopKugouQrPolling();
      msg.style.color = 'var(--warning)';
      msg.textContent = '⌛ 二维码已过期，请点击「刷新二维码」';
    } else {
      msg.style.color = 'var(--text-muted)';
      msg.textContent = data.status === 2 ? '📲 已扫码，请在手机上确认登录' : '📱 请使用酷狗音乐 App 扫码';
    }
  } catch (err) {
    stopKugouQrPolling();
    msg.style.color = 'var(--danger)';
    msg.textContent = `❌ ${err.message}`;
  }
}

function updateDrawerButtons(plat) {
  const st = platformStatuses[plat] || {};
  const discBtn = document.getElementById('disconnectPlatBtn');
  discBtn.style.display = st.connected ? 'inline-flex' : 'none';
}

function closeAuthDrawer() {
  stopKugouQrPolling();
  activeAuthDrawer = null;
  document.querySelectorAll('.plat-card').forEach(c => c.classList.remove('active-drawer'));
  document.getElementById('authDrawerCard').style.display = 'none';
}

async function submitCookieAuth() {
  if (!activeAuthDrawer) return;
  const raw = document.getElementById('cookieRawInput').value.trim();
  const msg = document.getElementById('cookieAuthMsg');
  const btn = document.getElementById('saveCookieAuthBtn');
  if (!raw) {
    msg.style.color = 'var(--danger)';
    msg.textContent = '请先粘贴 Copy as cURL、请求头或 Cookie 内容';
    return;
  }
  btn.disabled = true;
  msg.style.color = 'var(--text-muted)';
  msg.textContent = '⏳ 正在验证凭据并连接平台...';
  try {
    const res = await fetch(`/api/platforms/${activeAuthDrawer}/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ headers_raw: raw }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '验证失败');
    msg.style.color = 'var(--success)';
    msg.textContent = `✅ ${data.message}`;
    document.getElementById('cookieRawInput').value = '';
    await refreshAllPlatformsStatus(false);
    if (selectedTargetPlatform === activeAuthDrawer) {
      loadTargetPlaylists(false);
    }
  } catch (err) {
    msg.style.color = 'var(--danger)';
    msg.textContent = `❌ ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function disconnectCurrentPlatform() {
  if (!activeAuthDrawer) return;
  try {
    const res = await fetch(`/api/platforms/${activeAuthDrawer}/disconnect`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '断开失败');
    await refreshAllPlatformsStatus(false);
    closeAuthDrawer();
  } catch (err) {
    alert(err.message);
  }
}

async function saveSpotifyConfigAndLogin() {
  const cid = document.getElementById('spClientId').value.trim();
  const sec = document.getElementById('spClientSecret').value.trim();
  if (!cid || !sec) {
    alert('请完整填写 Spotify Client ID 和 Client Secret');
    return;
  }
  try {
    const res = await fetch('/api/spotify/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: cid, client_secret: sec }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '保存失败');
    if (data.auth_url) {
      window.location.href = data.auth_url;
    }
  } catch (err) {
    alert('❌ ' + err.message);
  }
}

async function clearMatchCache() {
  try {
    const res = await fetch('/api/cache/matches', { method: 'DELETE' });
    const data = await res.json();
    showAlert('sourceAlert', 'info', `⚡ 已清理本地匹配缓存（共移除 ${data.cleared_count || 0} 条记录）`);
  } catch (err) {
    console.error(err);
  }
}

// ---------------------------------------------------------------------------
// 2. Source Playlist Loading (URL / Account / CSV / Plain Text)
// ---------------------------------------------------------------------------

function switchSourceTab(tab) {
  ['url', 'account', 'csv', 'text'].forEach(t => {
    document.getElementById(`srcTab_${t}`).classList.toggle('active', t === tab);
    document.getElementById(`sourcePane_${t}`).style.display = t === tab ? 'block' : 'none';
  });
  if (tab === 'account') {
    loadSourceAccountPlaylists(false);
  }
}

async function importFromUrl() {
  const plat = document.getElementById('urlPlatformSelect').value;
  const urlVal = document.getElementById('playlistUrlInput').value.trim();
  if (!urlVal) {
    showAlert('sourceAlert', 'error', '请先粘贴网易云音乐、QQ音乐、酷狗音乐、Apple Music 或 YouTube Music 的歌单链接 / ID！');
    return;
  }
  const btn = document.getElementById('importUrlBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 解析中...';
  showAlert('sourceAlert', 'info', '正在解析链接并批量拉取歌单曲目，请稍候...');
  try {
    const res = await fetch('/api/import/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform: plat, url_or_id: urlVal }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '解析歌单链接失败');
    applyIncomingTracks(data.tracks, data.playlist_name, data.platform || plat);
    showAlert(
      'sourceAlert',
      'success',
      `✅ 成功从 ${PLATFORM_LABELS[data.platform] || '歌单链接'} 读取「${data.playlist_name}」，共 ${data.count} 首歌曲！`
    );
  } catch (err) {
    showAlert('sourceAlert', 'error', '❌ ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '📥 解析歌单';
  }
}

async function loadSourceAccountPlaylists(showErr = false) {
  const plat = document.getElementById('srcAccountPlatformSelect').value;
  const sel = document.getElementById('srcAccountPlaylistSelect');
  sel.innerHTML = '<option value="">正在读取歌单列表...</option>';
  try {
    const res = await fetch(`/api/platforms/${plat}/playlists?include_liked=true`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '拉取失败');
    const list = data.playlists || [];
    sel.innerHTML = '';
    if (!list.length) {
      sel.innerHTML = '<option value="">-- 该账号下暂无歌单 --</option>';
      return;
    }
    list.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id || p.playlistId;
      const cnt = p.count !== undefined && p.count !== '' ? ` (${p.count} 首)` : '';
      opt.textContent = `${p.name || p.title}${cnt}`;
      sel.appendChild(opt);
    });
  } catch (err) {
    sel.innerHTML = `<option value="">-- 请先点击顶部「${PLATFORM_LABELS[plat]}」卡片完成连接 --</option>`;
    if (showErr) showAlert('sourceAlert', 'error', '❌ ' + err.message);
  }
}

async function fetchSelectedAccountPlaylist() {
  const plat = document.getElementById('srcAccountPlatformSelect').value;
  const pid = document.getElementById('srcAccountPlaylistSelect').value;
  if (!pid) {
    showAlert('sourceAlert', 'error', '请先选择一个要读取的歌单（若未登录请先点击顶部对应平台连接）');
    return;
  }
  const btn = document.getElementById('fetchAccountTracksBtn');
  btn.disabled = true;
  showAlert('sourceAlert', 'info', `⏳ 正在从 ${PLATFORM_LABELS[plat]} 读取全量歌单曲目...`);
  try {
    const res = await fetch(`/api/platforms/${plat}/playlist/${encodeURIComponent(pid)}/tracks`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '读取歌单失败');
    applyIncomingTracks(data.tracks, data.playlist_name, plat);
    showAlert('sourceAlert', 'success', `✅ 成功读取「${data.playlist_name}」，共 ${data.count} 首歌曲！`);
  } catch (err) {
    showAlert('sourceAlert', 'error', '❌ ' + err.message);
  } finally {
    btn.disabled = false;
  }
}

function setupDragAndDrop() {
  const dz = document.getElementById('csvDropzone');
  if (!dz) return;
  dz.addEventListener('dragover', e => {
    e.preventDefault();
    dz.classList.add('dragover');
  });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', e => {
    e.preventDefault();
    dz.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleCsvFiles(e.dataTransfer.files);
    }
  });
}

async function handleCsvFiles(fileList) {
  if (!fileList || fileList.length === 0) return;
  hideAlert('sourceAlert');
  const formData = new FormData();
  for (const f of fileList) {
    formData.append('files', f);
  }
  try {
    const res = await fetch('/api/import/csv', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '文件解析失败');
    applyIncomingTracks(data.tracks, data.playlist_name, 'csv');
    showAlert('sourceAlert', 'success', `✅ 成功从文件解析出 ${data.count} 首歌曲！`);
  } catch (err) {
    showAlert('sourceAlert', 'error', '❌ ' + err.message);
  } finally {
    document.getElementById('csvFileInput').value = '';
  }
}

async function importFromPlainText() {
  const text = document.getElementById('plainTextTracksInput').value.trim();
  const name = document.getElementById('plainTextNameInput').value.trim() || '文本导入歌单';
  if (!text) {
    showAlert('sourceAlert', 'error', '请先粘贴歌曲列表文本（如：晴天 - 周杰伦）');
    return;
  }
  try {
    const res = await fetch('/api/import/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, playlist_name: name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '解析失败');
    applyIncomingTracks(data.tracks, data.playlist_name, 'text');
    showAlert('sourceAlert', 'success', `✅ 成功从文本解析出 ${data.count} 首歌曲！`);
  } catch (err) {
    showAlert('sourceAlert', 'error', '❌ ' + err.message);
  }
}

function applyIncomingTracks(newTracks, suggestedName, sourcePlat) {
  const appendMode = document.getElementById('appendTracksModeCheckbox').checked;
  if (appendMode && loadedTracks.length > 0) {
    loadedTracks = loadedTracks.concat(newTracks || []);
    loadedSourcePlatform = 'mixed';
  } else {
    loadedTracks = newTracks || [];
    loadedSourcePlatform = sourcePlat || 'csv';
    if (suggestedName) {
      document.getElementById('playlistTitleInput').value = suggestedName;
    }
  }
  previewOverrides = {};
  document.getElementById('commitPreviewBtn').style.display = 'none';
  updateLoadedTracksUI();
}

function updateLoadedTracksUI() {
  document.getElementById('loadedCounter').textContent =
    loadedTracks.length > 0 ? `已就绪 ${loadedTracks.length} 首歌曲` : '尚未加载曲目';
  document.getElementById('previewCount').textContent = loadedTracks.length;
  document.getElementById('trackPreviewSection').style.display = loadedTracks.length > 0 ? 'block' : 'none';
  renderLoadedTracksTable();
}

function renderLoadedTracksTable() {
  const tbody = document.getElementById('trackPreviewTbody');
  const q = (document.getElementById('sourceFilterInput').value || '').trim().toLowerCase();
  tbody.innerHTML = '';

  const filtered = [];
  loadedTracks.forEach((t, idx) => {
    if (!q || (t.title || '').toLowerCase().includes(q) || (t.artist || '').toLowerCase().includes(q)) {
      filtered.push({ t, idx });
    }
  });

  filtered.slice(0, 400).forEach(({ t, idx }) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="color: var(--text-muted);">${idx + 1}</td>
      <td style="font-weight: 600;">${escapeHtml(t.title)}</td>
      <td>${escapeHtml(t.artist)}</td>
      <td style="color: var(--text-muted);">${escapeHtml(t.album || '')}</td>
      <td style="color: var(--text-muted); font-variant-numeric: tabular-nums;">${formatMs(t.duration_ms)}</td>
      <td>
        <div style="display: flex; gap: 4px;">
          <button class="btn-mini" title="编辑歌名/歌手" onclick="openEditTrackModal(${idx})">✏️</button>
          <button class="btn-mini" title="从列表移除" onclick="deleteLoadedTrack(${idx})">✕</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });

  if (filtered.length > 400) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="6" style="text-align:center; color: var(--text-muted);">... 仅展示前 400 首预览，其余 ${filtered.length - 400} 首将在迁移时完整处理 ...</td>`;
    tbody.appendChild(tr);
  }
}

function openEditTrackModal(idx) {
  const t = loadedTracks[idx];
  if (!t) return;
  editingTrackIndex = idx;
  document.getElementById('editTrackTitle').value = t.title || '';
  document.getElementById('editTrackArtist').value = t.artist || '';
  document.getElementById('editTrackAlbum').value = t.album || '';
  document.getElementById('editTrackModal').classList.add('open');
}

function closeEditTrackModal() {
  editingTrackIndex = null;
  document.getElementById('editTrackModal').classList.remove('open');
}

function saveEditedTrack() {
  if (editingTrackIndex === null || !loadedTracks[editingTrackIndex]) return;
  const title = document.getElementById('editTrackTitle').value.trim();
  if (!title) {
    alert('歌曲标题不能为空');
    return;
  }
  loadedTracks[editingTrackIndex].title = title;
  loadedTracks[editingTrackIndex].artist = document.getElementById('editTrackArtist').value.trim();
  loadedTracks[editingTrackIndex].album = document.getElementById('editTrackAlbum').value.trim();
  closeEditTrackModal();
  renderLoadedTracksTable();
}

function deleteLoadedTrack(idx) {
  loadedTracks.splice(idx, 1);
  updateLoadedTracksUI();
}

function clearLoadedTracks() {
  loadedTracks = [];
  previewOverrides = {};
  document.getElementById('sourceDedupeBox').style.display = 'none';
  document.getElementById('commitPreviewBtn').style.display = 'none';
  hideAlert('sourceAlert');
  updateLoadedTracksUI();
}

async function exportCurrentLoadedCsv() {
  if (!loadedTracks.length) return;
  const name = document.getElementById('playlistTitleInput').value.trim() || 'Switch_Music_Tracks';
  await triggerCsvDownload(name, loadedTracks);
}

// --- Source List Deduplication ---

async function scanLoadedTracksDuplicates() {
  if (!loadedTracks.length) return;
  try {
    const res = await fetch('/api/tracks/deduplicate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'standard', tracks: loadedTracks }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '检测重复失败');
    const groups = data.groups || [];
    if (!groups.length) {
      document.getElementById('sourceDedupeBox').style.display = 'none';
      showAlert('sourceAlert', 'info', '🎉 当前待迁移列表中没有发现任何重复曲目！');
    } else {
      scannedSourceGroups = groups.map(g => ({
        ...g,
        items: g.items.map(it => ({ ...it, selectedRemove: !!it.default_remove })),
      }));
      document.getElementById('srcDupGroupCount').textContent = scannedSourceGroups.length;
      document.getElementById('sourceDedupeBox').style.display = 'block';
      renderSourceDuplicateGroups();
      hideAlert('sourceAlert');
    }
  } catch (err) {
    showAlert('sourceAlert', 'error', '❌ ' + err.message);
  }
}

function renderSourceDuplicateGroups() {
  const container = document.getElementById('sourceDupGroupsContainer');
  container.innerHTML = '';
  let totalSelected = 0;

  scannedSourceGroups.forEach((g, gIdx) => {
    const allChecked = g.items.every(it => it.selectedRemove);
    const div = document.createElement('div');
    div.className = 'dup-group';

    let rowsHtml = '';
    g.items.forEach((it, iIdx) => {
      if (it.selectedRemove) totalSelected++;
      const dur = formatMs(it.duration_ms);
      rowsHtml += `
        <div class="dup-row ${it.selectedRemove ? 'marked-remove' : 'marked-keep'}">
          <input type="checkbox" ${it.selectedRemove ? 'checked' : ''}
            onchange="toggleSrcItemRemove(${gIdx}, ${iIdx}, this.checked)"
            style="width: 16px; height: 16px; accent-color: var(--danger); cursor: pointer;" />
          <span class="pill ${it.selectedRemove ? 'pill-fail' : 'pill-ok'}" style="min-width: 58px; justify-content: center;">
            ${it.selectedRemove ? '🗑️ 移除' : '✅ 保留'}
          </span>
          <span style="color: var(--text-muted); font-weight: 600; min-width: 40px;">#${it.position}</span>
          <div style="flex: 1; min-width: 0;">
            <div style="font-weight: 600;">${escapeHtml(it.title)}</div>
            <div style="font-size: 12px; color: var(--text-muted);">
              ${escapeHtml(it.artist)}${it.album ? ' · ' + escapeHtml(it.album) : ''}${dur ? ' · ' + dur : ''}
            </div>
          </div>
          ${it.selectedRemove
            ? `<button class="btn-mini" onclick="keepOnlyThisInSourceGroup(${gIdx}, ${iIdx})">🔄 改为只留这首</button>`
            : `<span style="font-size: 11.5px; color: var(--text-muted);">当前保留</span>`
          }
        </div>
      `;
    });

    div.innerHTML = `
      <div class="dup-group-header">
        <span>第 ${gIdx + 1} 组重复（共 ${g.items.length} 首） · ${escapeHtml(g.reason)}</span>
        ${allChecked ? '<span style="color: var(--warning);">⚠️ 该组全部被勾选，将整组移除</span>' : ''}
      </div>
      ${rowsHtml}
    `;
    container.appendChild(div);
  });

  document.getElementById('selectedSrcDupCount').textContent = totalSelected;
  document.getElementById('confirmSrcRemoveBtn').disabled = totalSelected === 0;
}

function toggleSrcItemRemove(gIdx, iIdx, checked) {
  scannedSourceGroups[gIdx].items[iIdx].selectedRemove = checked;
  renderSourceDuplicateGroups();
}

function keepOnlyThisInSourceGroup(gIdx, keepIdx) {
  scannedSourceGroups[gIdx].items.forEach((it, idx) => {
    it.selectedRemove = idx !== keepIdx;
  });
  renderSourceDuplicateGroups();
}

function applySourceGroupPreset(preset) {
  scannedSourceGroups.forEach(g => {
    const last = g.items.length - 1;
    g.items.forEach((it, idx) => {
      if (preset === 'keep_first') it.selectedRemove = idx !== 0;
      else if (preset === 'keep_last') it.selectedRemove = idx !== last;
    });
  });
  renderSourceDuplicateGroups();
}

function confirmRemoveSourceDuplicates() {
  const toRemove = new Set();
  scannedSourceGroups.forEach(g => {
    g.items.forEach(it => {
      if (it.selectedRemove) toRemove.add(it.track_index);
    });
  });
  if (!toRemove.size) return;
  loadedTracks = loadedTracks.filter((_, idx) => !toRemove.has(idx));
  document.getElementById('sourceDedupeBox').style.display = 'none';
  updateLoadedTracksUI();
  showAlert('sourceAlert', 'success', `🧹 已移除 ${toRemove.size} 首重复歌曲，当前保留 ${loadedTracks.length} 首！`);
}

// ---------------------------------------------------------------------------
// 3. Target Platform Selection, Preview Match & Migration Execution
// ---------------------------------------------------------------------------

function selectTargetPlatform(plat) {
  selectedTargetPlatform = plat;
  document.querySelectorAll('.target-plat-option').forEach(el => {
    el.classList.toggle('selected', el.dataset.plat === plat);
  });
  const btn = document.getElementById('startMigrateBtn');
  btn.className = `btn btn-${plat}`;
  btn.textContent = `🚀 直接一键匹配并导入到 ${PLATFORM_LABELS[plat]}`;
  document.getElementById('commitPreviewBtn').style.display = 'none';

  if (document.getElementById('targetModeSelect').value === 'existing_playlist') {
    loadTargetPlaylists(false);
  }
}

function onTargetModeChange() {
  const mode = document.getElementById('targetModeSelect').value;
  document.getElementById('newPlaylistMetaRow').style.display = mode === 'new_playlist' ? 'grid' : 'none';
  document.getElementById('newPlaylistPrivacyCol').style.display = mode === 'new_playlist' ? 'block' : 'none';
  document.getElementById('existingPlaylistRow').style.display = mode === 'existing_playlist' ? 'block' : 'none';
  if (mode === 'existing_playlist') {
    loadTargetPlaylists(false);
  }
}

async function loadTargetPlaylists(showErr = false) {
  const sel = document.getElementById('existingTargetPlaylistSelect');
  sel.innerHTML = '<option value="">加载中...</option>';
  try {
    const res = await fetch(`/api/platforms/${selectedTargetPlatform}/playlists?include_liked=false`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '加载歌单失败');
    const list = (data.playlists || []).filter(p => p.editable !== false);
    sel.innerHTML = '';
    if (!list.length) {
      sel.innerHTML = '<option value="">-- 暂无可编辑歌单 --</option>';
      return;
    }
    list.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id || p.playlistId;
      opt.textContent = `${p.name || p.title} (${p.count ?? 0} 首)`;
      sel.appendChild(opt);
    });
  } catch (err) {
    sel.innerHTML = `<option value="">-- 请先在顶部连接 ${PLATFORM_LABELS[selectedTargetPlatform]} --</option>`;
    if (showErr) showAlert('migrateErrorAlert', 'error', '❌ ' + err.message);
  }
}

async function startPreviewMatch() {
  hideAlert('migrateErrorAlert');
  if (!loadedTracks.length) {
    showAlert('migrateErrorAlert', 'error', '请先在第 1 步加载源歌单曲目！');
    return;
  }

  previewOverrides = {};
  const payload = {
    target_platform: selectedTargetPlatform,
    concurrency: parseInt(document.getElementById('concurrencySelect').value, 10) || 4,
    use_cache: document.getElementById('useCacheCheckbox').checked,
    min_score: parseInt(document.getElementById('minScoreSelect').value, 10) || 38,
    tracks: loadedTracks,
  };

  setJobButtonsRunning(true);
  try {
    const res = await fetch('/api/migrate/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '启动预匹配失败');
    currentJobId = data.job_id;
    document.getElementById('migrationProgressBox').style.display = 'block';
    pollJobStatus();
  } catch (err) {
    showAlert('migrateErrorAlert', 'error', '❌ ' + err.message);
    setJobButtonsRunning(false);
  }
}

async function startDirectMigration(prematchedPayload = null) {
  hideAlert('migrateErrorAlert');
  if (!loadedTracks.length) {
    showAlert('migrateErrorAlert', 'error', '请先在第 1 步加载源歌单曲目！');
    return;
  }

  const targetMode = document.getElementById('targetModeSelect').value;
  const payload = {
    source_platform: loadedSourcePlatform,
    target_platform: selectedTargetPlatform,
    target_mode: targetMode,
    playlist_title: document.getElementById('playlistTitleInput').value.trim() || 'Switch Music Playlist',
    playlist_description: document.getElementById('playlistDescInput').value.trim(),
    privacy_status: document.getElementById('privacySelect').value,
    existing_playlist_id: document.getElementById('existingTargetPlaylistSelect').value || null,
    skip_duplicates: document.getElementById('skipDuplicatesCheckbox').checked,
    concurrency: parseInt(document.getElementById('concurrencySelect').value, 10) || 4,
    use_cache: document.getElementById('useCacheCheckbox').checked,
    min_score: parseInt(document.getElementById('minScoreSelect').value, 10) || 38,
    tracks: loadedTracks,
    prematched: prematchedPayload,
  };

  setJobButtonsRunning(true);
  try {
    const res = await fetch('/api/migrate/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '启动迁移任务失败');
    currentJobId = data.job_id;
    document.getElementById('migrationProgressBox').style.display = 'block';
    pollJobStatus();
  } catch (err) {
    showAlert('migrateErrorAlert', 'error', '❌ ' + err.message);
    setJobButtonsRunning(false);
  }
}

async function commitPreviewedMigration() {
  if (!currentJobData || currentJobData.job_type !== 'preview') return;
  const prematched = {};
  (currentJobData.results || []).forEach(r => {
    const idx = r.track_index !== undefined ? r.track_index : r.index - 1;
    const ov = previewOverrides[idx];
    if (ov && ov.skip) {
      prematched[String(idx)] = { skip: true };
    } else if (ov && ov.candidate) {
      prematched[String(idx)] = { candidate: ov.candidate };
    } else if (r.status === 'matched' && r.candidate) {
      prematched[String(idx)] = { candidate: r.candidate };
    } else {
      prematched[String(idx)] = { skip: true };
    }
  });
  await startDirectMigration(prematched);
}

function setJobButtonsRunning(running) {
  document.getElementById('previewMatchBtn').disabled = running;
  document.getElementById('startMigrateBtn').disabled = running;
  document.getElementById('cancelMigrateBtn').style.display = running ? 'inline-flex' : 'none';
  if (running) {
    document.getElementById('jobDoneActions').style.display = 'none';
    document.getElementById('commitPreviewBtn').style.display = 'none';
  }
}

async function pollJobStatus() {
  if (!currentJobId) return;
  if (pollTimer) clearTimeout(pollTimer);
  try {
    const res = await fetch(`/api/migrate/status/${currentJobId}`);
    const job = await res.json();
    if (!res.ok) throw new Error(job.detail || '读取进度失败');

    currentJobData = job;
    renderJobProgress(job);

    if (job.status === 'running') {
      pollTimer = setTimeout(pollJobStatus, 700);
    } else {
      setJobButtonsRunning(false);
      if (job.job_type === 'preview' && job.status === 'completed') {
        document.getElementById('commitPreviewBtn').style.display = 'inline-flex';
        updateCommitPreviewButtonCount();
      }
    }
  } catch (err) {
    console.error(err);
    setJobButtonsRunning(false);
  }
}

function updateCommitPreviewButtonCount() {
  if (!currentJobData || currentJobData.job_type !== 'preview') return;
  let count = 0;
  (currentJobData.results || []).forEach(r => {
    const idx = r.track_index !== undefined ? r.track_index : r.index - 1;
    const ov = previewOverrides[idx];
    if (ov && ov.skip) return;
    if ((ov && ov.candidate) || r.status === 'matched') count++;
  });
  const btn = document.getElementById('commitPreviewBtn');
  btn.textContent = `✅ 确认无误，立即将 ${count} 首曲目写入 ${PLATFORM_LABELS[selectedTargetPlatform]}`;
  btn.disabled = count === 0;
}

function renderJobProgress(job) {
  const pct = job.total > 0 ? Math.round((job.current_index / job.total) * 100) : 0;
  document.getElementById('jobPercentLabel').textContent = `${pct}% (${job.current_index}/${job.total})`;
  document.getElementById('jobProgressBar').style.width = `${pct}%`;
  document.getElementById('currentTrackLabel').textContent = job.current_track || '-';

  document.getElementById('statTotal').textContent = job.total || 0;
  document.getElementById('statDone').textContent = job.current_index || 0;
  document.getElementById('statMatched').textContent = job.matched_count || 0;
  document.getElementById('statLowConf').textContent = job.low_confidence_count || 0;
  document.getElementById('statUnmatched').textContent = job.unmatched_count || 0;

  const isPreview = job.job_type === 'preview';
  const tgtLabel = PLATFORM_LABELS[job.target_platform] || job.target_platform;
  const statusLabel = document.getElementById('jobStatusLabel');

  if (job.status === 'running') {
    statusLabel.textContent = isPreview
      ? `⏳ 正在多线程预匹配 ${tgtLabel} 曲库...`
      : `⏳ 正在并发匹配并写入 ${tgtLabel}...`;
    statusLabel.style.color = 'var(--text)';
  } else if (job.status === 'completed') {
    statusLabel.textContent = isPreview
      ? `🔍 预匹配完成！请核对下方列表（可筛选低置信度或手动替换），确认后点击绿色按钮写入 ${tgtLabel}`
      : `🎉 歌单迁移已完成！（成功导入 ${job.matched_count} 首${job.already_existed_count ? `，其中 ${job.already_existed_count} 首原歌单已存在自动防重` : ''}）`;
    statusLabel.style.color = 'var(--success)';
  } else if (job.status === 'cancelled') {
    statusLabel.textContent = job.pending_count
      ? `⏹ 任务已手动停止（尚有 ${job.pending_count} 首未处理，可点击「重试」继续）`
      : '⏹ 任务已手动停止';
    statusLabel.style.color = 'var(--warning)';
  } else if (job.status === 'interrupted') {
    statusLabel.textContent = `⚠️ 任务因服务关闭/重启而中断（尚有 ${job.pending_count || 0} 首未处理），可点击「重试未匹配/未完成曲目」继续`;
    statusLabel.style.color = 'var(--warning)';
  } else if (job.status === 'failed') {
    statusLabel.textContent = `❌ 任务失败：${job.error || ''}`;
    statusLabel.style.color = 'var(--danger)';
  }

  const warnings = [];
  if (job.error_count) warnings.push(`${job.error_count} 首因网络/限流搜索出错（重试通常即可成功）`);
  if (job.write_failed_count) warnings.push(`${job.write_failed_count} 首写入目标平台失败${job.last_write_error ? '：' + job.last_write_error : ''}`);
  if (warnings.length && job.status !== 'running') {
    statusLabel.textContent += `　⚠️ ${warnings.join('；')}`;
  }

  if (job.status !== 'running' && !isPreview) {
    const actions = document.getElementById('jobDoneActions');
    actions.style.display = 'flex';
    const openLink = document.getElementById('openTargetPlaylistLink');
    if (job.target_playlist_url) {
      openLink.href = job.target_playlist_url;
      openLink.textContent = `🎵 在 ${tgtLabel} 中打开该歌单`;
      openLink.style.display = 'inline-flex';
    } else {
      openLink.style.display = 'none';
    }
    const hasUnmatched = getRetryableTracks(job).length > 0;
    document.getElementById('retryUnmatchedBtn').style.display = hasUnmatched ? 'inline-flex' : 'none';
    document.getElementById('exportUnmatchedBtn').style.display = hasUnmatched ? 'inline-flex' : 'none';
  }

  renderJobResultsTable();
}

function getRetryableTracks(job) {
  if (!job) return [];
  return [...(job.unmatched_tracks || []), ...(job.pending_tracks || [])];
}

function setResultFilter(f) {
  resultFilter = f;
  document.querySelectorAll('.filter-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === f);
  });
  renderJobResultsTable();
}

function renderJobResultsTable() {
  const tbody = document.getElementById('jobResultsTbody');
  tbody.innerHTML = '';
  if (!currentJobData) return;

  const isPreview = currentJobData.job_type === 'preview';
  const rows = currentJobData.status === 'running'
    ? [...(currentJobData.results || [])].reverse()
    : (currentJobData.results || []);

  rows.forEach(r => {
    const idx = r.track_index !== undefined ? r.track_index : r.index - 1;
    const ov = isPreview ? previewOverrides[idx] : null;
    const effectiveCand = ov && ov.candidate ? ov.candidate : r.candidate;
    const isSkipped = ov ? !!ov.skip : r.status === 'skipped';
    const isMatched = !isSkipped && (Boolean(effectiveCand && effectiveCand.track_id) || r.status === 'matched');
    const conf = ov && ov.candidate ? 'manual' : (r.confidence || (isMatched ? 'high' : 'unmatched'));

    if (resultFilter === 'high' && !(isMatched && (conf === 'high' || conf === 'manual'))) return;
    if (resultFilter === 'low' && conf !== 'low') return;
    if (resultFilter === 'unmatched' && isMatched) return;

    let badgeHtml = '';
    if (isSkipped) {
      badgeHtml = `<span class="pill pill-muted">已跳过</span>`;
    } else if (r.status === 'error' && !(ov && ov.candidate)) {
      badgeHtml = `<span class="pill pill-warn">⚠️ 搜索出错</span>`;
    } else if (!isMatched) {
      badgeHtml = `<span class="pill pill-fail">未匹配</span>`;
    } else if (r.write_failed) {
      badgeHtml = `<span class="pill pill-fail">写入失败</span>`;
    } else if (conf === 'manual') {
      badgeHtml = `<span class="pill pill-info">🎯 人工指定</span>`;
    } else if (conf === 'low') {
      badgeHtml = `<span class="pill pill-warn">⚠️ 低置信 (${r.score || ''})</span>`;
    } else {
      badgeHtml = `<span class="pill pill-ok">✅ 高置信 (${r.score || ''})</span>`;
    }

    const mTitle = (effectiveCand && effectiveCand.title) || r.matched_title || r.ytm_title || '';
    const mArtist = (effectiveCand && effectiveCand.artist) || r.matched_artist || r.ytm_artist || '';
    const mDur = (effectiveCand && effectiveCand.duration) || r.matched_duration || r.ytm_duration || '';
    const mUrl = (effectiveCand && effectiveCand.url) || r.matched_url ||
      (r.ytm_video_id ? `https://music.youtube.com/watch?v=${encodeURIComponent(r.ytm_video_id)}` : '');
    const mReason = (ov && ov.candidate) ? '人工指定替换' : (r.match_reason || '');

    const checkboxHtml = isPreview
      ? `<input type="checkbox" ${!isSkipped && isMatched ? 'checked' : ''} ${!isMatched ? 'disabled' : ''}
           onchange="togglePreviewRowSkip(${idx}, !this.checked)"
           style="width:15px;height:15px;accent-color:var(--spotify);margin-right:6px;cursor:pointer;" />`
      : '';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="color: var(--text-muted); white-space: nowrap;">${checkboxHtml}${r.index}</td>
      <td>
        <div style="font-weight: 600;">${escapeHtml(r.source_title)}</div>
        <div style="font-size: 12px; color: var(--text-muted);">${escapeHtml(r.source_artist)}</div>
      </td>
      <td>
        ${badgeHtml}
        ${r.already_existed ? '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">已在歌单中</div>' : ''}
      </td>
      <td>
        ${isMatched
          ? `<div>
               ${mUrl
                 ? `<a href="${escapeHtml(mUrl)}" target="_blank" style="color: #93c5fd; text-decoration: none; font-weight: 600;">${escapeHtml(mTitle)} ↗</a>`
                 : `<span style="font-weight: 600;">${escapeHtml(mTitle)}</span>`
               }
             </div>
             <div style="font-size: 12px; color: var(--text-muted);">
               ${escapeHtml(mArtist)}${mDur ? ' · ' + escapeHtml(mDur) : ''}${mReason ? ' · <span style="opacity:0.8">' + escapeHtml(mReason) + '</span>' : ''}
             </div>`
          : `<span style="color: var(--text-muted); font-size: 12px;">${r.status === 'error' ? escapeHtml(r.match_reason || '搜索出错') : '未搜索到可靠匹配，可点击右侧手动指定'}</span>`
        }
      </td>
      <td>
        <button class="btn-mini" onclick="openManualModal(${idx})">
          🔍 ${isMatched ? '替换' : '搜歌补录'}
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function togglePreviewRowSkip(idx, skip) {
  previewOverrides[idx] = { ...(previewOverrides[idx] || {}), skip };
  updateCommitPreviewButtonCount();
  renderJobResultsTable();
}

async function cancelActiveJob() {
  if (!currentJobId) return;
  await fetch(`/api/migrate/cancel/${currentJobId}`, { method: 'POST' });
}

function loadUnmatchedForRetry() {
  const retryTracks = getRetryableTracks(currentJobData);
  if (!retryTracks.length) return;
  document.getElementById('appendTracksModeCheckbox').checked = false;
  applyIncomingTracks(
    retryTracks,
    (currentJobData.playlist_title || 'Playlist') + ' (未匹配重试)',
    currentJobData.source_platform || 'retry'
  );
  window.scrollTo({ top: 180, behavior: 'smooth' });
}

async function exportUnmatchedCsv() {
  const retryTracks = getRetryableTracks(currentJobData);
  if (!retryTracks.length) return;
  await triggerCsvDownload(`${currentJobData.playlist_title || 'Playlist'}_未匹配曲目`, retryTracks);
}

async function exportFullJobReportCsv() {
  if (!currentJobData || !(currentJobData.results || []).length) return;
  await triggerCsvDownload(`${currentJobData.playlist_title || 'Migration'}_完整报告`, currentJobData.results);
}

// ---------------------------------------------------------------------------
// 4. Manual Search & Candidate Override / Backfill Modal
// ---------------------------------------------------------------------------

function openManualModal(trackIdx) {
  if (!currentJobData) return;
  const row = (currentJobData.results || []).find(
    r => (r.track_index !== undefined ? r.track_index : r.index - 1) === trackIdx
  );
  if (!row) return;

  manualModalTrackIdx = trackIdx;
  const tgtPlat = currentJobData.target_platform || selectedTargetPlatform;
  document.getElementById('manualSourceInfo').textContent =
    `原曲：${row.source_title} - ${row.source_artist}  →  搜索目标平台：${PLATFORM_LABELS[tgtPlat]}`;
  document.getElementById('manualSearchInput').value = `${row.source_title} ${row.source_artist}`.trim();
  document.getElementById('manualModalBody').innerHTML = '';
  document.getElementById('manualMatchModal').classList.add('open');
  executeManualSearch();
}

function closeManualModal() {
  manualModalTrackIdx = null;
  document.getElementById('manualMatchModal').classList.remove('open');
}

async function executeManualSearch() {
  const query = document.getElementById('manualSearchInput').value.trim();
  if (!query || !currentJobData) return;
  const tgtPlat = currentJobData.target_platform || selectedTargetPlatform;
  const row = (currentJobData.results || []).find(
    r => (r.track_index !== undefined ? r.track_index : r.index - 1) === manualModalTrackIdx
  );
  const bodyEl = document.getElementById('manualModalBody');
  const btn = document.getElementById('manualSearchBtn');
  btn.disabled = true;
  bodyEl.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">⏳ 正在搜索候选曲目...</div>';

  try {
    const res = await fetch('/api/search/candidates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform: tgtPlat,
        query,
        limit: 10,
        source_track: row ? row.source_track : null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '搜索失败');
    manualModalCandidates = data.candidates || [];

    if (!manualModalCandidates.length) {
      bodyEl.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">未搜到相关歌曲，请尝试简化歌名或切换中英文名再试</div>';
      return;
    }

    bodyEl.innerHTML = '';
    manualModalCandidates.forEach((c, cIdx) => {
      const div = document.createElement('div');
      div.className = 'cand-item';
      const scoreBadge = c.score !== undefined
        ? `<span class="pill ${c.score >= 65 ? 'pill-ok' : c.score >= 38 ? 'pill-warn' : 'pill-muted'}">${c.score} 分</span>`
        : '';
      div.innerHTML = `
        <div style="flex: 1; min-width: 0;">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span style="font-weight: 700;">${escapeHtml(c.title)}</span>
            ${scoreBadge}
            ${c.url ? `<a href="${escapeHtml(c.url)}" target="_blank" style="font-size: 12px; color: #93c5fd; text-decoration: none;">▶ 试听</a>` : ''}
          </div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
            ${escapeHtml(c.artist)}${c.album ? ' · 专辑: ' + escapeHtml(c.album) : ''}${c.duration ? ' · ' + escapeHtml(c.duration) : ''}
          </div>
        </div>
        <button class="btn btn-spotify" style="padding: 6px 13px; font-size: 12.5px;" onclick="selectManualCandidate(${cIdx})">
          ✅ 选用此曲
        </button>
      `;
      bodyEl.appendChild(div);
    });
  } catch (err) {
    bodyEl.innerHTML = `<div style="padding: 16px; color: var(--danger);">❌ ${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

async function selectManualCandidate(cIdx) {
  const cand = manualModalCandidates[cIdx];
  if (!cand || manualModalTrackIdx === null || !currentJobData) return;

  if (currentJobData.job_type === 'preview') {
    previewOverrides[manualModalTrackIdx] = { skip: false, candidate: cand };
    closeManualModal();
    updateCommitPreviewButtonCount();
    renderJobResultsTable();
    return;
  }

  // Completed migration job -> immediately write to target playlist/liked songs & update job!
  try {
    const res = await fetch('/api/migrate/manual-apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_platform: currentJobData.target_platform,
        target_mode: currentJobData.target_mode === 'liked_songs' ? 'liked_songs' : 'existing_playlist',
        playlist_id: currentJobData.target_playlist_id,
        candidate: cand,
        job_id: currentJobData.job_id,
        result_index: manualModalTrackIdx,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '补录失败');
    closeManualModal();
    await pollJobStatus();
  } catch (err) {
    alert('❌ ' + err.message);
  }
}

// ---------------------------------------------------------------------------
// 5. Multi-Platform Playlist Deduplicator (View 2)
// ---------------------------------------------------------------------------

async function loadDedupePlaylists(showErr = false) {
  const plat = document.getElementById('dedupePlatformSelect').value;
  const sel = document.getElementById('dedupePlaylistSelect');
  sel.innerHTML = '<option value="">正在加载歌单...</option>';
  try {
    const includeLiked = LINK_READ_PLATFORMS.includes(plat);
    const res = await fetch(`/api/platforms/${plat}/playlists?include_liked=${includeLiked}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '获取失败');
    const list = (data.playlists || []).filter(p => p.editable !== false);
    sel.innerHTML = '';
    if (!list.length) {
      sel.innerHTML = '<option value="">-- 暂无可去重的自建歌单 --</option>';
      return;
    }
    list.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id || p.playlistId;
      opt.textContent = `${p.name || p.title} (${p.count ?? 0} 首)`;
      sel.appendChild(opt);
    });
  } catch (err) {
    sel.innerHTML = `<option value="">-- 请先在顶部连接 ${PLATFORM_LABELS[plat]} --</option>`;
    if (showErr) showAlert('dedupeAlert', 'error', '❌ ' + err.message);
  }
}

async function scanPlatformDuplicates() {
  const plat = document.getElementById('dedupePlatformSelect').value;
  const pid = document.getElementById('dedupePlaylistSelect').value;
  const mode = document.getElementById('dedupeModeSelect').value;
  if (!pid) {
    showAlert('dedupeAlert', 'error', '请先选择一个要检查的歌单（或先点击顶部对应平台登录并刷新）！');
    return;
  }

  hideAlert('dedupeAlert');
  const btn = document.getElementById('scanDupBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 正在读取歌单并分析重复组...';

  try {
    const res = await fetch(
      `/api/platforms/${plat}/playlist/${encodeURIComponent(pid)}/duplicates?mode=${encodeURIComponent(mode)}`
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '扫描歌单失败');

    scannedDupPlatform = plat;
    scannedDupPlaylistId = pid;
    scannedDupTotal = data.total_tracks || 0;
    scannedDupGroups = (data.groups || []).map(g => ({
      ...g,
      items: g.items.map(it => ({
        ...it,
        selectedRemove: Boolean(it.default_remove && it.can_remove),
      })),
    }));

    document.getElementById('dedupeResultBox').style.display = 'block';
    document.getElementById('dupStatTotal').textContent = scannedDupTotal;
    document.getElementById('dupStatFound').textContent = scannedDupGroups.length;

    if (!scannedDupGroups.length) {
      document.getElementById('dupStatUnique').textContent = scannedDupTotal;
      document.getElementById('dedupeTableArea').style.display = 'none';
      showAlert('dedupeAlert', 'success', `🎉 扫描完成！「${data.playlist_title}」共 ${scannedDupTotal} 首歌，未发现重复曲目！`);
    } else {
      document.getElementById('dedupeTableArea').style.display = 'block';
      renderPlatformDupGroups();
      showAlert(
        'dedupeAlert',
        'info',
        `🔍 在「${data.playlist_title}」中发现 ${scannedDupGroups.length} 组重复曲目，可自由勾选或点「🔄 改为只留这首」切换保留项！`
      );
    }
  } catch (err) {
    showAlert('dedupeAlert', 'error', '❌ ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 扫描重复曲目';
  }
}

function renderPlatformDupGroups() {
  const container = document.getElementById('dupGroupsContainer');
  container.innerHTML = '';
  let totalSelected = 0;

  scannedDupGroups.forEach((g, gIdx) => {
    const allChecked = g.items.every(it => it.selectedRemove);
    let rowsHtml = '';
    g.items.forEach((it, iIdx) => {
      if (it.selectedRemove) totalSelected++;
      rowsHtml += `
        <div class="dup-row ${it.selectedRemove ? 'marked-remove' : 'marked-keep'}">
          <input type="checkbox" ${it.selectedRemove ? 'checked' : ''} ${it.can_remove ? '' : 'disabled'}
            onchange="togglePlatDupItem(${gIdx}, ${iIdx}, this.checked)"
            style="width: 16px; height: 16px; accent-color: var(--ytm); cursor: pointer;" />
          <span class="pill ${it.selectedRemove ? 'pill-fail' : 'pill-ok'}" style="min-width: 58px; justify-content: center;">
            ${it.selectedRemove ? '🗑️ 删除' : '✅ 保留'}
          </span>
          <span style="color: var(--text-muted); font-weight: 600; min-width: 42px;">#${it.position}</span>
          <div style="flex: 1; min-width: 0;">
            <div style="font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span>${escapeHtml(it.title)}</span>
              ${it.url ? `<a href="${escapeHtml(it.url)}" target="_blank" style="font-size: 11.5px; color: #93c5fd; text-decoration: none;">▶ 试听</a>` : ''}
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">
              ${escapeHtml(it.artist)}${it.album ? ' · 专辑: ' + escapeHtml(it.album) : ''}${it.duration ? ' · ' + escapeHtml(it.duration) : ''}
            </div>
          </div>
          ${it.selectedRemove
            ? `<button class="btn-mini" onclick="keepOnlyThisInPlatGroup(${gIdx}, ${iIdx})">🔄 改为只留这首</button>`
            : `<span style="font-size: 11.5px; color: #6ee7b7; font-weight: 600;">当前保留</span>`
          }
        </div>
      `;
    });

    const div = document.createElement('div');
    div.className = 'dup-group';
    div.innerHTML = `
      <div class="dup-group-header">
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span>第 ${gIdx + 1} 组重复（共 ${g.items.length} 首）</span>
          <span class="pill ${g.reason_code === 'exact_id' ? 'pill-fail' : 'pill-warn'}">${escapeHtml(g.reason)}</span>
        </div>
        ${allChecked ? '<span style="color: var(--warning);">⚠️ 注意：该组全部被勾选，将整组删除</span>' : ''}
      </div>
      ${rowsHtml}
    `;
    container.appendChild(div);
  });

  document.getElementById('selectedDupCount').textContent = totalSelected;
  document.getElementById('dupStatUnique').textContent = Math.max(0, scannedDupTotal - totalSelected);
  document.getElementById('removeDupBtn').disabled = totalSelected === 0;
}

function togglePlatDupItem(gIdx, iIdx, checked) {
  const it = scannedDupGroups[gIdx].items[iIdx];
  if (!it.can_remove) return;
  it.selectedRemove = checked;
  renderPlatformDupGroups();
}

function keepOnlyThisInPlatGroup(gIdx, keepIdx) {
  scannedDupGroups[gIdx].items.forEach((it, idx) => {
    it.selectedRemove = it.can_remove ? idx !== keepIdx : false;
  });
  renderPlatformDupGroups();
}

function applyDedupeGroupPreset(preset) {
  scannedDupGroups.forEach(g => {
    const last = g.items.length - 1;
    g.items.forEach((it, idx) => {
      if (!it.can_remove) {
        it.selectedRemove = false;
        return;
      }
      if (preset === 'keep_first') it.selectedRemove = idx !== 0;
      else if (preset === 'keep_last') it.selectedRemove = idx !== last;
      else if (preset === 'exact_only') it.selectedRemove = idx !== 0 && it.reason_code === 'exact_id';
      else if (preset === 'none') it.selectedRemove = false;
    });
  });
  renderPlatformDupGroups();
}

async function removeSelectedPlatformDuplicates() {
  const items = [];
  scannedDupGroups.forEach(g => {
    g.items.forEach(it => {
      if (it.selectedRemove && it.can_remove) {
        items.push({
          item_id: it.item_id || '',
          videoId: it.videoId || '',
          setVideoId: it.setVideoId || '',
          extra: it.extra || {},
        });
      }
    });
  });
  if (!items.length || !scannedDupPlaylistId) return;

  const btn = document.getElementById('removeDupBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 正在从歌单移除...';

  try {
    const res = await fetch(
      `/api/platforms/${scannedDupPlatform}/playlist/${encodeURIComponent(scannedDupPlaylistId)}/remove-duplicates`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      }
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '移除失败');

    showAlert('dedupeAlert', 'success', `✅ 已成功移除 ${data.removed_count} 首重复歌曲！正在重新扫描确认...`);
    await scanPlatformDuplicates();
  } catch (err) {
    showAlert('dedupeAlert', 'error', '❌ ' + err.message);
    renderPlatformDupGroups();
  }
}

// ---------------------------------------------------------------------------
// 6. Playlist CSV Backup & Export (View 3)
// ---------------------------------------------------------------------------

async function triggerCsvDownload(playlistName, tracks) {
  const res = await fetch('/api/export/csv', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlist_name: playlistName, tracks }),
  });
  if (!res.ok) {
    const err = await res.json();
    alert('❌ 导出失败: ' + (err.detail || '未知错误'));
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${playlistName}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function loadExportPlaylists(showErr = false) {
  const plat = document.getElementById('exportPlatformSelect').value;
  const sel = document.getElementById('exportPlaylistSelect');
  sel.innerHTML = '<option value="">正在读取...</option>';
  try {
    const res = await fetch(`/api/platforms/${plat}/playlists?include_liked=true`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '读取失败');
    sel.innerHTML = '';
    (data.playlists || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id || p.playlistId;
      opt.textContent = `${p.name || p.title} (${p.count ?? ''} 首)`;
      sel.appendChild(opt);
    });
  } catch (err) {
    sel.innerHTML = `<option value="">-- 请先连接 ${PLATFORM_LABELS[plat]} --</option>`;
    if (showErr) showAlert('exportAlert', 'error', '❌ ' + err.message);
  }
}

function downloadSelectedPlaylistCsv() {
  const plat = document.getElementById('exportPlatformSelect').value;
  const pid = document.getElementById('exportPlaylistSelect').value;
  if (!pid) {
    showAlert('exportAlert', 'error', '请先选择一个要导出的歌单！');
    return;
  }
  window.open(`/api/platforms/${plat}/playlist/${encodeURIComponent(pid)}/export-csv`, '_blank');
}

async function exportUrlPlaylistCsv() {
  const urlVal = document.getElementById('exportUrlInput').value.trim();
  if (!urlVal) {
    showAlert('exportAlert', 'error', '请输入公开歌单分享链接！');
    return;
  }
  const btn = document.getElementById('exportUrlBtn');
  btn.disabled = true;
  showAlert('exportAlert', 'info', '⏳ 正在拉取歌单曲目并生成 CSV...');
  try {
    const res = await fetch('/api/import/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform: 'auto', url_or_id: urlVal }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '读取失败');
    await triggerCsvDownload(data.playlist_name || 'Exported_Playlist', data.tracks);
    showAlert('exportAlert', 'success', `✅ 已成功导出「${data.playlist_name}」（共 ${data.count} 首）！`);
  } catch (err) {
    showAlert('exportAlert', 'error', '❌ ' + err.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// 7. Scheduled Incremental Sync & Migration History (View 4)
// ---------------------------------------------------------------------------

async function loadSyncSourcePlaylists() {
  const plat = document.getElementById('syncSrcPlat').value;
  const sel = document.getElementById('syncSrcPlaylist');
  sel.innerHTML = '<option value="">读取中...</option>';
  try {
    const res = await fetch(`/api/platforms/${plat}/playlists?include_liked=true`);
    const data = await res.json();
    if (!res.ok) throw new Error();
    sel.innerHTML = '';
    (data.playlists || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id || p.playlistId;
      opt.textContent = p.name || p.title;
      sel.appendChild(opt);
    });
  } catch {
    sel.innerHTML = `<option value="">请先连接 ${PLATFORM_LABELS[plat]}</option>`;
  }
}

async function loadSyncTargetPlaylists() {
  const plat = document.getElementById('syncTgtPlat').value;
  const sel = document.getElementById('syncTgtPlaylist');
  sel.innerHTML = '<option value="__LIKED__">❤️ 我喜欢的音乐 (Liked)</option>';
  try {
    const res = await fetch(`/api/platforms/${plat}/playlists?include_liked=false`);
    const data = await res.json();
    if (!res.ok) return;
    (data.playlists || []).filter(p => p.editable !== false).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id || p.playlistId;
      opt.textContent = p.name || p.title;
      sel.appendChild(opt);
    });
  } catch {
    // Keep Liked option available
  }
}

async function createSyncTask() {
  const srcPlat = document.getElementById('syncSrcPlat').value;
  const srcSel = document.getElementById('syncSrcPlaylist');
  const srcPid = srcSel.value;
  const srcName = srcSel.options[srcSel.selectedIndex]?.text || srcPid;

  const tgtPlat = document.getElementById('syncTgtPlat').value;
  const tgtSel = document.getElementById('syncTgtPlaylist');
  const tgtVal = tgtSel.value;
  const tgtName = tgtSel.options[tgtSel.selectedIndex]?.text || '';

  if (!srcPid) {
    showAlert('syncAlert', 'error', '请先选择有效的源平台歌单！');
    return;
  }

  const isLiked = tgtVal === '__LIKED__';
  const nameInput = document.getElementById('syncRuleName').value.trim();
  const interval = parseInt(document.getElementById('syncIntervalSelect').value, 10) || 120;

  try {
    const res = await fetch('/api/sync/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: nameInput || `${PLATFORM_LABELS[srcPlat]} → ${PLATFORM_LABELS[tgtPlat]}`,
        source_platform: srcPlat,
        source_playlist_id: srcPid,
        source_playlist_name: srcName,
        target_platform: tgtPlat,
        target_mode: isLiked ? 'liked_songs' : 'existing_playlist',
        target_playlist_id: isLiked ? null : tgtVal,
        target_playlist_name: tgtName,
        interval_minutes: interval,
        enabled: true,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '创建失败');
    showAlert('syncAlert', 'success', '✅ 定时增量同步规则已添加！点击「▶ 立即同步」即可执行首次增量扫描。');
    loadSyncTasks();
  } catch (err) {
    showAlert('syncAlert', 'error', '❌ ' + err.message);
  }
}

async function loadSyncTasks() {
  const tbody = document.getElementById('syncTasksTbody');
  try {
    const res = await fetch('/api/sync/tasks');
    const data = await res.json();
    const tasks = data.tasks || [];
    tbody.innerHTML = '';
    if (!tasks.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">暂无定时同步规则</td></tr>';
      return;
    }
    tasks.forEach(t => {
      const tr = document.createElement('tr');
      const statusBadge = t.is_running_now || t.last_status === 'running'
        ? '<span class="pill pill-info">⏳ 同步中</span>'
        : t.last_status === 'error'
          ? '<span class="pill pill-fail">异常</span>'
          : `<span class="pill ${t.enabled ? 'pill-ok' : 'pill-muted'}">${t.enabled ? '运行中' : '已暂停'}</span>`;
      tr.innerHTML = `
        <td>
          <div style="font-weight: 600;">${escapeHtml(t.name)}</div>
          <div style="font-size: 11.5px; color: var(--text-muted);">已记录 ${t.known_tracks_count || 0} 首 · 累计同步 ${t.total_synced_count || 0} 首</div>
        </td>
        <td style="font-size: 12.5px;">
          <div>${escapeHtml(PLATFORM_LABELS[t.source_platform] || t.source_platform)}: ${escapeHtml(t.source_playlist_name)}</div>
          <div style="color: var(--text-muted);">→ ${escapeHtml(PLATFORM_LABELS[t.target_platform] || t.target_platform)}: ${escapeHtml(t.target_playlist_name)}</div>
        </td>
        <td style="font-size: 12.5px;">每 ${t.interval_minutes} 分钟<div style="margin-top:3px;">${statusBadge}</div></td>
        <td style="font-size: 12px; color: var(--text-muted);">
          <div>${escapeHtml(t.last_message || '-')}</div>
          ${t.last_run_at ? `<div style="margin-top:2px;">上次: ${escapeHtml(t.last_run_at)}</div>` : ''}
        </td>
        <td>
          <div style="display: flex; gap: 5px; flex-wrap: wrap;">
            <button class="btn-mini" onclick="runSyncTaskNow('${t.id}')">▶ 立即同步</button>
            <button class="btn-mini" onclick="toggleSyncTask('${t.id}', ${!t.enabled})">${t.enabled ? '⏸ 暂停' : '启用'}</button>
            <button class="btn-mini" onclick="deleteSyncTask('${t.id}')">🗑️</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

async function runSyncTaskNow(id) {
  await fetch(`/api/sync/tasks/${id}/run`, { method: 'POST' });
  loadSyncTasks();
  setTimeout(loadSyncTasks, 2500);
}

async function toggleSyncTask(id, enabled) {
  await fetch(`/api/sync/tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  loadSyncTasks();
}

async function deleteSyncTask(id) {
  await fetch(`/api/sync/tasks/${id}`, { method: 'DELETE' });
  loadSyncTasks();
}

async function loadHistoryList() {
  const tbody = document.getElementById('historyTbody');
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    const list = data.history || [];
    tbody.innerHTML = '';
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">暂无历史迁移记录</td></tr>';
      return;
    }
    list.forEach(h => {
      const tr = document.createElement('tr');
      const ok = h.status === 'completed';
      tr.innerHTML = `
        <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(h.completed_at || h.started_at || '-')}</td>
        <td>
          <div style="font-weight: 600;">${escapeHtml(PLATFORM_LABELS[h.target_platform] || h.target_platform)} · ${escapeHtml(h.playlist_title || '歌单')}</div>
          ${h.target_playlist_url ? `<a href="${escapeHtml(h.target_playlist_url)}" target="_blank" style="font-size:11.5px;color:#93c5fd;text-decoration:none;">打开目标歌单 ↗</a>` : ''}
        </td>
        <td><span class="pill ${ok ? 'pill-ok' : 'pill-warn'}">${escapeHtml(h.status)}</span></td>
        <td style="font-size: 12.5px;">
          共 ${h.total || 0} 首 · <span style="color:var(--success)">成功 ${h.matched_count || 0}</span> · <span style="color:var(--danger)">未匹配 ${h.unmatched_count || 0}</span>
        </td>
        <td>
          <div style="display: flex; gap: 6px;">
            <button class="btn-mini" onclick="openHistoryJob('${h.job_id}')">📂 查看详情 / 补录</button>
            <button class="btn-mini" onclick="deleteHistoryJob('${h.job_id}')">🗑️</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

async function openHistoryJob(jobId) {
  currentJobId = jobId;
  switchMainView('migrate');
  document.getElementById('migrationProgressBox').style.display = 'block';
  await pollJobStatus();
  document.getElementById('migrationProgressBox').scrollIntoView({ behavior: 'smooth' });
}

async function deleteHistoryJob(jobId) {
  await fetch(`/api/history/${jobId}`, { method: 'DELETE' });
  loadHistoryList();
}

async function clearAllHistory() {
  await fetch('/api/history', { method: 'DELETE' });
  loadHistoryList();
}
