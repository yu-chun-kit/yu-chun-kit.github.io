"""Fine-grained, user-editable tag taxonomy for the conversation studio.

The tags are produced by a System One model (Jev / OpenJev): every dimension is
one *typed question* about the conversation, so each tag arrives with a
probability instead of being parsed out of generated text.

Design rules
------------
* Option ids are ASCII so the model reads unambiguous keys; labels and
  descriptions are bilingual because the underlying models are stronger in
  English than in Chinese, while the blog is written in Chinese.
* Three levels of specificity (domain → subdomain → concept) plus a genre, a
  depth score, the language and a few flags.  Reading only the tags should tell
  you what the conversation is about without opening it.
* A conversation's own ``title`` is never used as a tag; the taxonomy is a
  controlled vocabulary, which keeps the blog's tag pages meaningful.
* The fallback classifier (no API key) lives in :mod:`chatblog.classify` and
  uses the ``keywords`` collected here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    description: str = ""
    parent: str = ""
    keywords: tuple[str, ...] = ()

    def prompt_text(self) -> str:
        return f"{self.label} — {self.description}" if self.description else self.label


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    kind: str  # "choice" | "noul" | "score"
    question: str
    options: tuple[Option, ...] = ()
    levels: tuple[str, ...] = ()

    def option(self, value: str) -> Option | None:
        for option in self.options:
            if option.id == value:
                return option
        return None


def _op(id: str, label: str, description: str = "", parent: str = "", kw: Iterable[str] = ()) -> Option:
    return Option(id=id, label=label, description=description, parent=parent, keywords=tuple(kw))


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

DOMAINS: tuple[Option, ...] = (
    _op("philosophy", "哲學思想", "抽象思想、倫理、宗教、主義與觀念史；討論概念本身，不是時事、實作或數字 (philosophy, ethics, religion, intellectual history)",
        kw=("哲學", "哲学", "倫理", "伦理", "存在主義", "存在主义", "馬克思", "马克思", "尼采",
            "黑格爾", "黑格尔", "現象學", "现象学", "虛無", "虚无", "思想", "主義", "主义",
            "宗教", "神學", "神学", "意識形態", "意识形态", "康德", "叔本華", "叔本华")),
    _op("politics", "政治社會", "政治制度、國際關係、地緣、歷史事件、法律、社會議題、媒體輿論、民族主義；重點在群體與權力 (politics, IR, law, history, public opinion)",
        kw=("政治", "國際關係", "国际关系", "地緣", "地缘", "社會", "社会", "法律", "歷史",
            "历史", "政府", "選舉", "选举", "抗議", "抗议", "國家", "国家", "輿論", "舆论",
            "納粹", "纳粹", "左翼", "右翼", "殖民主義", "殖民主义", "民主", "極權", "极权")),
    _op("economics", "經濟商業", "經濟金融、投資、創業、商業模式、行銷、職涯求職、產業與公司分析 (economics, finance, business, marketing, careers)",
        kw=("經濟", "经济", "金融", "股票", "投資", "投资", "創業", "创业", "商業", "商业",
            "行銷", "营销", "職涯", "职涯", "求職", "求职", "產業", "产业", "市場", "市场",
            "詐騙", "诈骗", "加盟", "理財", "理财", "加密貨幣", "加密货币", "薪水", "收入")),
    _op("technology", "技術程式", "寫程式、系統、網絡、資料庫、部署、AI 工程、工具與硬體；通常有指令、程式碼或設定 (programming, systems, networking, databases)",
        kw=("程式", "程序", "代碼", "代码", "編程", "编程", "開發", "开发", "伺服器", "服务器",
            "資料庫", "数据库", "網絡", "网络", "系統", "系统", "軟件", "软件", "硬件", "部署",
            "docker", "linux", "windows", "api", "llm", "ai", "模型", "代理", "腳本", "脚本",
            "terminal", "終端", "终端", "github", "開源", "开源", "nas", "hexo", "unity")),
    _op("science", "科學研究", "自然科學、數學、統計、認知科學、學術論文、實驗數據、事實查核與科普求證 (natural science, math, statistics, fact-checking)",
        kw=("科學", "科学", "數學", "数学", "物理", "化學", "化学", "生物", "統計", "统计",
            "實驗", "实验", "論文", "论文", "認知", "认知", "心理學", "心理学", "蒙提霍爾",
            "蒙提霍尔", "機率", "概率", "研究")),
    _op("writing", "創作寫作", "小說、劇本、文案、翻譯、世界觀與詩；重點在寫出來的作品 (fiction, screenplays, copywriting, translation)",
        kw=("小說", "小说", "劇本", "剧本", "文案", "寫作", "写作", "翻譯", "翻译", "詩", "诗",
            "故事", "世界觀", "世界观", "角色", "散文", "書評", "书评", "影評", "影评")),
    _op("games", "遊戲動漫", "電子遊戲、VRChat、Unity 專案、動漫、桌遊、模組與攻略 (video games, VRChat, Unity, anime, tabletop)",
        kw=("遊戲", "游戏", "攻略", "vrchat", "blender", "動漫", "动漫", "桌遊", "桌游",
            "模組", "模组", "玩家", "steam", "無人深空", "无人深空", "化身", "avatar")),
    _op("life", "生活實務", "健康醫療、飲食、旅遊、家居、個人理財、購物與寵物等日常實務 (health, food, travel, home, personal finance)",
        kw=("健康", "醫療", "医疗", "飲食", "饮食", "旅遊", "旅游", "家居", "裝修", "装修",
            "購物", "购物", "寵物", "宠物", "減肥", "减肥", "睡眠", "失眠", "保險", "保险",
            "租房", "搬家", "煮", "食譜", "食谱")),
    _op("learning", "學習教育", "語言學習、考試準備、課程設計、學習方法與筆記 (language learning, exams, courses, study methods)",
        kw=("學習", "学习", "考試", "考试", "課程", "课程", "教學", "教学", "語言學習",
            "语言学习", "記憶", "记忆", "筆記", "笔记", "學校", "学校", "留學", "留学",
            "補習", "补习", "日文", "英文")),
    _op("relationships", "人際情感", "家庭、戀愛、溝通、心理狀態與情緒 (family, romance, communication, mental state)",
        kw=("感情", "戀愛", "恋爱", "家庭", "婚姻", "朋友", "溝通", "沟通", "情緒", "情绪",
            "焦慮", "焦虑", "關係", "关系", "父母", "子女", "親密", "亲密", "孤獨", "孤独")),
    _op("other", "其他", "以上皆非 (everything else)", kw=()),
)

#: English surface forms appended to the domain keywords above; the chats mix
#: languages and the rules fallback should not be blind to English text.
_DOMAIN_EN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "philosophy": ("philosophy", "ethics", "religion", "marxism", "nietzsche", "existential",
                   "metaphysics", "ideology", "hegel", "nihilism"),
    "politics": ("politics", "political", "government", "election", "law", "history",
                 "geopolitics", "society", "nazi", "democracy", "regime"),
    "economics": ("economy", "economics", "finance", "investment", "business", "marketing",
                  "startup", "career", "market", "stock", "crypto", "franchise"),
    "technology": ("programming", "code", "software", "hardware", "server", "database",
                   "network", "docker", "linux", "windows", "api", "llm", "deploy", "git",
                   "nas", "hexo", "unity", "browser", "script", "terminal"),
    "science": ("science", "math", "physics", "biology", "statistics", "research",
                "psychology", "experiment", "probability", "cognition"),
    "writing": ("fiction", "novel", "screenplay", "translation", "writing", "story",
                "poem", "character design", "worldbuilding"),
    "games": ("game", "vrchat", "anime", "board game", "modding", "steam", "gameplay"),
    "life": ("health", "diet", "travel", "home", "shopping", "pet", "sleep", "insurance",
             "workout", "recipe"),
    "learning": ("learning", "study", "exam", "course", "teaching", "language learning",
                 "memory", "university", "study abroad"),
    "relationships": ("relationship", "family", "marriage", "emotion", "anxiety",
                      "communication", "dating", "loneliness"),
}

DOMAINS = tuple(
    _op(
        option.id,
        option.label,
        option.description,
        option.parent,
        option.keywords + _DOMAIN_EN_KEYWORDS.get(option.id, ()),
    )
    for option in DOMAINS
)

SUBDOMAINS: tuple[Option, ...] = (
    _op("existentialism", "存在主義", "existentialism, Sartre, Camus, Heidegger", "philosophy"),
    _op("marxism", "馬克思主義", "Marx, historical materialism, class analysis", "philosophy"),
    _op("accelerationism", "加速主義", "accelerationism, Nick Land, CCRU, cyberpunk politics", "philosophy"),
    _op("nietzsche", "尼采", "Nietzsche, nihilism, genealogy of morals", "philosophy"),
    _op("byung_chul_han", "韓炳哲", "Byung-Chul Han, burnout society, transparency", "philosophy"),
    _op("mark_fisher", "馬克·費舍", "Mark Fisher, capitalist realism, hauntology", "philosophy"),
    _op("ethics", "倫理學", "normative ethics, applied ethics", "philosophy"),
    _op("epistemology", "認識論", "knowledge, truth, justification", "philosophy"),
    _op("religion", "宗教神學", "religion, theology, comparative mythology", "philosophy"),
    _op("psychoanalysis", "心理分析", "Freud, Lacan, psychoanalytic theory", "philosophy"),
    _op("phenomenology", "現象學", "Husserl, Merleau-Ponty, lived experience", "philosophy"),
    _op("chinese_philosophy", "中國哲學", "Confucianism, Daoism, Chinese thought", "philosophy"),

    _op("china_politics", "中國政治", "PRC politics, governance, policy", "politics"),
    _op("international_relations", "國際關係", "IR theory, diplomacy, alliances", "politics"),
    _op("geopolitics", "地緣政治", "geopolitics, security, regional conflict", "politics"),
    _op("social_issues", "社會議題", "social problems, inequality, urban life", "politics"),
    _op("law", "法律法規", "law, regulation, legal reasoning", "politics"),
    _op("history", "歷史研究", "history, historiography, historical events", "politics"),
    _op("media", "媒體輿論", "media, public opinion, information war", "politics"),
    _op("activism", "社會運動", "protest, organising, civil resistance", "politics"),
    _op("political_theory", "政治理論", "political philosophy, ideology, institutions", "politics"),

    _op("macro_econ", "總體經濟", "macroeconomics, trade, monetary policy", "economics"),
    _op("investing", "金融投資", "stocks, funds, portfolio, valuation", "economics"),
    _op("startup", "創業", "startups, founding, product-market fit", "economics"),
    _op("business_model", "商業模式", "business models, unit economics, operations", "economics"),
    _op("marketing", "行銷", "marketing, growth, branding", "economics"),
    _op("career", "職涯求職", "career, job search, workplace", "economics"),
    _op("industry", "產業分析", "industry structure, supply chain, market analysis", "economics"),

    _op("frontend", "前端開發", "HTML/CSS/JS, React, browser UI", "technology"),
    _op("backend", "後端開發", "servers, APIs, Go/Python/Node services", "technology"),
    _op("python", "Python", "Python language, packaging, tooling", "technology"),
    _op("javascript", "JavaScript/TypeScript", "JS/TS language, npm ecosystem", "technology"),
    _op("database", "資料庫", "SQL, SQLite, Postgres, data modelling", "technology"),
    _op("devops", "DevOps/部署", "CI/CD, containers, deployment, infra", "technology"),
    _op("networking", "網絡與代理", "networking, proxy, VPN, DNS, tunnels", "technology"),
    _op("ai_llm", "AI/LLM", "LLM prompting, agents, model behaviour", "technology"),
    _op("tooling", "工具鏈", "editors, CLI tools, automation, userscripts", "technology"),
    _op("sysadmin", "系統管理", "Linux/Windows administration, NAS, storage", "technology"),
    _op("data_analysis", "資料分析", "data wrangling, visualisation, notebooks", "technology"),
    _op("security", "資訊安全", "security, privacy, threat models", "technology"),
    _op("hardware", "硬體", "hardware, devices, peripherals, builds", "technology"),
    _op("web_scraping", "網頁抓取", "scraping, browser automation, Playwright", "technology"),
    _op("game_dev", "遊戲開發", "game engines, shaders, level design", "technology"),

    _op("math", "數學", "algebra, analysis, probability", "science"),
    _op("physics", "物理", "physics, cosmology, mechanics", "science"),
    _op("biology", "生物", "biology, evolution, neuroscience", "science"),
    _op("cognitive_science", "認知科學", "cognition, perception, consciousness", "science"),
    _op("statistics", "統計方法", "statistics, inference, experiment design", "science"),
    _op("academia", "論文寫作", "papers, citations, research workflow", "science"),
    _op("fact_check", "事實查核", "fact-checking, 闢謠, 科普, 拆解偽科學與軟廣中的數字/引文", "science"),

    _op("fiction", "小說創作", "novel/short-story drafting and critique", "writing"),
    _op("screenplay", "劇本", "screenwriting, dialogue, structure", "writing"),
    _op("copywriting", "文案", "copywriting, naming, marketing text", "writing"),
    _op("translation", "翻譯", "translation, localisation, style", "writing"),
    _op("worldbuilding", "世界觀設定", "worldbuilding, lore, setting design", "writing"),
    _op("poetry", "詩歌", "poetry, lyrics, verse", "writing"),

    _op("vrchat", "VRChat", "VRChat worlds, avatars, Udon", "games"),
    _op("unity", "Unity", "Unity engine, prefabs, VRChat SDK", "games"),
    _op("game_design", "遊戲設計", "game design, balance, mechanics", "games"),
    _op("walkthrough", "攻略", "walkthroughs, builds, strategies", "games"),
    _op("anime", "動漫", "anime, manga, characters", "games"),
    _op("game_culture", "遊戲雜談", "遊戲社群、迷因、賽事、周邊文化", "games",
        kw=("迷因", "梗", "表情包", "電競", "賽事", "社群", "玩家", "手遊", "代理")),
    _op("boardgame", "桌遊", "board games, rules, strategy", "games"),
    _op("modding", "模組", "mods, plugins, game customisation", "games"),

    _op("health", "健康醫療", "health, symptoms, fitness, medicine", "life"),
    _op("food", "飲食", "cooking, recipes, restaurants", "life"),
    _op("travel", "旅遊", "travel planning, destinations, itineraries", "life"),
    _op("home", "家居", "home, renovation, appliances, organisation", "life"),
    _op("personal_finance", "個人理財", "budgeting, saving, insurance", "life"),
    _op("shopping", "購物", "product research, buying advice", "life"),
    _op("pets", "寵物", "pets, care, training", "life"),

    _op("language_learning", "語言學習", "language acquisition, vocabulary, grammar", "learning"),
    _op("exam", "考試準備", "exams, test prep, study plans", "learning"),
    _op("curriculum", "課程設計", "course design, teaching material", "learning"),
    _op("study_methods", "學習方法", "learning techniques, memory, notes", "learning"),

    _op("family", "家庭", "family dynamics, parenting, relatives", "relationships"),
    _op("romance", "戀愛", "romance, dating, relationships", "relationships"),
    _op("communication", "溝通", "communication, conflict, persuasion", "relationships"),
    _op("mental_state", "心理狀態", "mood, anxiety, self-reflection", "relationships"),

    _op("chitchat", "閒聊", "small talk, casual chat", "other"),
    _op("misc", "雜項", "uncategorised", "other"),
)

CONCEPTS: tuple[Option, ...] = (
    _op("accelerationism", "加速主義", "accelerationism, Nick Land, CCRU", "philosophy",
        ("加速主義", "加速主义", "尼克蘭德", "尼克兰德", "nick land", "ccru")),
    _op("nihilism", "虛無主義", "nihilism and its critics", "philosophy",
        ("虛無", "虚无", "nihilism")),
    _op("capitalist_realism", "資本現實主義", "Mark Fisher's capitalist realism", "philosophy",
        ("資本現實", "资本现实", "capitalist realism", "費舍", "费舍")),
    _op("family_deconstruction", "家庭解構", "critique/deconstruction of the family", "relationships",
        ("家庭解構", "家庭解构", "家庭結構", "家庭结构")),
    _op("leftism", "左翼思潮", "left-wing thought and its tensions", "politics",
        ("左翼", "左派", "社會主義", "社会主义")),
    _op("monty_hall", "蒙提霍爾問題", "the Monty Hall probability puzzle", "science",
        ("蒙提霍爾", "蒙提霍尔", "monty hall")),
    _op("gansfeld", "甘茲菲爾德實驗", "Ganzfeld / sensory deprivation hallucination", "science",
        ("甘茲菲爾德", "甘兹菲尔德", "ganzfeld")),
    # parent="" keeps these available whatever domain wins (memes show up in
    # game, anime and news chats alike).
    _op("internet_meme", "網路迷因", "memes, 梗, 表情包, 病毒式傳播", "",
        kw=("迷因", "meme", "梗", "表情包", "惡搞", "鬼畜", "玩梗")),
    _op("esports", "電競賽事", "esports, 賽事統計, 戰隊與選手", "",
        kw=("電競", "电竞", "賽事", "赛事", "戰隊", "战队", "世界賽", "世界赛", "LPL", "LCK")),
    _op("pseudo_science_marketing", "軟廣帶貨", "科普包裝的帶貨文、偽科學廣告、智商稅產品", "science",
        kw=("軟廣", "软广", "帶貨", "带货", "智商稅", "智商税", "偽科學", "伪科学", "精油", "廣告文", "广告文")),
    _op("nationalism", "民族主義", "nationalism, 民族情緒, 中日/中美輿論", "politics",
        kw=("民族主義", "民族主义", "民族情緒", "辱華", "辱华", "仇日", "仇中")),
    _op("short_drama_scam", "短劇黑灰產", "short-drama grey/black industry", "politics",
        ("短劇", "短剧", "黑灰產", "黑灰产", "黃果", "黄果")),
    _op("franchise_scam", "連鎖加盟詐騙", "franchise/加盟 fraud patterns", "economics",
        ("加盟", "連鎖", "连锁", "詐騙", "诈骗")),
    _op("anti_fraud", "反詐騙", "scam detection and prevention", "politics",
        ("反詐", "反诈", "詐騙", "诈骗", "騙局", "骗局")),
    _op("hexo", "Hexo", "Hexo static blog and its themes", "technology",
        ("hexo", "landscape", "github pages")),
    _op("openwebui", "OpenWebUI", "OpenWebUI deployment and API", "technology",
        ("openwebui", "open-webui", "open webui")),
    _op("deepseek_harness", "DeepSeek Harness", "DSH / DeepSeek Harness agent", "technology",
        ("dsh", "deepseek harness", "碟仙哈拉斯", "harness")),
    _op("jev", "Jev", "TypeSafe Jev / System One decisions", "technology",
        ("jev", "typesafe", "system one", "systemone")),
    _op("openjev", "OpenJev", "open-source Jev-compatible decision models", "technology",
        ("openjev", "codiv", "wev")),
    _op("playwright", "Playwright", "browser automation with Playwright", "technology",
        ("playwright", "playwrite", "瀏覽器自動化", "浏览器自动化")),
    _op("tunnlto", "TunnlTo", "TunnlTo split tunnelling on Windows", "technology",
        ("tunnlto", "split tunnel", "分流")),
    _op("synology_nas", "Synology NAS", "Synology NAS, DSM, containers", "technology",
        ("synology", "群暉", "群晖", "nas", "dsm")),
    _op("rime", "小狼毫/Rime", "Rime / Weasel input method", "technology",
        ("rime", "weasel", "小狼毫", "倉頡", "仓颉", "輸入法", "输入法")),
    _op("blender", "Blender", "Blender modelling and rendering", "technology",
        ("blender", "建模", "渲染")),
    _op("vrchat_avatar", "VRChat 化身", "VRChat avatar creation and wardrobe", "games",
        ("vrchat", "avatar", "化身", "wardrobe", "穿衣")),
    _op("unity_project", "Unity 專案", "Unity project structure and SDK", "games",
        ("unity", "prefab", "udon", "sdk")),
    _op("docker_container", "Docker", "containers, images, compose", "technology",
        ("docker", "container", "compose", "容器")),
    _op("local_llm", "本地模型", "local LLM inference, Ollama, llama.cpp", "technology",
        ("ollama", "llama.cpp", "本地模型", "gguf", "lm studio")),
    _op("llm_prompting", "提示詞工程", "prompt engineering and evaluation", "technology",
        ("prompt", "提示詞", "提示词", "prompting")),
    _op("stt", "語音轉文字", "speech-to-text and dictation", "technology",
        ("stt", "asr", "語音", "语音", "聽寫", "听写", "dictation")),
    _op("proxy", "網絡代理", "proxy, VPN, routing", "technology",
        ("代理", "proxy", "vpn", "clash", "分流", "轉發", "转发")),
    _op("scraping", "網頁抓取", "scraping and anti-bot workarounds", "technology",
        ("爬蟲", "爬虫", "scraping", "抓取", "cloudflare")),
    _op("self_hosted", "自架服務", "self-hosted services", "technology",
        ("自架", "self-host", "自建", "伺服器", "服务器")),
    _op("ai_art", "AI 繪圖", "image generation and models", "technology",
        ("ai 繪圖", "ai绘图", "midjourney", "stable diffusion", "comfyui", "生圖", "生图")),
    _op("github", "GitHub", "GitHub repos, actions, workflows", "technology",
        ("github", "action", "workflow", "repo")),
    _op("privacy", "私隱安全", "privacy and security hygiene", "technology",
        ("私隱", "私隐", "隱私", "隐私", "security", "安全")),
    _op("stock_market", "股票投資", "stock picking and markets", "economics",
        ("股票", "台股", "港股", "美股", "投資", "投资")),
    _op("crypto", "加密貨幣", "crypto assets", "economics",
        ("加密貨幣", "加密货币", "bitcoin", "比特幣", "比特币", "eth")),
    _op("study_abroad", "留學", "studying abroad", "learning",
        ("留學", "留学", "外國", "外国", "申請學校", "申请学校")),
    _op("weight_loss", "減肥", "weight loss and diet", "life",
        ("減肥", "减肥", "體重", "体重", "斷食", "断食")),
    _op("insomnia", "失眠", "sleep problems", "life",
        ("失眠", "睡眠", "sleep")),
    _op("anxiety", "焦慮", "anxiety and stress", "relationships",
        ("焦慮", "焦虑", "壓力", "压力", "anxiety")),
    _op("no_mans_sky", "無人深空", "No Man's Sky", "games",
        ("無人深空", "无人深空", "no man's sky", "nms")),
    _op("stick_building", "木棍建築", "stick-building game", "games",
        ("木棍", "建築", "建筑", "building game")),
    _op("book_review", "書評", "book reviews and reading notes", "writing",
        ("書評", "书评", "讀後感", "读后感", "書", "book")),
    _op("film", "電影", "films and TV", "writing",
        ("電影", "电影", "影集", "電視劇", "电视剧", "film", "movie")),
    _op("nazi_history", "納粹歷史", "Nazi Germany and its historiography", "politics",
        ("納粹", "纳粹", "nazi", "希特勒", "hitler")),
    _op("addiction", "成癮", "addiction and compulsion", "life",
        ("成癮", "成瘾", "上癮", "上瘾", "addiction")),
    _op("none", "（無明顯主題）", "no single identifiable topic", "", ()),
)

GENRES: tuple[Option, ...] = (
    _op("analysis", "分析", "analytical breakdown or explanation"),
    _op("tutorial", "教學", "step-by-step how-to"),
    _op("discussion", "討論", "open-ended discussion or debate"),
    _op("creation", "創作", "writing or generating content"),
    _op("debugging", "除錯", "debugging and fixing a concrete problem"),
    _op("planning", "規劃", "planning and decision-making"),
    _op("comparison", "比較", "comparing options or ideas"),
    _op("summary", "摘要", "summarising material"),
    _op("translation", "翻譯", "translation or rewriting"),
    _op("brainstorm", "頭腦風暴", "idea generation"),
    _op("qa", "問答", "direct question and answer"),
    _op("decision", "決策", "choosing between concrete actions"),
    _op("chitchat", "閒聊", "casual conversation"),
)

LANGUAGES: tuple[Option, ...] = (
    _op("zh", "中文", "mostly Chinese"),
    _op("en", "英文", "mostly English"),
    _op("mixed", "中英混雜", "Chinese and English mixed"),
    _op("ja", "日文", "mostly Japanese"),
    _op("other", "其他語言", "another language"),
)

SENSITIVITY: tuple[Option, ...] = (
    _op("normal", "一般", "safe to publish as is"),
    _op("private", "私人", "personal details, keep local"),
    _op("sensitive", "敏感", "politics/health/legal risk, review before publishing"),
)

FLAGS: tuple[Option, ...] = (
    _op("has_code", "含程式碼", "the conversation contains source code or shell commands"),
    _op("is_series", "連載/專案", "part of an ongoing series or project"),
    _op("publishable", "適合發佈", "good enough to become a public post"),
    _op("has_private_info", "含私隱", "names, addresses, accounts or other personal data"),
)

DEPTH_LEVELS: tuple[str, ...] = (
    "1 表層問答 — shallow Q&A",
    "2 一般 — ordinary exchange",
    "3 中等 — some depth",
    "4 深入 — in-depth",
    "5 研究級 — research-grade",
)

DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "domain", "領域", "choice",
        "這段對話最主要屬於哪一個領域？只選最接近的一個。",
        DOMAINS,
    ),
    Dimension(
        "subdomain", "子領域", "choice",
        "這段對話的具體子領域是哪一個？選最接近的；真的不確定就選 other 類的 misc。",
        SUBDOMAINS,
    ),
    Dimension(
        "concept", "主題", "choice",
        "對話中最具體、最有辨識度的主題、人物、作品或工具是哪一個？沒有明顯主題就選 none。",
        CONCEPTS,
    ),
    Dimension(
        "genre", "類型", "choice",
        "這段對話的性質最接近哪一種？",
        GENRES,
    ),
    Dimension(
        "depth", "深度", "score",
        "這段對話的深度如何？1 是表層問答，5 是研究級別的深入鑽研。",
        (),
        DEPTH_LEVELS,
    ),
    Dimension(
        "language", "語言", "choice",
        "對話主要使用哪一種語言？",
        LANGUAGES,
    ),
    Dimension(
        "sensitivity", "敏感度", "choice",
        "這段對話包含的內容有多敏感？",
        SENSITIVITY,
    ),
    Dimension("has_code", "含程式碼", "noul", "對話中是否包含程式碼、指令或設定檔？"),
    Dimension("is_series", "連載/專案", "noul", "這段對話是否明顯屬於一個持續進行的專案或連載？"),
    Dimension("publishable", "適合發佈", "noul", "這段對話整理後是否值得公開發佈成一篇博文？"),
    Dimension("has_private_info", "含私隱", "noul", "對話中是否出現姓名、地址、帳號或其他個人資料？"),
)

DIMENSION_BY_ID = {dimension.id: dimension for dimension in DIMENSIONS}

#: Ids that are too generic to use as English keywords in the rules fallback.
_RULE_SKIP_IDS = frozenset(
    {"other", "misc", "none", "chitchat", "qa", "ai", "zh", "en", "ja", "mixed", "private", "normal", "sensitive"}
)


# ---------------------------------------------------------------------------
# Tag objects and answer handling
# ---------------------------------------------------------------------------


@dataclass
class Tag:
    name: str
    dim: str
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "dim": self.dim, "confidence": round(self.confidence, 3)}


@dataclass
class Taxonomy:
    domains: tuple[Option, ...] = DOMAINS
    subdomains: tuple[Option, ...] = SUBDOMAINS
    concepts: tuple[Option, ...] = CONCEPTS
    genres: tuple[Option, ...] = GENRES
    languages: tuple[Option, ...] = LANGUAGES
    sensitivity: tuple[Option, ...] = SENSITIVITY
    flags: tuple[Option, ...] = FLAGS
    extra: dict[str, Any] = field(default_factory=dict)

    def dimensions(self) -> tuple[Dimension, ...]:
        return (
            Dimension("domain", "領域", "choice", DIMENSIONS[0].question, self.domains),
            Dimension("subdomain", "子領域", "choice", DIMENSIONS[1].question, self.subdomains),
            Dimension("concept", "主題", "choice", DIMENSIONS[2].question, self.concepts),
            Dimension("genre", "類型", "choice", DIMENSIONS[3].question, self.genres),
            Dimension("depth", "深度", "score", DIMENSIONS[4].question, (), DEPTH_LEVELS),
            Dimension("language", "語言", "choice", DIMENSIONS[5].question, self.languages),
            Dimension("sensitivity", "敏感度", "choice", DIMENSIONS[6].question, self.sensitivity),
            *[dimension for dimension in DIMENSIONS if dimension.kind == "noul"],
        )

    # -- questions -------------------------------------------------------
    def questions(self) -> dict[str, dict[str, Any]]:
        """The ``questions`` object for ``POST /v1/systemone``."""
        payload: dict[str, dict[str, Any]] = {}
        for dimension in self.dimensions():
            if dimension.kind == "choice":
                payload[dimension.id] = {
                    "type": "choice",
                    "instructions": dimension.question,
                    "criteria": {option.id: option.prompt_text() for option in dimension.options},
                }
            elif dimension.kind == "score":
                payload[dimension.id] = {
                    "type": "score",
                    "instructions": dimension.question,
                    "criteria": list(dimension.levels),
                }
            else:
                payload[dimension.id] = {"type": "noul", "instructions": dimension.question}
        return payload

    # -- lookups ---------------------------------------------------------
    def choice_question(self, dimension: str, options: Iterable[Option]) -> dict[str, Any] | None:
        """A ``choice`` question restricted to ``options``.

        OpenJev is a small diffusion model: offering 80 subdomains in the same
        batch makes it answer *something* from the list rather than the right
        thing, so the studio asks domain first and then narrows these options.
        """
        entries = {option.id: option.prompt_text() for option in options}
        if len(entries) < 2:
            return None
        found = next((item for item in DIMENSIONS if item.id == dimension), None)
        return {
            "type": "choice",
            "instructions": found.question if found else dimension,
            "criteria": entries,
        }

    def subdomain_question(self, domain_id: str) -> dict[str, Any] | None:
        options = [option for option in self.subdomains if option.parent == domain_id]
        return self.choice_question("subdomain", options)

    def concept_question(self, domain_id: str) -> dict[str, Any] | None:
        options = [
            option
            for option in self.concepts
            if option.id == "none" or option.parent in (domain_id, "")
        ]
        return self.choice_question("concept", options)

    def option(self, dimension: str, value: str) -> Option | None:
        table = {
            "domain": self.domains,
            "subdomain": self.subdomains,
            "concept": self.concepts,
            "genre": self.genres,
            "language": self.languages,
            "sensitivity": self.sensitivity,
        }.get(dimension, ())
        for option in table:
            if option.id == value:
                return option
        return None

    # -- compose ---------------------------------------------------------
    def compose(self, answers: dict[str, Any]) -> list[Tag]:
        """Turn raw System One answers into display tags."""
        tags: list[Tag] = []

        chosen = _choice(answers, "domain")
        domain = self.option("domain", chosen[0]) if chosen else None
        sub = _choice(answers, "subdomain")
        sub_option = self.option("subdomain", sub[0]) if sub else None

        # The two questions are asked independently, so they can disagree (a
        # chat reads as "philosophy 0.62 / politics 0.37" but its subdomain
        # belongs to politics). When the subdomain is confident and the domain
        # is not, let the subdomain's parent win instead of dropping the tag.
        if sub_option is not None and sub_option.parent and domain is not None:
            if sub_option.parent != domain.id:
                parent = self.option("domain", sub_option.parent)
                if parent is not None and sub[1] >= 0.55 and chosen[1] <= 0.75:
                    domain = parent
                else:
                    sub_option = None

        if domain is not None:
            tags.append(Tag(domain.label, "domain", chosen[1] if chosen else 0.5))
        if sub_option is not None and sub[1] >= 0.45:
            tags.append(Tag(sub_option.label, "subdomain", sub[1]))

        concept = _choice(answers, "concept")
        if concept and concept[1] >= 0.45:
            option = self.option("concept", concept[0])
            if option and option.id != "none":
                tags.append(Tag(option.label, "concept", concept[1]))

        genre = _choice(answers, "genre")
        if genre:
            option = self.option("genre", genre[0])
            if option:
                tags.append(Tag(option.label, "genre", genre[1]))

        depth = _score(answers, "depth")
        if depth is not None:
            level = max(1, min(5, int(round(depth[0])) + 1))
            tags.append(Tag(f"深度 {level}/5", "depth", depth[1]))

        language = _choice(answers, "language")
        if language:
            option = self.option("language", language[0])
            if option:
                tags.append(Tag(option.label, "language", language[1]))

        sensitivity = _choice(answers, "sensitivity")
        if sensitivity:
            option = self.option("sensitivity", sensitivity[0])
            if option and option.id != "normal":
                tags.append(Tag(option.label, "flag", sensitivity[1]))

        for flag in self.flags:
            probability = _noul(answers, flag.id)
            if probability is not None and probability >= 0.5:
                tags.append(Tag(flag.label, "flag", probability))
        return _dedupe(tags)

    def rules(self, text: str, title: str = "") -> list[Tag]:
        """Offline fallback: keyword scoring, no model required."""
        haystack = f"{title}\n{text}".lower()
        title_lower = (title or "").lower()

        def score_options(options: tuple[Option, ...]) -> list[tuple[float, Option]]:
            scored: list[tuple[float, Option]] = []
            for option in options:
                needles = {keyword.lower() for keyword in option.keywords if len(keyword) >= 2}
                if len(option.label) >= 3:
                    needles.add(option.label.lower())
                # The ASCII id doubles as an English keyword ("marxism",
                # "hexo", "docker"); word boundaries keep "unity" out of
                # "community".
                identifier = option.id.lower()
                use_id = (
                    len(identifier) >= 3
                    and identifier.isalpha()
                    and identifier not in _RULE_SKIP_IDS
                )
                if not needles and not use_id:
                    continue
                score = 0.0
                for needle in needles:
                    if needle in title_lower:
                        score += 3.0
                    score += min(haystack.count(needle), 5) * 1.0
                if use_id:
                    pattern = re.compile(rf"\b{re.escape(identifier)}\b")
                    hits = len(pattern.findall(haystack))
                    if hits:
                        if pattern.search(title_lower):
                            score += 3.0
                        score += min(hits, 5) * 1.0
                if score:
                    scored.append((score, option))
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored

        scored = score_options(self.domains)

        tags: list[Tag] = []
        if scored:
            best_score, best = scored[0]
            tags.append(Tag(best.label, "domain", min(1.0, best_score / 10.0)))
        else:
            best = self.option("domain", "other") or self.domains[-1]
            tags.append(Tag(best.label, "domain", 0.3))

        # Subdomain / concept: only offer matches inside the chosen domain so
        # the rule output never contradicts itself.
        subdomain = next(
            (
                (score, option)
                for score, option in score_options(self.subdomains)
                if option.parent == best.id
            ),
            None,
        )
        if subdomain and subdomain[0] >= 2:
            tags.append(Tag(subdomain[1].label, "subdomain", min(1.0, subdomain[0] / 8.0)))

        concept = next(
            (
                (score, option)
                for score, option in score_options(self.concepts)
                if option.parent in (best.id, "") and score >= 3
            ),
            None,
        )
        if concept and concept[1].id != "none":
            tags.append(Tag(concept[1].label, "concept", min(1.0, concept[0] / 8.0)))

        # Genre heuristics.
        genre_id = "discussion"
        if "```" in text or "def " in text or "import " in text or "$ " in text:
            genre_id = "debugging"
        if any(word in title_lower for word in ("如何", "怎麼", "怎样", "how to", "why")):
            genre_id = "qa"
        if any(word in title_lower for word in ("比較", "比较", "vs", "差異", "差异", "difference")):
            genre_id = "comparison"
        if any(word in title_lower for word in ("幫我寫", "帮我写", "生成", "draft", "write")):
            genre_id = "creation"
        if any(word in title_lower for word in ("規劃", "规划", "計劃", "计划", "plan")):
            genre_id = "planning"
        genre = self.option("genre", genre_id)
        if genre:
            tags.append(Tag(genre.label, "genre", 0.4))

        # Language by CJK ratio.
        sample = text[:4000]
        cjk = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
        latin = sum(1 for char in sample if char.isascii() and char.isalpha())
        total = cjk + latin
        if total:
            ratio = cjk / total
            # Real chat text mixes product names into Chinese sentences, so a
            # high threshold would label almost every technical chat "mixed".
            language_id = "zh" if ratio > 0.35 else "en" if ratio < 0.08 else "mixed"
        else:
            language_id = "other"
        language = self.option("language", language_id)
        if language:
            tags.append(Tag(language.label, "language", 0.5))

        if "```" in text or "def " in text or "class " in text:
            tags.append(Tag("含程式碼", "flag", 0.8))

        length = len(text)
        depth_level = 2 if length < 800 else 3 if length < 4000 else 4
        tags.append(Tag(f"深度 {depth_level}/5", "depth", 0.3))
        return _dedupe(tags)

    def post_tags(self, tags: Iterable[Tag], provider: str) -> list[str]:
        """Coarse front-matter tags: AI 對話 + provider + domain only."""
        provider_label = {"openwebui": "OpenWebUI", "gemini": "Gemini"}.get(provider, provider.title())
        result = ["AI对话", provider_label]
        for tag in tags:
            if tag.dim == "domain" and tag.name not in result:
                result.append(tag.name)
                break
        return result


def _dedupe(tags: list[Tag]) -> list[Tag]:
    seen: set[str] = set()
    unique: list[Tag] = []
    for tag in tags:
        if tag.name in seen:
            continue
        seen.add(tag.name)
        unique.append(tag)
    return unique


def _choice(answers: dict[str, Any], key: str) -> tuple[str, float] | None:
    answer = answers.get(key)
    if not isinstance(answer, dict):
        return None
    value = answer.get("choice")
    if not isinstance(value, str) or not value:
        return None
    probabilities = answer.get("probabilities")
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)):
        if isinstance(probabilities, dict) and probabilities:
            confidence = max(float(value or 0) for value in probabilities.values())
        else:
            confidence = 0.0
    return value, float(confidence)


def _noul(answers: dict[str, Any], key: str) -> float | None:
    answer = answers.get(key)
    if not isinstance(answer, dict):
        return None
    value = answer.get("noul")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _score(answers: dict[str, Any], key: str) -> tuple[float, float] | None:
    answer = answers.get(key)
    if not isinstance(answer, dict):
        return None
    value = answer.get("score")
    if isinstance(value, (int, float)):
        confidence = answer.get("confidence")
        return float(value), float(confidence or 0.0)
    return None


def load_taxonomy(path: Any = None) -> Taxonomy:
    """Load the built-in taxonomy, optionally extended by a JSON file.

    The JSON file is additive only::

        {"concepts": {"my_topic": {"label": "我的主題",
                                   "description": "...",
                                   "parent": "technology",
                                   "keywords": ["keyword"]}},
         "subdomains": {...},
         "domains": {...}}

    That keeps upgrades safe: removing a built-in tag never breaks an existing
    index, and the user can add their own topics without touching code.
    """
    if path is None:
        return Taxonomy()
    from pathlib import Path
    import json

    file = Path(path)
    if not file.is_file():
        return Taxonomy()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Taxonomy()
    if not isinstance(raw, dict):
        return Taxonomy()

    def extend(base: tuple[Option, ...], additions: Any) -> tuple[Option, ...]:
        if not isinstance(additions, dict):
            return base
        known = {option.id for option in base}
        result = list(base)
        for option_id, spec in additions.items():
            if not isinstance(spec, dict) or option_id in known:
                continue
            result.append(
                Option(
                    id=str(option_id),
                    label=str(spec.get("label") or option_id),
                    description=str(spec.get("description") or ""),
                    parent=str(spec.get("parent") or ""),
                    keywords=tuple(str(word) for word in spec.get("keywords") or ()),
                )
            )
        return tuple(result)

    return Taxonomy(
        domains=extend(DOMAINS, raw.get("domains")),
        subdomains=extend(SUBDOMAINS, raw.get("subdomains")),
        concepts=extend(CONCEPTS, raw.get("concepts")),
        genres=extend(GENRES, raw.get("genres")),
        languages=extend(LANGUAGES, raw.get("languages")),
        sensitivity=extend(SENSITIVITY, raw.get("sensitivity")),
        flags=extend(FLAGS, raw.get("flags")),
        extra=raw,
    )
