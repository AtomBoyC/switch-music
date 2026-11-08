# Switch Music 🎵

本地无限制歌单迁移与去重管理 Web 应用（**Spotify → YouTube Music**）。

所有认证凭据均仅保存在本地 `data/` 目录中（已加入 `.gitignore`，不会上传任何隐私数据），无第三方平台常见的 200~500 首曲目数量限制。

---

## ✨ 核心功能

1. **YouTube Music 极速连接**
   - 支持直接粘贴浏览器开发者工具中的 `Copy as cURL` 命令、原始 `Request Headers`、`cookies.txt` 或 Cookie JSON，自动提取并计算 `SAPISIDHASH` 认证签名。
2. **双模式加载 Spotify 歌单（支持私密歌单与 Liked Songs）**
   - **CSV 拖拽导入（免配置）**：兼容 [Exportify](https://exportify.net/) 导出的单个或多个 `.csv` 文件。
   - **Spotify OAuth 授权直连**：填入 Spotify Developer `Client ID` & `Client Secret` 后一键拉取全部私密歌单及「❤️ 我喜欢的音乐」。
3. **多维曲目匹配与实时批量导入**
   - 综合歌名、歌手、简繁体汉字归一、曲目时长接近度与 `Song` 类型权重进行打分匹配。
   - 支持 **新建歌单**、**追加到现有歌单** 或 **直接点亮至 YouTube Music「我喜欢的音乐」**。
   - 原生使用 `DEDUPE_OPTION_DROP_DUPLICATE` 批量写入并带单曲降级重试，避免单首重复导致整批丢失。
4. **按「重复组」自由选择的歌单去重工具**
   - **导入前源列表去重**：扫描 CSV / Spotify 待迁移列表中的重复组，自由选择保留哪一版。
   - **YouTube Music 现有歌单独立去重**：支持「标准（同 ID + 同名同歌手/简繁体）」「严格（仅同 ID）」「深度（同名 + 时长 ±3s）」三种扫描模式；按组展示所有版本、支持点击 `▶ 试听` 及 `🔄 改为只留这首` 一键切换保留项。

---

## 🚀 快速启动

### macOS 一键启动
双击运行项目根目录下的 `start.command`（首次运行会自动创建 `.venv` 并安装依赖，随后自动打开浏览器访问 `http://127.0.0.1:8765`）。

### 命令行手动启动
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动服务（开发模式可加 --reload）
uvicorn app:app --host 127.0.0.1 --port 8765 --reload
```
然后在浏览器打开：**http://127.0.0.1:8765**

---

## 🗂️ 项目结构

```text
Switch Music/
├── app.py               # FastAPI 后端：认证解析、曲目匹配引擎、批量导入与歌单去重 API
├── static/
│   └── index.html       # 单页 Web UI（原生 HTML/CSS/JS，零前端构建依赖）
├── requirements.txt     # Python 依赖清单 (fastapi, uvicorn, ytmusicapi, spotipy, ...)
├── start.command        # macOS 双击启动脚本
├── .gitignore           # 忽略 data/ 本地凭据与虚拟环境
└── data/                # 运行时自动生成（存放本地认证与任务记录，不入库）
```

---

## 🛠️ 后续开发方向 (TODO / Ideas)

- [ ] 匹配结果人工微调：对低置信度匹配或未匹配曲目支持在界面内手动搜索替换候选曲目后再写入
- [ ] 双向同步：支持 YouTube Music 导出 CSV 或反向同步回 Spotify
- [ ] 定时增量同步：定期拉取 Spotify `Liked Songs` 新增曲目增量同步至 YouTube Music
- [ ] 并发加速：使用异步或受控线程池优化超大型歌单（2000+ 首）的搜索耗时
