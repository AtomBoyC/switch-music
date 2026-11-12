# Switch Music 2.0 🎵

本地无限制**全平台歌单互转、预匹配人工微调、去重清理与定时增量同步**工作台（**Spotify ⇄ YouTube Music ⇄ 网易云音乐 ⇄ QQ音乐 ⇄ 酷狗音乐 ⇄ Apple Music**）。

所有账号认证凭据、匹配缓存与历史记录均仅保存在本地 `data/` 目录中（已加入 `.gitignore`，绝不上传任何第三方服务器），彻底告别在线平台常见的 200~500 首曲目上限与隐私泄露风险。

---

## ✨ v2.0 核心特性

1. **四大主流音乐平台任意互转（Any-to-Any）**
   - **支持平台**：**YouTube Music**、**Spotify**、**网易云音乐**、**QQ音乐**，以及通用 **CSV / TSV / JSON / 纯文本歌单**。
   - **免登录链接直读**：粘贴任意 **网易云音乐**（自动突破网页端 10~20 首及 1000 首曲目截断，读取全量 `trackIds`）、**QQ音乐**（自动解析 `c6.y.qq.com` 短链并分页拉取大歌单）或 **YouTube Music** 公开歌单分享链接即可一键解析。
   - **账号完整读写连接**：
     - **YouTube Music / 网易云音乐 / QQ音乐**：均支持浏览器 `Copy as cURL`、原始 `Request Headers`、`cookies.txt` 或 Cookie JSON 一键连接。
     - **Spotify**：支持 OAuth 2.0 双向读写授权（支持读取私密歌单 / `Liked Songs` 及反向创建歌单 / 写入曲目）。
2. **高精度多维曲目匹配 + 预匹配人工微调工作台**
   - **智能防踩坑打分模型**：综合 ISRC 精准编码、简繁体汉字归一、多歌手合作交叉比对、专辑吻合度与曲目时长接近度打分；**自动识别并对非预期的「伴奏 / Karaoke / 翻唱 / DJ版 / 倍速版 / Live现场」降权**，设置最低置信度阈值拦截无关错配。
   - **先预匹配审核，确认后再写入**：支持在正式写入前并发预览所有匹配结果，按「高置信度 / ⚠️ 低置信度待核对 / ❌ 未匹配」筛选，点击 **「🔍 手动搜歌替换 / 补录」** 即可在弹窗内实时搜索目标平台曲库并试听指定。
3. **受控多线程并发加速 + 本地持久化匹配缓存**
   - 内置 `ThreadPoolExecutor` 并发搜索与滑动窗口保序提交机制（1~6 线程可调），提速 3~5 倍的同时 **100% 保持原歌单曲目顺序**。
   - 本地持久化 `data/match_cache.json`，重试或跨歌单重复曲目 `0ms` 秒级命中；向现有歌单追加时自动预读已有曲目防止重复请求。
4. **全平台歌单重复组清理工具**
   - 支持扫描并清理 **YouTube Music**、**网易云音乐**、**QQ音乐**、**Spotify** 自建歌单及待迁移源列表中的重复曲目。
   - 提供「标准（同 ID + 同名同歌手/简繁体）」「严格（仅同 ID）」「深度（同名 + 时长 ±3s）」三种模式，按「重复组」自由点击 `▶ 试听` 与 `🔄 改为只留这首`。
5. **歌单 CSV 备份导出、历史记录与定时增量同步**
   - 一键将任意平台歌单（含「❤️ 我喜欢的音乐」）或未匹配曲目导出为 Excel 友好的 UTF-8 BOM `.csv` 文件。
   - 支持配置后台**定时增量同步规则**（例如每 2 小时自动检测 Spotify / 网易云 `我喜欢的音乐` 新增曲目并增量同步至 YouTube Music / QQ音乐）。

### 🛡️ v2.1 稳定性与安全加固

- **单曲出错不再卡死任务**：某首歌搜索抛异常时会记为「⚠️ 搜索出错」并继续处理后续曲目（此前会导致后面所有曲目都不写入）；全部查询都失败时明确标记为出错，而不是误报为「未匹配」。
- **有序单线程写入 + 失败可见**：所有写入按歌单顺序串行执行，失败自动重试 3 次；仍失败的曲目标记为「写入失败」并加入重试列表，不再静默丢失。
- **网络限流自动退避**：网易云 / QQ音乐请求在连接错误或 HTTP 429/502/503/504 时自动指数退避重试，网易云「操作频繁」响应也会自动重试。
- **崩溃 / 重启后可续传**：迁移进度每 100 首自动存档；服务意外关闭后再次启动会把任务标记为「已中断」，一键「重试未匹配/未完成曲目」即可继续迁移剩余部分。手动停止的任务同样保留未处理曲目。
- **增量同步更可靠**：搜索失败的新歌不会被标记为已同步，下次自动重试。
- **本地服务安全加固**：仅接受 `127.0.0.1` / `localhost` 的 Host（防 DNS 重绑定攻击），拒绝跨站来源的写操作请求（防 CSRF），`data/` 目录及凭据文件权限收紧为仅本人可读写（`0700` / `0600`）。
- 新增健康检查接口 `GET /api/health`。

### 🆕 新增平台：酷狗音乐 & Apple Music

