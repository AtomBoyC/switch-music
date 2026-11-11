from __future__ import annotations

import re
from typing import List, Optional, Set

_TRAD_SIMP_RAW = (
    "澤泽 樣样 東东 貓猫 後后 來来 倫伦 傑杰 孫孙 劉刘 趙赵 愛爱 裡里 獨独 視视 劇剧 專专 輯辑 "
    "雲云 煙烟 風风 戀恋 夢梦 淚泪 橋桥 傷伤 離离 開开 華华 陳陈 張张 學学 鄧邓 蘇苏 綠绿 樂乐 "
    "團团 隊队 國国 語语 粵粤 歲岁 時时 間间 記记 憶忆 誰谁 說说 話话 讓让 變变 過过 還还 沒没 "
    "對对 錯错 難难 聽听 見见 親亲 擁拥 藍蓝 紅红 黃黄 雙双 飛飞 鳥鸟 魚鱼 馬马 島岛 灣湾 臺台 "
    "鐵铁 號号 樓楼 門门 關关 閉闭 燈灯 聲声 響响 詞词 會会 場场 節节 點点 線线 網网 絡络 萬万 "
    "與与 絲丝 兩两 嚴严 喪丧 個个 豐丰 臨临 為为 麗丽 舉举 麼么 義义 烏乌 喬乔 習习 鄉乡 書书 "
    "買买 亂乱 乾干 爭争 虧亏 亞亚 產产 億亿 僅仅 從从 倉仓 們们 價价 眾众 優优 偉伟 傳传 偽伪 "
    "體体 餘余 俠侠 侶侣 偵侦 側侧 僑侨 儂侬 儘尽 兒儿 兌兑 黨党 蘭兰 養养 獸兽 內内 岡冈 冊册 "
    "寫写 軍军 農农 馮冯 沖冲 決决 況况 凍冻 淨净 淒凄 涼凉 減减 湊凑 幾几 鳳凤 憑凭 凱凯 擊击 "
    "別别 刪删 剮剐 劍剑 劑剂 創创 勸劝 辦办 務务 動动 勵励 勁劲 勞劳 勢势 勳勋 區区 醫医 協协 "
    "單单 賣卖 盧卢 衛卫 卻却 廠厂 廳厅 歷历 厲厉 壓压 厭厌 廁厕 廂厢 廈厦 廚厨 縣县 參参 發发 "
    "葉叶 嘆叹 嚇吓 呂吕 嗎吗 噸吨 啟启 吳吴 嘔呕 員员 嗚呜 詠咏 嚨咙 嚀咛 嘯啸 嘩哗 噓嘘 囑嘱 "
    "囉啰 圖图 圍围 園园 圓圆 聖圣 壞坏 塊块 堅坚 壇坛 壩坝 塢坞 墳坟 墜坠 壘垒 墾垦 壯壮 殼壳 "
    "壺壶 壽寿 處处 備备 復复 夠够 頭头 誇夸 夾夹 奪夺 奮奋 獎奖 奧奥 妝妆 婦妇 媽妈 嫵妩 嫗妪 "
    "姍姗 姊姐 婭娅 嬈娆 嬌娇 寧宁 寶宝 實实 寵宠 審审 憲宪 宮宫 寬宽 賓宾 寢寝 尋寻 導导 將将 "
    "爾尔 塵尘 嚐尝 堯尧 尷尴 屍尸 盡尽 層层 屜屉 屆届 屬属 屢屡 嶼屿 嶄崭 嶺岭 嶽岳 巔巅 鞏巩 "
    "幣币 帥帅 師师 帳帐 簾帘 幟帜 帶带 幀帧 幫帮 冪幂 廣广 莊庄 慶庆 廬庐 庫库 應应 廟庙 龐庞 "
    "廢废 異异 棄弃 弒弑 彌弥 彎弯 彈弹 強强 歸归 當当 錄录 彥彦 徹彻 徑径 徠徕 徵征 懺忏 憂忧 "
    "懷怀 態态 慫怂 悵怅 愴怆 憐怜 總总 懟怼 懇恳 惡恶 慟恸 愷恺 惻恻 惱恼 悅悦 懸悬 憫悯 驚惊 "
    "懼惧 慘惨 懲惩 憊惫 愜惬 慚惭 憚惮 慣惯 憤愤 懶懒 戲戏 戰战 戩戬 戶户 撲扑 執执 "
    "擴扩 掃扫 揚扬 擾扰 撫抚 拋抛 掄抡 搶抢 護护 報报 擔担 擬拟 攏拢 揀拣 攔拦 擰拧 撥拨 擇择 "
    "掛挂 摯挚 挾挟 撓挠 擋挡 掙挣 擠挤 揮挥 撈捞 損损 撿捡 換换 搗捣 據据 擄掳 擲掷 摻掺 攬揽 "
    "擱搁 摟搂 攪搅 攜携 攝摄 擺摆 搖摇 攤摊 撐撑 攆撵 敵敌 斂敛 數数 驅驱 驕骄 驗验 驛驿 驟骤 "
    "驢驴 髒脏 鬚须 髮发 鬧闹 鬱郁 魯鲁 鮮鲜 鯨鲸 鳴鸣 鷗鸥 鴉鸦 鴨鸭 鴦鸯 鴿鴿 鴻鸿 鵝鹅 鵬鹏 "
    "鵲鹊 鶯莺 鶴鹤 鸚鹦 鷹鹰 麥麦 齊齐 齒齿 齡龄 龍龙 龜龟 這这 進进 遠远 連连 遲迟 適适 選选 "
    "遜逊 遞递 週周 遊游 遙遥 遺遗 邊边 達达 遷迁 邁迈 運运 閃闪 問问 閒闲 聞闻 閱阅 闊阔 闌阑 "
    "隻只 雖虽 雜杂 雞鸡 電电 霧雾 靈灵 靜静 韓韩 韻韵 頂顶 順顺 須须 頌颂 預预 頑顽 頓顿 領领 "
    "頸颈 頻频 顆颗 題题 額额 顏颜 願愿 類类 顧顾 顯显 飄飘 飛飞 飯饭 飲饮 飽饱 飾饰 館馆 饒饶 "
    "馳驰 駐驻 駛驶 駝驼 罵骂 駭骇 駱骆 駿骏 騎骑 騙骗 騰腾 騷骚 鬆松 鬍胡 鬢鬓 鬥斗 魚鱼 鯊鲨 "
    "鯉鲤 鯽鲫 鳥鸟 鴦鸯 鴻鸿 鵑鹃 鹹咸 鹽盐 麵面 裏里 妳你 於于 並并 鐘钟 鍾钟 製制 勝胜 檯台 "
    "颱台 嚮向 迴回 睏困 複复 覆复 慾欲 瞭了 藉借 藝艺 蘋苹 蟲虫 術术 裝装 觀观 覺觉 訂订 計计 "
    "訊讯 討讨 訓训 託托 許许 訴诉 診诊 註注 證证 評评 詢询 試试 詩诗 該该 詳详 誠诚 誌志 認认 "
    "誕诞 誘诱 誤误 課课 調调 談谈 請请 諒谅 論论 諸诸 諾诺 謀谋 謂谓 謊谎 謎谜 謙谦 講讲 謝谢 "
    "謠谣 謹谨 識识 譜谱 譯译 議议 譽誉 讀读 讚赞 豔艳 艷艳 貝贝 貞贞 負负 財财 貢贡 貧贫 貨货 販贩 "
    "貪贪 貫贯 責责 貴贵 貶贬 貸贷 費费 貼贴 貿贸 賀贺 資资 賊贼 賜赐 賞赏 賠赔 賢贤 賤贱 賦赋 "
    "質质 賬账 賭赌 賴赖 賺赚 購购 賽赛 贈赠 贊赞 贏赢 贖赎 趕赶 跡迹 踐践 躍跃 軀躯 車车 軌轨 "
    "軟软 輕轻 載载 轎轿 輛辆 輝辉 輩辈 輪轮 輸输 轉转 轟轰 辭辞 辮辫 辯辩 峯峰 喆哲 羣群 麪面"
)

