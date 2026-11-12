/* Switch Music v2.3 Bilingual (zh-CN / en-US) Dictionary & Helpers */

const UI_I18N = {
  zh: {
    doc_title: 'Switch Music v2.3 · 全平台歌单互转、去重与同步工作台',
    version_tag: 'v2.3 全平台版',
    brand_subtitle: '本地无限制歌单互转 · 预匹配人工微调 · 歌单去重 · 增量/镜像/双向同步（Spotify ⇄ YouTube Music ⇄ 网易云 ⇄ QQ音乐 ⇄ 酷狗 ⇄ Apple Music ⇄ Navidrome + 汽水音乐导入）',
    lang_toggle_btn: '🌐 English',
    btn_refresh_platforms: '🔄 刷新平台状态',
    btn_cache_manager: '⚡ 匹配缓存管理',

    plat_checking: '检测中...',
    plat_connected_user: '已连接: {name}',
    plat_connected_generic: '已连接 (点击管理)',
    plat_unconnected_link: '未登录 · 支持链接直读',
    plat_unconnected_cfg: '未连接 · 点击配置',

    drawer_title_prefix: '连接管理 · ',
    btn_disconnect: '断开连接 / 清除凭据',
    btn_collapse_drawer: '收起面板 ✕',
    kugou_qr_title: '📱 推荐：酷狗 App 扫码登录',
    kugou_qr_desc: '打开手机「酷狗音乐」App → 右上角扫一扫，扫描右侧二维码并确认登录。登录凭据仅保存在本地 data/ 目录。',
    btn_kugou_qr: '生成登录二维码',
    cookie_placeholder: '在此粘贴右键 Copy → Copy as cURL 的内容（或 Request Headers / Cookie 字符串 / cookies.txt）',
    btn_save_cookie: '验证并保存连接',
    sp_guide_summary: '💡 如何获取 Spotify Developer Client ID & Secret？（支持双向读写歌单）',
    btn_sp_oauth: '保存并前往 Spotify OAuth 授权登录',
    subsonic_guide_summary: '💡 连接自建 Navidrome / Subsonic / OpenSubsonic 音乐服务器（支持双向歌单读写与去重）',
    subsonic_url_label: '服务器地址 (Server URL)',
    subsonic_user_label: '用户名 (Username)',
    subsonic_pass_label: '密码 (Password · 采用 Subsonic 盐值 Token 认证)',
    btn_save_subsonic: '验证并连接 Navidrome / Subsonic',

    nav_migrate: '⇄ 跨平台歌单互转',
    nav_dedupe: '🧹 全平台歌单去重',
    nav_export: '📤 多格式导出备份',
    nav_sync: '⏱️ 定时同步 & 通知守护',

    step1_title: '加载源歌单（支持网易云 / QQ音乐 / 酷狗 / 汽水音乐 / Apple Music / Spotify / YTM / Navidrome / CSV / M3U8）',
    loaded_none: '尚未加载曲目',
    loaded_ready: '已就绪 {count} 首歌曲',
    src_tab_url: '🔗 链接直读（网易云/QQ/酷狗/汽水/Apple/YTM 免登录）',
    src_tab_account: '☁️ 从已连接账号选择歌单',
    src_tab_csv: '📂 上传 CSV / M3U8 / JSON',
    src_tab_text: '📝 粘贴纯文本歌单',
    url_guide_summary: '💡 支持哪些歌单分享链接？（点击查看示例）',
    opt_auto_detect: '✨ 自动识别平台',
    opt_qishui_url: '汽水音乐（免登录分享链接）',
    opt_spotify_login: 'Spotify (需已登录)',
    url_input_placeholder: '粘贴网易云 / QQ音乐 / 酷狗 / 汽水音乐 / Apple Music / YouTube Music 歌单分享链接、分享口令或 ID...',
    btn_parse_url: '📥 解析歌单',

    lbl_select_src_plat: '选择源平台（需已在顶部连接）',
    lbl_select_src_playlist: '选择要读取的歌单',
    btn_refresh: '🔄 刷新',
    btn_fetch_account_tracks: '📥 加载选中歌单曲目',

    csv_guide_summary: '💡 支持导出/导入哪些本地歌单文件？',
    dropzone_title: '📥 点击选择或将 CSV / M3U8 / TSV / JSON 歌单文件拖拽至此',
    dropzone_sub: '完美兼容 Exportify CSV、#EXTM3U (.m3u / .m3u8 · Jellyfin / Navidrome / foobar2000) 与 JSON 备份（无数量上限）',
    btn_parse_text: '📥 解析文本歌单',
    lbl_append_mode: '追加合并模式（勾选后新加载的歌单将合并追加到当前列表，可混合多平台歌单）',

    lbl_pending_tracks_prefix: '待迁移列表（共 ',
    lbl_pending_tracks_suffix: ' 首）',
    source_filter_placeholder: '🔎 搜索过滤歌名/歌手...',
    btn_src_dedupe: '🧹 源列表查重',
    btn_export_csv_short: '📤 CSV',
    btn_export_m3u8_short: '🎵 M3U8',
    btn_export_json_short: '📦 JSON',
    btn_clear_list: '清空列表',
    th_title: '歌曲标题',
    th_artist: '歌手',
    th_album: '专辑',
    th_duration: '时长',
    th_actions: '操作',

    step2_title: '选择目标平台、预匹配微调与批量导入',
    lbl_target_plat: '选择要导入的目标音乐平台',
    tgt_sub_ytm: '新建 / 追加 / 红心',
    tgt_sub_netease: '新建 / 追加 / 我喜欢',
    tgt_sub_qqmusic: '新建 / 追加 / 我喜欢',
    tgt_sub_spotify: '新建 / 追加 / Liked',
    tgt_sub_kugou: '新建 / 追加 / 我喜欢',
    tgt_sub_applemusic: '新建 / 追加 / 资料库',
    tgt_sub_subsonic: '新建 / 追加 / Starred',

    lbl_write_mode: '写入模式',
    opt_mode_new: '✨ 在目标平台新建歌单（推荐）',
    opt_mode_existing: '➕ 追加到现有的自建歌单',
    opt_mode_liked: '❤️ 直接加入目标平台「我喜欢的音乐 / Starred」',
    lbl_privacy: '新建歌单隐私属性',
    opt_priv_private: '🔒 私密歌单 (Private)',
    opt_priv_public: '🌍 公开歌单 (Public)',
    opt_priv_unlisted: '🔗 不公开链接可见 (仅 YouTube Music 支持)',
    lbl_new_title: '新建歌单名称',
    lbl_new_desc: '歌单简介 (可选)',
    lbl_existing_pl: '选择目标平台的现有歌单',
    lbl_concurrency: '搜索并发线程数（大型歌单加速）',
    lbl_min_score: '匹配最低置信度阈值（拦截错配/伴奏/翻唱）',
    lbl_skip_dup: '自动跳过目标歌单中已存在的重复歌曲',
    lbl_use_cache: '启用本地持久化匹配缓存（二次迁移/重试秒级命中）',
    btn_preview_match: '🔍 先预匹配并人工微调（不写入）',
    btn_direct_migrate: '🚀 直接一键匹配并导入到 {plat}',
    btn_stop_job: '⏹ 停止当前任务',

    stat_total: '总计曲目',
    stat_done: '已处理',
    stat_matched: '成功匹配',
    stat_low_conf: '低置信度留意',
    stat_unmatched: '未找到匹配',
    filter_all: '全部结果',
    filter_high: '✅ 高置信度',
    filter_low: '⚠️ 低置信度待核对',
    filter_unmatched: '❌ 未匹配',
    manual_tip: '💡 对任意不满意或未匹配的歌曲，点击右侧「🔍 替换 / 搜歌补录」即可手动指定并自动记入缓存！',
    th_src_track: '源曲目',
    th_conf_status: '置信度 / 状态',
    th_matched_track: '目标平台匹配结果',
    th_manual_fix: '人工微调',

    dedupe_header: '全平台歌单去重清理工具（支持 YTM / 网易云 / QQ音乐 / 酷狗 / Spotify / Navidrome，Apple Music 仅扫描）',
    lbl_dedupe_plat: '选择平台',
    lbl_dedupe_pl: '选择要扫描的自建歌单',
    lbl_dedupe_mode: '去重识别模式',
    btn_scan_dup: '🔍 扫描重复曲目',

    export_header: '歌单多格式导出备份（支持 CSV / M3U8 / JSON，兼容 Excel、Navidrome、Jellyfin 与跨工具恢复）',
    lbl_export_format: '选择导出文件格式',
    opt_fmt_csv: '📊 CSV 表格 (.csv · Excel 直接打开 / 兼容 Exportify)',
    opt_fmt_m3u8: '🎵 M3U8 播放列表 (.m3u8 · #EXTM3U 兼容 Jellyfin / Navidrome / 本地播放器)',
    opt_fmt_json: '📦 JSON 完整备份 (.json · 保留 ISRC、时长与平台 ID)',
    lbl_export_method1: '方式一：从已连接平台选择歌单导出（含 ❤️ 我喜欢的音乐 / Starred）',
    btn_export_selected: '📥 导出选中歌单备份',
    lbl_export_method2: '方式二：粘贴公开歌单链接免登录直接导出（支持网易云/QQ/酷狗/汽水/Apple Music/YTM）',
    btn_export_url: '📥 解析链接并下载备份',

    sync_header: '定时同步守护（支持单向增量追加、防误删镜像同步、双向无回声合并）',
    lbl_sync_src: '源平台 & 歌单（双向模式下为 A 端）',
    lbl_sync_tgt: '目标平台 & 位置（双向模式下为 B 端）',
    lbl_sync_interval_name: '同步周期 & 规则名称',
    lbl_sync_mode: '同步策略模式',
    opt_sync_append: '➕ 单向增量追加（仅同步源端新增曲目，最安全）',
    opt_sync_mirror: '🪞 单向镜像同步（源端移除时同步删除，内置防误删熔断）',
    opt_sync_twoway: '⇄ 双向合并同步（A ⇄ B 两端新增曲目互相同步且防回声）',
    lbl_mirror_guard: '镜像防误删熔断阈值（空快照保护 + 单次最大允许删除比例）',
    opt_ratio_20: '🛡️ 严格保护：单次最多允许删除 20%（超出自动熔断中止）',
    opt_ratio_30: '✨ 推荐阈值：单次最多允许删除 30%（超出自动熔断中止）',
    opt_ratio_50: '🌊 宽松阈值：单次最多允许删除 50%（超出自动熔断中止）',
    btn_add_sync: '➕ 添加定时同步规则',

    notif_header: '消息推送守护（Webhook / Bark / Telegram · 登录态失效或同步完成自动通知）',
    lbl_notif_enable: '启用消息推送通知',
    lbl_notif_on_err: '同步异常 / Cookie 过期 / 镜像熔断时告警',
    lbl_notif_on_ok: '同步成功并有曲目变更时推送摘要',
    lbl_notif_webhook: 'Webhook 地址（支持飞书 / 钉钉 / 企业微信 / Discord / Slack / 自定义 JSON）',
    lbl_notif_bark: 'Bark 推送地址或 Device Key（iOS 实时推送）',
    lbl_notif_tg_token: 'Telegram Bot Token（可选）',
    lbl_notif_tg_chat: 'Telegram Chat ID（可选）',
    btn_save_notif: '💾 保存推送配置',
    btn_test_notif: '📨 发送测试通知',

    history_header: '本地历史迁移任务记录',
    btn_clear_history: '清空历史',

    cache_modal_title: '⚡ 本地持久化匹配缓存管理（查看 / 搜索 / 单条纠错删除）',
    cache_filter_all_plat: '全部目标平台',
    cache_search_placeholder: '搜索源歌名、歌手、ISRC 或匹配结果...',
    btn_clear_all_cache: '🗑️ 清空全部缓存',
    cache_empty: '当前没有符合条件的匹配缓存记录',
  },

  en: {
    doc_title: 'Switch Music v2.3 · Universal Playlist Converter, Deduplicator & Sync Hub',
    version_tag: 'v2.3 Universal',
    brand_subtitle: 'Unlimited Local Playlist Migration · Pre-Match Review · Deduplication · Append / Mirror / 2-Way Sync (Spotify ⇄ YouTube Music ⇄ NetEase ⇄ QQ Music ⇄ Kugou ⇄ Apple Music ⇄ Navidrome + Qishui URL)',
    lang_toggle_btn: '🌐 简体中文',
    btn_refresh_platforms: '🔄 Refresh Status',
    btn_cache_manager: '⚡ Match Cache',

    plat_checking: 'Checking...',
    plat_connected_user: 'Connected: {name}',
    plat_connected_generic: 'Connected (Manage)',
    plat_unconnected_link: 'No Login · URL Direct OK',
    plat_unconnected_cfg: 'Not Connected · Click to Setup',

    drawer_title_prefix: 'Account Setup · ',
    btn_disconnect: 'Disconnect / Clear Credentials',
    btn_collapse_drawer: 'Close ✕',
    kugou_qr_title: '📱 Recommended: Scan QR with Kugou App',
    kugou_qr_desc: 'Open Kugou Music mobile app → Scan QR on the right and confirm login. Credentials stay locally in data/.',
    btn_kugou_qr: 'Generate Login QR',
    cookie_placeholder: 'Paste "Copy as cURL" output, Request Headers, Cookie string, or cookies.txt here...',
    btn_save_cookie: 'Verify & Save Connection',
    sp_guide_summary: '💡 How to get Spotify Developer Client ID & Secret? (Enables full read/write)',
    btn_sp_oauth: 'Save & Authorize via Spotify OAuth',
    subsonic_guide_summary: '💡 Connect Self-Hosted Navidrome / Subsonic / OpenSubsonic Server (Full Read/Write & Dedupe)',
    subsonic_url_label: 'Server URL (e.g. http://192.168.1.10:4533)',
    subsonic_user_label: 'Username',
    subsonic_pass_label: 'Password (Salted MD5 Subsonic Token Auth)',
    btn_save_subsonic: 'Verify & Connect Navidrome / Subsonic',

    nav_migrate: '⇄ Playlist Migration',
    nav_dedupe: '🧹 Playlist Deduplicator',
    nav_export: '📤 Multi-Format Backup',
    nav_sync: '⏱️ Scheduled Sync & Alerts',

    step1_title: 'Load Source Playlist (NetEase / QQ / Kugou / Qishui / Apple Music / Spotify / YTM / Navidrome / CSV / M3U8)',
    loaded_none: 'No tracks loaded',
    loaded_ready: '{count} tracks ready',
    src_tab_url: '🔗 Direct URL (No-Login Public Share)',
    src_tab_account: '☁️ From Connected Account',
    src_tab_csv: '📂 Upload CSV / M3U8 / JSON',
    src_tab_text: '📝 Paste Plain Text',
    url_guide_summary: '💡 Supported public playlist URLs & share links (click to view)',
    opt_auto_detect: '✨ Auto-Detect Platform',
    opt_qishui_url: 'Qishui / Soda Music (Public Share URL)',
    opt_spotify_login: 'Spotify (Requires Login)',
    url_input_placeholder: 'Paste NetEase / QQ Music / Kugou / Qishui / Apple Music / YouTube Music playlist URL or ID...',
    btn_parse_url: '📥 Fetch Playlist',

    lbl_select_src_plat: 'Source Platform (Connect in top bar first)',
    lbl_select_src_playlist: 'Select Playlist',
    btn_refresh: '🔄 Refresh',
    btn_fetch_account_tracks: '📥 Load Selected Playlist',

    csv_guide_summary: '💡 Supported local playlist file formats',
    dropzone_title: '📥 Click or drag CSV / M3U8 / TSV / JSON playlist files here',
    dropzone_sub: 'Supports Exportify CSV, #EXTM3U (.m3u / .m3u8 for Jellyfin / Navidrome / foobar2000) & JSON backups (unlimited tracks)',
    btn_parse_text: '📥 Parse Text Playlist',
    lbl_append_mode: 'Append & Merge Mode (append newly loaded tracks to current list across platforms)',

    lbl_pending_tracks_prefix: 'Loaded Source Tracks (',
    lbl_pending_tracks_suffix: ' total)',
    source_filter_placeholder: '🔎 Filter by title or artist...',
    btn_src_dedupe: '🧹 Check Duplicates',
    btn_export_csv_short: '📤 CSV',
    btn_export_m3u8_short: '🎵 M3U8',
    btn_export_json_short: '📦 JSON',
    btn_clear_list: 'Clear List',
    th_title: 'Title',
    th_artist: 'Artist',
    th_album: 'Album',
    th_duration: 'Duration',
    th_actions: 'Actions',

    step2_title: 'Select Target Platform, Pre-Match Review & Batch Import',
    lbl_target_plat: 'Target Music Platform',
    tgt_sub_ytm: 'New / Append / Liked',
    tgt_sub_netease: 'New / Append / Liked',
    tgt_sub_qqmusic: 'New / Append / Liked',
    tgt_sub_spotify: 'New / Append / Liked',
    tgt_sub_kugou: 'New / Append / Liked',
    tgt_sub_applemusic: 'New / Append / Library',
    tgt_sub_subsonic: 'New / Append / Starred',

    lbl_write_mode: 'Write Mode',
    opt_mode_new: '✨ Create New Playlist on Target (Recommended)',
    opt_mode_existing: '➕ Append to Existing Playlist',
    opt_mode_liked: '❤️ Add Directly to Liked Songs / Starred',
    lbl_privacy: 'New Playlist Privacy',
    opt_priv_private: '🔒 Private',
    opt_priv_public: '🌍 Public',
    opt_priv_unlisted: '🔗 Unlisted (YouTube Music only)',
    lbl_new_title: 'New Playlist Title',
    lbl_new_desc: 'Description (Optional)',
    lbl_existing_pl: 'Select Existing Target Playlist',
    lbl_concurrency: 'Search Concurrency (Speed up large playlists)',
    lbl_min_score: 'Minimum Match Confidence Threshold',
    lbl_skip_dup: 'Skip tracks that already exist in target playlist',
    lbl_use_cache: 'Use persistent local match cache (instant hit on re-runs)',
    btn_preview_match: '🔍 Pre-Match & Review First (Dry Run)',
    btn_direct_migrate: '🚀 Match & Import Directly to {plat}',
    btn_stop_job: '⏹ Stop Active Job',

    stat_total: 'Total',
    stat_done: 'Processed',
    stat_matched: 'Matched',
    stat_low_conf: 'Low Confidence',
    stat_unmatched: 'Unmatched',
    filter_all: 'All',
    filter_high: '✅ High Confidence',
    filter_low: '⚠️ Low Confidence',
    filter_unmatched: '❌ Unmatched',
    manual_tip: '💡 Click "🔍 Replace / Backfill" on any row to manually pick a song and persist it to cache!',
    th_src_track: 'Source Track',
    th_conf_status: 'Confidence / Status',
    th_matched_track: 'Target Match',
    th_manual_fix: 'Override',

    dedupe_header: 'Multi-Platform Playlist Deduplicator (YTM / NetEase / QQ / Kugou / Spotify / Navidrome; Scan-only on Apple Music)',
    lbl_dedupe_plat: 'Platform',
    lbl_dedupe_pl: 'Select Owned Playlist',
    lbl_dedupe_mode: 'Detection Mode',
    btn_scan_dup: '🔍 Scan Duplicates',

    export_header: 'Multi-Format Playlist Backup (Export CSV / M3U8 / JSON for Excel, Navidrome, Jellyfin & Portable Restore)',
    lbl_export_format: 'Export Format',
    opt_fmt_csv: '📊 CSV Spreadsheet (.csv · Excel & Exportify compatible)',
    opt_fmt_m3u8: '🎵 M3U8 Playlist (.m3u8 · #EXTM3U for Jellyfin / Navidrome / Players)',
    opt_fmt_json: '📦 Portable JSON (.json · Preserves ISRC, duration & IDs)',
    lbl_export_method1: 'Option 1: Export from Connected Platform (including ❤️ Liked / Starred)',
    btn_export_selected: '📥 Export Selected Playlist',
    lbl_export_method2: 'Option 2: Paste Public Share URL to Export Without Login (NetEase/QQ/Kugou/Qishui/Apple/YTM)',
    btn_export_url: '📥 Parse URL & Download Backup',

    sync_header: 'Scheduled Sync Guardian (One-Way Append, Safe Mirror with Circuit Breaker & Echo-Free Two-Way Merge)',
    lbl_sync_src: 'Source Platform & Playlist (Side A in 2-Way)',
    lbl_sync_tgt: 'Target Platform & Destination (Side B in 2-Way)',
    lbl_sync_interval_name: 'Interval & Rule Name',
    lbl_sync_mode: 'Sync Strategy Mode',
    opt_sync_append: '➕ One-Way Incremental Append (Add new tracks only · Safest)',
    opt_sync_mirror: '🪞 One-Way Mirror Sync (Propagate removals · Protected by Circuit Breaker)',
    opt_sync_twoway: '⇄ Two-Way Merge Sync (Echo-free A ⇄ B bidirectional additions)',
    lbl_mirror_guard: 'Mirror Safety Circuit Breaker (Empty-Snapshot Guard + Max Removal Ratio)',
    opt_ratio_20: '🛡️ Strict Guard: Abort if >20% tracks would be removed',
    opt_ratio_30: '✨ Recommended: Abort if >30% tracks would be removed',
    opt_ratio_50: '🌊 Relaxed: Abort if >50% tracks would be removed',
    btn_add_sync: '➕ Create Scheduled Sync Rule',

    notif_header: 'Push Notification Guardian (Webhook / Bark / Telegram · Alerts on Sync Completion or Expired Login)',
    lbl_notif_enable: 'Enable Push Notifications',
    lbl_notif_on_err: 'Alert on sync error / expired Cookie / mirror circuit-breaker trip',
    lbl_notif_on_ok: 'Send summary when sync completes with track changes',
    lbl_notif_webhook: 'Webhook URL (Feishu / DingTalk / WeCom / Discord / Slack / Generic JSON)',
    lbl_notif_bark: 'Bark Server URL or Device Key (iOS Push)',
    lbl_notif_tg_token: 'Telegram Bot Token (Optional)',
    lbl_notif_tg_chat: 'Telegram Chat ID (Optional)',
    btn_save_notif: '💾 Save Notification Config',
    btn_test_notif: '📨 Send Test Push',

    history_header: 'Local Migration History',
    btn_clear_history: 'Clear History',

    cache_modal_title: '⚡ Persistent Match Cache Inspector (Search / Inspect / Delete Single Entry)',
    cache_filter_all_plat: 'All Target Platforms',
    cache_search_placeholder: 'Search source title, artist, ISRC or matched song...',
    btn_clear_all_cache: '🗑️ Clear Entire Cache',
    cache_empty: 'No cached track mappings match your filter.',
  },
};