| 能力 | 酷狗音乐 | Apple Music |
|---|---|---|
| 免登录链接直读 | ✅ `kugou.com/songlist/gcid_...`、App 分享短链、`collection_3_..._0` | ✅ 公开歌单 / 专辑链接、`apple.co` 短链 |
| 作为目标平台搜索匹配 | ✅ | ✅（支持 ISRC 精准匹配） |
| 账号连接 | 酷狗 App **扫码登录**（或粘贴客户端 token） | 粘贴 music.apple.com 的 `Copy as cURL`（需 `media-user-token`），无需开发者账号 |
| 读取账号歌单 | ✅ 含「❤️ 我喜欢」 | ✅ 资料库歌单 + 资料库全部歌曲 |
| 新建 / 追加 / 我喜欢 | ✅ / ✅ / ✅ | ✅ / ✅ / ✅（加入资料库并标记喜爱） |
| 歌单去重 | ✅ 扫描 + 删除 | ⚠️ 仅扫描（Apple 接口不支持从歌单删除单曲） |

> 两者均基于网页版 / 客户端的非官方接口，平台改版后可能需要更新适配。

### 🐛 修复

- 追加到现有歌单 / 我喜欢时，若读取目标歌单已有曲目失败（如登录态过期），任务此前会永久卡在「运行中」，且各平台会静默跳过防重导致可能重复写入。现在会明确标记为失败（未写入任何曲目）并保留全部曲目供重试。
- YouTube Music / Spotify「我喜欢」防重读取不再限制为前 2000 首。

---

## 🚀 快速启动

### macOS 一键启动（零前端构建依赖）
双击运行项目根目录下的 `start.command`（首次运行会自动创建 `.venv` 并安装纯 Python 依赖，等待服务端口就绪后自动在浏览器打开 `http://127.0.0.1:8765`）。

### 命令行手动启动
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动服务
python app.py
# 或开发模式热重载：
uvicorn app:app --host 127.0.0.1 --port 8765 --reload
```
浏览器访问：**http://127.0.0.1:8765**

### 🐳 Docker 部署

```bash
# 方式一：直接拉取镜像（支持 amd64 / arm64：Intel、Apple Silicon、树莓派、群晖等 NAS）
docker run -d --name switch-music \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD/data:/data" \
  --restart unless-stopped \
  ciezsup/switch-music:latest

# 方式二：docker compose（编辑 docker-compose.yml 中的可选环境变量后）
docker compose up -d

# 方式三：从源码构建
docker build -t switch-music .
```

所有凭据、匹配缓存、历史与同步规则都保存在挂载的 `/data` 卷中，升级镜像不会丢失。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SWITCH_MUSIC_PASSWORD` | 空 | 访问密码（浏览器弹窗登录，用户名任意）。**只要端口对其他设备开放就必须设置**，因为服务里保存着你的音乐账号凭据 |
| `SWITCH_MUSIC_ALLOWED_HOSTS` | 空 | 允许访问的局域网 IP / 域名，逗号分隔，如 `192.168.1.10,music.example.com`；`*` 表示任意（仅在设置密码时使用） |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8765/api/spotify/callback` | Spotify 只允许 `127.0.0.1` 使用 http 回调；部署在服务器上需配置 https 反向代理并填写对应地址 |
| `PORT` | `8765` | 容器内监听端口 |
| `PUID` / `PGID` | `10001` | 运行用户 / 组（NAS 上可设为你的用户 ID） |
| `TZ` | `Asia/Shanghai` | 时区（影响定时同步与历史记录时间） |

> 💡 NAS 上没有 https 时，可用 SSH 隧道 `ssh -L 8765:127.0.0.1:8765 你的NAS` 后在本机打开 `http://127.0.0.1:8765` 完成一次 Spotify 授权，令牌会保存在 `/data` 并自动续期。

镜像由 GitHub Actions（`.github/workflows/docker.yml`）自动测试、构建并推送到 Docker Hub：推送到 `main` 发布 `latest`，打 `v*` 标签发布对应版本号。

### 运行单元测试
```bash
./.venv/bin/python -m unittest discover -s tests -t . -v
```

---

## 🗂️ 模块化项目结构

```text
switch-music/
├── app.py                        # FastAPI 应用入口与统一 REST API 路由
├── backend/
│   ├── config.py                 # 路径配置、原子 JSON 持久化与通用 cURL/Cookie 解析器
│   ├── models.py                 # Pydantic 数据模型定义
│   ├── text_utils.py             # 简繁转换字典、文本清洗与版本特征（伴奏/Live/翻唱）识别
│   ├── matcher.py                # 多维匹配打分引擎、多轮兜底查询与持久化缓存
│   ├── csv_io.py                 # 多格式 CSV / TSV / JSON / 纯文本歌单导入与导出
│   ├── deduplicator.py           # 源列表与全平台歌单重复组分析引擎
│   ├── migration_engine.py       # 多线程保序匹配、预匹配审核、手动补录与历史记录管理
│   ├── sync_scheduler.py         # 后台定时增量同步守护线程
│   └── providers/
│       ├── base.py               # 统一音乐平台抽象接口 (PlatformProvider)
│       ├── ytm.py                # YouTube Music 适配器 (SAPISIDHASH 签名、读写与去重)
│       ├── spotify.py            # Spotify 适配器 (OAuth 双向读写、ISRC 搜索与定点去重)
│       ├── netease.py            # 网易云音乐适配器 (纯 Python weapi AES+RSA、全量歌单读写)
│       └── qqmusic.py            # QQ音乐适配器 (musicu.fcg 网关、短链解析、g_tk 与读写去重)
├── static/
│   ├── index.html                # 模块化单页应用壳（零 Node.js 构建依赖）
│   ├── css/styles.css            # 响应式深色主题样式
│   └── js/app.js                 # 前端交互控制器
├── tests/
│   └── test_core.py              # 核心算法、加密协议与 API 集成测试
├── requirements.txt              # 纯 Python 依赖清单
└── start.command                 # macOS 双击启动脚本（含端口就绪检测）
```