TRAD_TO_SIMP_MAP = str.maketrans(
    {tok[0]: tok[1] for tok in _TRAD_SIMP_RAW.split() if len(tok) == 2 and tok[0] != tok[1]}
)

_VERSION_PATTERNS = {
    "live": re.compile(r"(?:\blive\b|现场|演唱會|演唱会|concert|武道馆|红馆)", re.IGNORECASE),
    "cover": re.compile(r"(?:\bcover\b|翻唱|翻自)", re.IGNORECASE),
    "instrumental": re.compile(
        r"(?:\binstrumental\b|\bkaraoke\b|伴奏|纯音乐|off\s*vocal|backing\s*track|卡拉\s*ok|消音)",
        re.IGNORECASE,
    ),
    "remix": re.compile(r"(?:\bremix\b|\bbootleg\b|混音)", re.IGNORECASE),
    "dj": re.compile(r"(?:\bdj\b|dj版|dj默涵|dj沈念|慢摇)", re.IGNORECASE),
    "acoustic": re.compile(r"(?:\bacoustic\b|\bunplugged\b|不插电|木吉他)", re.IGNORECASE),
    "sped_slowed": re.compile(
        r"(?:sped\s*up|slowed|reverb|倍速|0\.8x|0\.9x|1\.2x|1\.3x|nightcore)",
        re.IGNORECASE,
    ),
}


