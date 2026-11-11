# Switch Music 2.0 🎵

本地无限制**全平台歌单互转、预匹配人工微调、去重清理与定时增量同步**工作台（**Spotify ⇄ YouTube Music ⇄ 网易云音乐 ⇄ QQ音乐**）。

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

### 运行单元测试
```bash
./.venv/bin/python -m unittest discover -s tests -v
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