const PLATFORM_LABELS_I18N = {
  zh: {
    ytm: 'YouTube Music',
    spotify: 'Spotify',
    netease: '网易云音乐',
    qqmusic: 'QQ音乐',
    kugou: '酷狗音乐',
    applemusic: 'Apple Music',
    subsonic: 'Navidrome / Subsonic',
    qishui: '汽水音乐',
  },
  en: {
    ytm: 'YouTube Music',
    spotify: 'Spotify',
    netease: 'NetEase Music',
    qqmusic: 'QQ Music',
    kugou: 'Kugou Music',
    applemusic: 'Apple Music',
    subsonic: 'Navidrome / Subsonic',
    qishui: 'Qishui Music',
  },
};

let currentUiLang = (function () {
  try {
    const saved = localStorage.getItem('switch_music_lang');
    if (saved === 'en' || saved === 'zh') return saved;
  } catch (_) {}
  return 'zh';
})();

function getUiLang() {
  return currentUiLang === 'en' ? 'en' : 'zh';
}

function t(key, vars = {}) {
  const lang = getUiLang();
  const dict = UI_I18N[lang] || UI_I18N.zh;
  let str = dict[key] !== undefined ? dict[key] : (UI_I18N.zh[key] !== undefined ? UI_I18N.zh[key] : key);
  Object.keys(vars).forEach(k => {
    str = str.replace(new RegExp('\\{' + k + '\\}', 'g'), String(vars[k]));
  });
  return str;
}

function platLabel(pid) {
  const lang = getUiLang();
  const map = PLATFORM_LABELS_I18N[lang] || PLATFORM_LABELS_I18N.zh;
  return map[pid] || PLATFORM_LABELS_I18N.zh[pid] || pid;
}

function applyStaticI18n() {
  const lang = getUiLang();
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
  document.title = t('doc_title');

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const k = el.getAttribute('data-i18n');
    if (k) el.textContent = t(k);
  });

  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const k = el.getAttribute('data-i18n-placeholder');
    if (k) el.setAttribute('placeholder', t(k));
  });
}