def to_simplified(s: str) -> str:
    return (s or "").translate(TRAD_TO_SIMP_MAP)


def extract_version_tags(s: str) -> Set[str]:
    norm = to_simplified(s or "")
    tags: Set[str] = set()
    for tag_name, pattern in _VERSION_PATTERNS.items():
        if pattern.search(norm):
            tags.add(tag_name)
    return tags


def strip_noise_for_query(title: str) -> str:
    """
    Produces a clean song title suitable for fallback search queries,
    removing (feat. ...), (Taylor's Version), [Official Video], - 2021 Remaster, 《电视剧...》, etc.
    """
    s = (title or "").strip()
    s = re.sub(
        r"\((?:feat|ft|with|prod|from|翻自|原唱|电影|电视剧|动画|游戏)[^)]*\)",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"（(?:feat|ft|with|prod|from|翻自|原唱|电影|电视剧|动画|游戏)[^）]*）",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\([^)]*(?:version|remaster(?:ed)?|edition|mix|edit|deluxe|bonus|ost|soundtrack|vault|ver\.?)[^)]*\)",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"（[^）]*(?:重制版|重置版|修复版|纪念版|豪华版|特别版|主题曲|片尾曲|插曲)[^）]*）",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\[[^\]]*\]|【[^】]*】|《[^》]*》", "", s)
    s = re.sub(
        r"\s+-\s+.*?(?:remaster(?:ed)?|version|mix|edit|live|mono|stereo|deluxe|bonus|ost|soundtrack).*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+(?:feat\.?|ft\.?)\s+.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -·")
    return s or (title or "").strip()


def clean_str(s: str) -> str:
    s = to_simplified(s or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|（.*?）|【.*?】|《.*?》", "", s)
    s = re.sub(
        r"\s+-\s+.*?(?:remaster(?:ed)?|version|mix|edit|live|original|ost|soundtrack).*",
        "",
        s,
    )
    s = re.sub(r"\b(?:feat\.?|ft\.?)\b.*", "", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", " ", s)
    return s.strip()


def split_artists(artist_str: str) -> List[str]:
    if not artist_str:
        return []
    raw = to_simplified(artist_str)
    parts = re.split(r"[,;/、&]|\s+(?:feat\.?|ft\.?|with|x)\s+", raw, flags=re.IGNORECASE)
    cleaned: List[str] = []
    for p in parts:
        c = clean_str(p)
        if c and c not in cleaned:
            cleaned.append(c)
    return cleaned


def parse_duration_seconds(duration_str: Optional[str]) -> int:
    if not duration_str:
        return 0
    s = str(duration_str).strip()
    if s.isdigit():
        return int(s)
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return 0


def format_duration_seconds(sec: int) -> str:
    if not sec or sec <= 0:
        return ""
    m, s = divmod(int(sec), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_duration_ms(ms: Optional[int]) -> str:
    if not ms or ms <= 0:
        return ""
    return format_duration_seconds(int(ms) // 1000)
