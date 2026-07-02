#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AstrBot 复读增强插件 v2.0.5 — 性能优化：独立锁/合并遍历/脏标记持久化"""

import random, logging, time, re, copy, asyncio, json, os
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import deque
from difflib import SequenceMatcher
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.message_components import Plain, Image, Face, At
from astrbot.api import AstrBotConfig

logger = logging.getLogger("astrbot")

PLUGIN_NAME = "RepeatPlus-Enterprise"
LOG_PREFIX = f"[{PLUGIN_NAME}]"
DEFAULT_COOLDOWN = 10
CLEANUP_INTERVAL = 3600
CONFIG_SYNC_INTERVAL = 60
DEFAULT_HUMAN_DELAY = "0.5-2.0"
RANK_RETENTION_DAYS = 30
MAX_LENGTH_DEVIATION = 0.3
INTERRUPT_SCALE_FACTOR = 0.1
MAX_WINDOW_SIZE = 20
COMMAND_PREFIXES = ("!", "！", "/", "#")
COOLDOWN_ESCALATION_MAX = 5
FAST_TRIGGER_DECAY_SECONDS = 300
INTERRUPT_COOLDOWN_MULTIPLIER = 2.0
DUPLICATE_SUPPRESSION_SECONDS = 60
SIM_CACHE_MAX = 3000

# 抽老公/老婆系统
HUSBAND_ACTIVE_DAYS = 30
HUSBAND_CLEANUP_INTERVAL = 86400
HUSBAND_FORCE_CD_DAYS = 3
HUSBAND_DAILY_LIMIT = 1
MAX_RECORDS_DEFAULT = 500

# 数据持久化目录
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# 抽老公/老婆话术模板 — 极简符号风
# 老婆模式通过 _T() 运行时替换: 老公→老婆, 他→她, 夫君→娘子, 真命天子→真命天女, 男人们→女人们, 一天一夫→一天一妻
_HUB_DRAW_ALREADY = [
    "💕 {user} 今天已经有老公了~\n【{husband}】就是你的今日夫君！\n专一是美德 ✨\n>> /我的老公 查看记录",
    "🔒 {user} 今天已绑定！\n【{husband}】你的真命天子！\n再来拆散人家不好吧…\n>> /我的老公 查看记录",
    "💍 今日夫君已就位！\n【{husband}】就是 {user} 的现任！\n重婚犯法！明天赶早~\n>> /我的老公 查看记录",
    "📜 婚姻登记处提醒：\n【{husband}】{user} 今天已领证！\n一天一夫，群规如山！\n>> /我的老公 查看记录",
    "🕊️ {user} 的今日老公：【{husband}】\n别贪心，明天再换！\n珍惜眼前人 ❤️\n>> /我的老公 查看记录",
]
_HUB_DRAW_ALREADY_MULTI = [
    "你今天已经抽了 {count} 次老公了！\n最近一位：【{husband}】\n明天再来吧~\n>> /我的老公 查看全部",
    "今日名额已用完！({count}次)\n现任老公：【{husband}】\n群里的男人们已被你抽遍了…\n>> /我的老公 查看全部",
    "够了够了！今天已经抽了 {count} 个！\n最新入宫：【{husband}】\n给他留点面子吧 😅\n>> /我的老公 查看全部",
    "你的后宫已经满了！({count}位)\n最新入宫：【{husband}】\n明天再来选秀吧~\n>> /我的老公 查看全部",
    "今日手气不错嘛，{count} 个老公了！\n最近一位：【{husband}】\n雨露均沾，别偏心~\n>> /我的老公 查看全部",
]
_HUB_DRAW_RESULT = [
    "🌸 天降良缘！\n【{husband}】就是 {user} 的今日老公！\n{suffix}",
    "🎯 命运之轮转动！\n【{husband}】{user} 抽中了作为今日老公！\n{suffix}",
    "💘 缘分到了！\n【{husband}】就是 {user} 的真命天子！\n{suffix}",
    "🎪 群友大转盘开奖！\n【{husband}】{user} 喜提老公一枚！\n{suffix}",
    "🎲 骰子已掷出！\n【{husband}】{user} 的本日伴侣！\n{suffix}",
    "📨 系统提示：{user} 收到一份老公快递\n【{husband}】请签收！\n{suffix}",
]
_HUB_DRAW_EMPTY = [
    "😢 老公池空空如也…\n群友们都潜水了，快出来冒个泡吧！\n>> 管理员可开启「不限制活跃」让潜水党也能被抽到",
    "🏜️ 沙漠中找不到老公…\n需要有人在群里说话（30天内）才能抽哦~\n>> 或让管理开启「不限制活跃」模式",
    "🌊 大海捞老公…捞了个空\n快让群友们活跃起来吧！\n>> 管理面板可开启全群抽取",
    "🕳️ 老公池干涸了！最近没人说话…\n老公都跑光了！\n>> 管理员可关闭「仅活跃成员」限制",
    "📭 今日老公库存告急！\n活跃群友不够抽了，让大家冒个泡吧~\n>> 或开启全群抽取模式",
]
_HUB_DRAW_SUFFIX = [
    "好好宠他，别让他跑了 ❤️\n🎫 剩余次数 {remain} 次",
    "记得给他买奶茶 🧋\n🎫 剩余次数 {remain} 次",
    "今天的幸福就交给你了！\n🎫 剩余次数 {remain} 次",
    "请对人家负责哦 🤝\n🎫 剩余次数 {remain} 次",
    "今晚加个鸡腿 🍗\n🎫 剩余次数 {remain} 次",
    "把好运分享给他吧 ✨\n🎫 剩余次数 {remain} 次",
]
_HUB_FORCE_OK = [
    "💍 {user} 霸气宣言！\n【{target}】已被捕获为老公！\n⏳ 冷却时间：{cd} 天\n>> /老公帮助 查看指令",
    "⚡ {user} 发动了「强制绑定」！\n【{target}】成功捕获为老公！\n⏳ 冷却时间：{cd} 天\n>> /老公帮助 查看指令",
    "🔨 {user} 一锤定音！\n【{target}】已被钦定为老公！\n⏳ 冷却时间：{cd} 天\n>> /老公帮助 查看指令",
    "🦍 {user} 扛起【{target}】就跑！\n「从今天起你就是我老公了！」\n⏳ 冷却时间：{cd} 天\n>> /老公帮助 查看指令",
    "🎣 {user} 撒下天罗地网！\n【{target}】被捕获为专属老公！\n⏳ 冷却时间：{cd} 天\n>> /老公帮助 查看指令",
    "🏴‍☠️ {user} 劫持成功！\n【{target}】已被押送至婚姻登记处！\n⏳ 冷却时间：{cd} 天\n>> /老公帮助 查看指令",
]
_HUB_FORCE_CD = [
    "⏳ 强娶技能冷却中…\n还需等待 {d}天{h}小时（冷却期 {cd} 天）\n>> /老公帮助 查看指令",
    "🧊 强娶之力还在恢复中…\n{d}天{h}小时后才能再次发动！\n冷却期：{cd} 天\n>> /老公帮助 查看指令",
    "😤 冷静！强娶是有代价的！\n还需 {d}天{h}小时才能再次使用\n冷却期：{cd} 天\n>> /老公帮助 查看指令",
    "🛑 强娶许可证已过期！\n{d}天{h}小时后自动续期\n冷却期：{cd} 天\n>> /老公帮助 查看指令",
    "🔋 强娶能量条：充电中…\n还需 {d}天{h}小时充满\n冷却期：{cd} 天\n>> /老公帮助 查看指令",
]
_HUB_FORCE_NO_TARGET = [
    "⚠️ 请指定强娶目标！\n格式：/强娶老公 @用户\n>> /老公帮助 查看指令",
    "🎯 你要强娶谁？请 @ 对方！\n格式：/强娶老公 @用户\n>> /老公帮助 查看指令",
    "🤷 没有目标怎么强娶？\n请 @ 你想要强娶的对象！\n>> /老公帮助 查看指令",
    "❓ 强娶谁？@ 他！\n格式：/强娶老公 @用户\n>> /老公帮助 查看指令",
    "👀 你倒是 @ 个人啊！\n格式：/强娶老公 @目标用户\n>> /老公帮助 查看指令",
]
_HUB_FORCE_SELF = [
    "🤔 你不能强娶自己哦！\n请 @ 别人来强娶~\n>> /老公帮助 查看指令",
    "🙅 自攻自受禁止！\n请 @ 别人来强娶~\n>> /老公帮助 查看指令",
    "🪞 对着镜子说「嫁给我」是没有用的…\n请 @ 别人！\n>> /老公帮助 查看指令",
    "🚫 自娶禁止！\n法律法规不允许自己娶自己！\n>> /老公帮助 查看指令",
    "🔄 强娶自己？\n你搁这搞自循环呢？@ 别人！\n>> /老公帮助 查看指令",
]
_HUB_FORCE_NOT_ACTIVE = [
    "😢 目标用户不在候选池中\n他可能已潜水超过 30 天…\n>> 管理员可关闭「仅活跃成员」来解除限制",
    "👻 目标已经潜水太久了！\n30 天内未发言的群友无法被强娶\n>> 或让管理开启全群抽取模式",
    "🏊 目标潜水太深，捞不上来…\n需要对方在 30 天内冒过泡~\n>> 管理面板可关闭活跃限制",
    "🔍 在候选池中找不到该用户\n对方可能被排除或长期潜水\n>> 管理员可调整「仅活跃成员」设置",
]
_HUB_MY_EMPTY = [
    "💕 你今天还没有老公呢~\n快用 /今日老公 抽一个吧！\n🎫 剩余次数 {remain} 次\n>> /老公帮助 查看指令",
    "💕 单身贵族！今日老公名额还未使用~\n发送 /今日老公 邂逅真命天子！\n🎫 剩余次数 {remain} 次\n>> /老公帮助 查看指令",
    "💕 孤独的 {user}…\n今天还没有老公陪伴呢~\n快 /今日老公 抽一个吧！\n🎫 剩余次数 {remain} 次\n>> /老公帮助 查看指令",
    "💕 今日老公位空缺中！\n{user} 还在等什么？/今日老公 来一发！\n🎫 剩余次数 {remain} 次\n>> /老公帮助 查看指令",
    "💔 今天还是一个人…\n没关系，/今日老公 帮你脱单！\n🎫 剩余次数 {remain} 次\n>> /老公帮助 查看指令",
]
_HUB_MY_HEADER = [
    "💕 你今天的老公记录：",
    "📋 今日羁绊记录：",
    "💘 你的今日老公一览：",
    "📜 今日夫君名册：",
    "💝 今日情缘记录：",
]
_HUB_RANK_TITLE = [
    "🏆 群内最受欢迎老公榜",
    "🏆 最强老公争夺榜",
    "🏆 群内老公人气榜",
    "🏆 老公被抢次数天梯榜",
    "🏆 老公排行榜（被强娶次数）",
]
_HUB_RANK_EMPTY = [
    "本群暂无强娶记录\n快来 /强娶老公 抢人吧！\n>> /老公帮助 查看指令",
    "还没有人被强娶过…\n做第一个吃螃蟹的人？/强娶老公\n>> /老公帮助 查看指令",
    "空空如也！\n没有人被强娶过，快去 /强娶老公 打破僵局！\n>> /老公帮助 查看指令",
    "📭 排行榜为空！\n你是第一个来的人，快 /强娶老公 抢占先机！\n>> /老公帮助 查看指令",
    "🏜️ 一片荒芜…\n还没有人发动过强娶，开疆拓土就靠你了！\n>> /老公帮助 查看指令",
]
_HUB_HELP_INTRO = [
    "💕 抽老公系统帮助",
    "💕 老公系统使用指南",
    "💕 抽老公功能说明",
    "💕 老公系统操作手册",
]
_HUB_MY_TAG_DRAW = ["✨ 缘分抽选", "🎯 天降", "🎲 命定", "🌸 随机邂逅", "🎪 抽取"]
_HUB_MY_TAG_FORCE = ["🔨 强制绑定", "💍 霸道抢人", "⚡ 武力夺取", "🏴‍☠️ 直接拿下", "🦍 强娶"]
_HUB_MY_TAG_PROPOSE = ["💒 求婚成对", "💝 情投意合", "💌 双向奔赴", "🌹 玫瑰之约", "💍 求婚成功"]

# 性别替换规则 — 老婆模式运行时替换（按长度降序，避免短词覆盖长词）
_GENDER_SUB = [("真命天子", "真命天女"), ("一天一夫", "一天一妻"), ("男人们", "女人们"), ("夫君", "娘子"), ("老公", "老婆"), ("他", "她")]

# 模板映射表 — all keys map to single (husband) array; _T() applies gender sub for wife mode
_TEMPLATE_MAP = {
    "draw_already": _HUB_DRAW_ALREADY, "draw_already_multi": _HUB_DRAW_ALREADY_MULTI,
    "draw_result": _HUB_DRAW_RESULT, "draw_empty": _HUB_DRAW_EMPTY,
    "draw_suffix": _HUB_DRAW_SUFFIX, "force_ok": _HUB_FORCE_OK,
    "force_cd": _HUB_FORCE_CD, "force_no_target": _HUB_FORCE_NO_TARGET,
    "force_self": _HUB_FORCE_SELF, "force_not_active": _HUB_FORCE_NOT_ACTIVE,
    "my_empty": _HUB_MY_EMPTY, "my_header": _HUB_MY_HEADER,
    "rank_title": _HUB_RANK_TITLE, "rank_empty": _HUB_RANK_EMPTY,
    "help_intro": _HUB_HELP_INTRO, "my_tag_draw": _HUB_MY_TAG_DRAW,
    "my_tag_force": _HUB_MY_TAG_FORCE, "my_tag_propose": _HUB_MY_TAG_PROPOSE,
}

# 指令关键字黑名单
_RANK_CMDS = frozenset(["复读排行榜", "复读日榜", "复读周榜", "复读月榜", "复读统计"])
_MGMT_CMDS = frozenset(["复读开启", "复读关闭", "复读状态", "复读帮助",
    "repeat", "repeat on", "repeat off", "repeat status", "repeat stat", "repeat help"])
COMMAND_KEYWORDS = _RANK_CMDS | _MGMT_CMDS

class InterruptStrategy(ABC):
    @abstractmethod
    async def execute(self, event: AstrMessageEvent, chain: List[Any], intensity: int) -> None:
        pass

    @staticmethod
    def _shuffle_text(text: str, rounds: int) -> str:
        if rounds <= 1: return text
        chars = list(text)
        for _ in range(rounds):
            random.shuffle(chars)
        return "".join(chars)

class _TextTransform(InterruptStrategy):
    """文本变换打断基类"""
    @abstractmethod
    def _transform(self, text: str, intensity: int) -> str: ...

    async def execute(self, event: AstrMessageEvent, chain: List[Any], intensity: int) -> None:
        nc: List[Any] = []
        has_text = False
        for c in chain:
            if isinstance(c, Plain):
                t = getattr(c, 'text', '')
                if t:
                    has_text = True
                    nc.append(Plain(self._transform(t, intensity)))
                else:
                    nc.append(c)
            else:
                nc.append(c)
        await event.send(event.chain_result(
            nc if has_text else [copy.copy(c) for c in chain]))

class ShuffleStrategy(_TextTransform):
    def _transform(self, t: str, i: int) -> str:
        return self._shuffle_text(t, max(1, i))

class ReverseStrategy(_TextTransform):
    def _transform(self, t: str, i: int) -> str:
        if i >= 3 and len(t) > 3:
            mid = len(t) // 2
            return t[:mid][::-1] + t[mid:][::-1]
        return t[::-1]

class CustomTextStrategy(InterruptStrategy):
    def __init__(self, config: AstrBotConfig): self.config = config
    async def execute(self, event: AstrMessageEvent, chain: List[Any], intensity: int) -> None:
        raw = self.config.get("custom_interrupt_texts", "")
        texts = [t.strip() for t in raw.split('\n') if t.strip()]
        msg = random.choice(texts) if texts else "打破复读机！"
        if intensity > 1: msg += "！" * min(intensity - 1, 5)
        await event.send(event.plain_result(msg))

class RepeatPlusPlugin(Star):

    _RANK_MAP = {"复读排行榜": "all", "复读日榜": "day", "复读周榜": "week", "复读月榜": "month"}
    _WIN_LABELS = {"day": "今日", "week": "本周", "month": "本月", "all": "累计"}

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.curr_dir = os.path.dirname(os.path.abspath(__file__))

        # 运行状态
        self.group_history: Dict[str, deque] = {}
        self.last_repeat_time: Dict[str, float] = {}
        self.fast_trigger_count: Dict[str, int] = {}
        self.last_repeated_sig: Dict[str, Tuple[str, float]] = {}
        self.disabled_groups: Set[str] = set()
        self.group_events: Dict[str, List[Dict[str, Any]]] = {}
        self.trigger_times: Dict[str, List[float]] = {}
        self.lock = asyncio.Lock()
        self._hub_active_lock = asyncio.Lock()  # 独立锁，避免热路径与 _sync_config 竞争

        # 策略实例
        self.strategies: Dict[str, InterruptStrategy] = {
            "原话洗牌": ShuffleStrategy(), "反向复读": ReverseStrategy(),
            "自定义话术": CustomTextStrategy(config),
        }

        # 配置缓存 — 在 _sync_config 中刷新，热路径零开销
        self._cfg: Dict[str, Any] = {
            "threshold": 3, "window_size": 5, "fuzzy_threshold": 0.9,
            "enable_weight_decay": False, "allow_same_user": True,
            "min_len": 1, "max_len": 200,
            "cooldown": 10, "cd_escalation": True,
            "dup_suppress": 60, "intr_prob": 0.1, "intr_cd_mul": 2.0,
            "intr_shuffle": True, "intr_reverse": True,
            "intr_custom": True, "intr_silent": False,
            "human_delay": "0.5-2.0", "fast_mode": False,
            "blacklist_re": None, "ignored_groups": set(), "ignored_users": set(),
            "debug": False,
            "hub_daily": 1, "hub_force_cd": 3, "hub_force_daily": 1,
            "hub_propose_daily": 3, "hub_propose_cd": 86400, "hub_active_days": 30,
            "hub_excluded": set(), "hub_keyword": False, "hub_require_active": True,
            "hub_draw_decay_days": 7,
            "enable_husband": True, "enable_wife": True,
            "at_waifu": False, "auto_set_other_half": False,
            "allow_marry_bot": False, "keyword_trigger_mode": "exact",
            "auto_withdraw_enabled": False, "auto_withdraw_delay_seconds": 30,
            "max_records": 500, "whitelist_groups": set(), "blacklist_groups": set(),
        }
        self._cfg_sync_ts = 0.0

        # 相似度缓存
        self._sim_cache: Dict[Tuple[str, str], bool] = {}

        # 抽老公/老婆系统
        self._hub_active: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._hub_records: Dict[str, Dict[str, Any]] = {}
        self._hub_force_cd: Dict[str, float] = {}
        self._hub_rbq: Dict[str, Dict[str, int]] = {}
        self._hub_last_cleanup = 0.0
        self._hub_members_cache: Dict[str, Tuple[List[str], float]] = {}
        self._hub_drawn_recent: Dict[str, Dict[str, float]] = {}  # 抽取概率衰减：{gid: {uid: 上次被抽时间戳}}

        # 求婚系统
        self._proposals: Dict[str, Dict[str, Any]] = {}
        self._hub_propose_cd: Dict[str, float] = {}
        self._hub_propose_count: Dict[str, int] = {}

        # 数据持久化
        self._data_dir = _DATA_DIR
        os.makedirs(self._data_dir, exist_ok=True)
        self._load_persisted_data()
        self._data_dirty = False  # 脏标记：仅在数据变更时持久化

        # 关键词路由表
        self._build_hub_keywords()

        self._log(logging.INFO, "插件已加载 v2.0.5")

    # ============================================================
    # 数据持久化
    # ============================================================
    def _data_path(self, filename: str) -> str:
        return os.path.join(self._data_dir, filename)

    def _save_json(self, filename: str, data: Any) -> None:
        try:
            with open(self._data_path(filename), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log(logging.ERROR, f"保存数据文件 {filename} 失败: {e}")

    def _load_json(self, filename: str, default: Any = None) -> Any:
        path = self._data_path(filename)
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self._log(logging.ERROR, f"加载数据文件 {filename} 失败: {e}")
            return default

    def _load_persisted_data(self) -> None:
        """从 JSON 文件加载持久化数据"""
        active = self._load_json("active_users.json", {})
        if isinstance(active, dict):
            for gid, users in active.items():
                if gid not in self._hub_active:
                    self._hub_active[gid] = {}
                for uid, data in users.items():
                    if isinstance(data, dict):
                        self._hub_active[gid][uid] = data
        fc = self._load_json("forced_marriage.json", {})
        if isinstance(fc, dict):
            self._hub_force_cd = {k: float(v) for k, v in fc.items()}
        rbq = self._load_json("rbq_stats.json", {})
        if isinstance(rbq, dict):
            self._hub_rbq = {k: {kk: int(vv) for kk, vv in v.items()} for k, v in rbq.items()}
        recs = self._load_json("wife_records.json", {})
        if isinstance(recs, dict):
            self._hub_records = recs
        pc = self._load_json("propose_cd.json", {})
        if isinstance(pc, dict):
            self._hub_propose_cd = {k: float(v) for k, v in pc.items()}
        pn = self._load_json("propose_count.json", {})
        if isinstance(pn, dict):
            safe_pn = {}
            for k, v in pn.items():
                if k == "_date":
                    safe_pn[k] = v
                else:
                    try:
                        safe_pn[k] = int(v)
                    except (ValueError, TypeError):
                        safe_pn[k] = 0
            self._hub_propose_count = safe_pn
        self._dbg("持久化数据已加载")

    def _save_persisted_data(self) -> None:
        """保存数据到 JSON 文件"""
        self._save_json("active_users.json", self._hub_active)
        self._save_json("forced_marriage.json", self._hub_force_cd)
        self._save_json("rbq_stats.json", self._hub_rbq)
        self._save_json("wife_records.json", self._hub_records)
        self._save_json("propose_cd.json", self._hub_propose_cd)
        self._save_json("propose_count.json", self._hub_propose_count)

    # ============================================================
    # 关键词路由表构建
    # ============================================================
    def _build_hub_keywords(self) -> None:
        """构建关键词路由表 — 关键词始终全部注册，模式检查由各 handler 内部处理"""
        # 强娶共享指令：根据当前启用的模式决定路由
        hus, wife = self._hub_enabled()
        if hus and not wife:
            force_handler = self._cmd_husband_force
        elif wife and not hus:
            force_handler = self._cmd_wife_force
        else:
            force_handler = self._cmd_wife_force  # 双开时默认老婆模式

        kw: Dict[str, Any] = {
            # 共享指令
            "不限制成员抽取": self._cmd_husband_toggle_active,
            "强娶": force_handler,
            "关系图": self._cmd_relation_graph, "gxt": self._cmd_relation_graph,
            "羁绊图谱": self._cmd_relation_graph,
            "求婚": self._cmd_propose, "qh": self._cmd_propose,
            "接受求婚": self._cmd_accept_proposal,
            "拒绝求婚": self._cmd_reject_proposal,
            "重置记录": self._cmd_reset_records, "czjl": self._cmd_reset_records,
            "重置强娶时间": self._cmd_reset_force_cd, "czqqsj": self._cmd_reset_force_cd,
            # 老公模式 — 始终注册，handler 内部检查模式
            "今日老公": self._cmd_husband_draw, "抽老公": self._cmd_husband_draw,
            "我的老公": self._cmd_husband_my, "老公记录": self._cmd_husband_my,
            "老公排行": self._cmd_husband_rank, "老公排行榜": self._cmd_husband_rank,
            "老公帮助": self._cmd_husband_help,
            "强娶老公": self._cmd_husband_force,
            # 老婆模式 — 始终注册，handler 内部检查模式
            "今日老婆": self._cmd_wife_draw, "抽老婆": self._cmd_wife_draw, "jrlp": self._cmd_wife_draw,
            "我的老婆": self._cmd_wife_my, "wdlp": self._cmd_wife_my,
            "老婆记录": self._cmd_wife_my,
            "老婆排行": self._cmd_wife_rank, "老婆排行榜": self._cmd_wife_rank,
            "老婆帮助": self._cmd_wife_help,
            "强娶老婆": self._cmd_wife_force, "qiangqu": self._cmd_wife_force,
        }
        self._hub_kw = kw

    # ============================================================
    # 工具方法
    # ============================================================
    def _log(self, level: int, msg: str, exc_info: bool = False) -> None:
        logger.log(level, f"{LOG_PREFIX} {msg}", exc_info=exc_info)

    def _dbg(self, msg: str) -> None:
        if self._cfg.get("debug"):
            self._log(logging.INFO, f"[DEBUG] {msg}")

    def _parse_set(self, key: str) -> Set[str]:
        raw = self.config.get(key, "")
        return {s.strip() for s in str(raw).replace('\n', ',').split(',') if s.strip()} if raw else set()

    def _gid(self, event: AstrMessageEvent) -> Optional[str]:
        mo = getattr(event, 'message_obj', None)
        if not mo: return None
        g = str(getattr(mo, 'group_id', ''))
        return g or None

    async def _check_admin(self, event: AstrMessageEvent, gid: str) -> bool:
        """检查发送者是否为机器人拥有者、群主或管理员"""
        uid = str(event.get_sender_id())
        # 机器人拥有者（登录 bot 的 QQ 号）始终拥有最高权限
        bot_id = str(getattr(event.message_obj, 'self_id', ''))
        if uid == bot_id:
            return True
        try:
            platform = event.get_platform_name()
            if platform == "aiocqhttp":
                resp = await event.bot.api.call_action(
                    "get_group_member_info", group_id=int(gid), user_id=int(uid))
                if isinstance(resp, dict):
                    data = resp.get("data", None)
                    if isinstance(data, dict):
                        role = data.get("role", "")
                    else:
                        role = resp.get("role", "")
                    return role in ("owner", "admin")
        except Exception as e:
            self._dbg(f"管理员检查失败: {e}")
        return False

    @staticmethod
    def _T(tpl: str, mode: str) -> str:
        """性别替换: 老公模式原样返回, 老婆模式替换 老公→老婆 他→她 等"""
        if mode != "wife": return tpl
        for old, new in _GENDER_SUB: tpl = tpl.replace(old, new)
        return tpl

    def _hb(self, key: str, mode: str = "husband") -> str:
        """Husband/Wife Bridge: 返回一条随机模板(已应用性别替换)"""
        arr = _TEMPLATE_MAP.get(key)
        return self._T(random.choice(arr), mode) if arr else ""

    def _hb_label(self, mode: str, husband_label: str = "老公", wife_label: str = "老婆") -> str:
        return husband_label if mode == "husband" else wife_label

    def _hub_enabled(self) -> Tuple[bool, bool]:
        return self._cfg.get("enable_husband", True), self._cfg.get("enable_wife", True)

    async def _sync_config(self) -> None:
        now = time.time()
        if now - self._cfg_sync_ts < CONFIG_SYNC_INTERVAL:
            return
        async with self.lock:
            now = time.time()
            if now - self._cfg_sync_ts < CONFIG_SYNC_INTERVAL:
                return

            old_husband = self._cfg.get("enable_husband", True)
            old_wife = self._cfg.get("enable_wife", True)
            # 聚合所有配置到 _cfg 缓存
            self._cfg = {
                "threshold": self.config.get("threshold", 3),
                "window_size": min(self.config.get("window_size", 5), MAX_WINDOW_SIZE),
                "fuzzy_threshold": self.config.get("fuzzy_threshold", 0.9),
                "enable_weight_decay": self.config.get("enable_weight_decay", False),
                "allow_same_user": self.config.get("allow_same_user", True),
                "min_len": self.config.get("min_message_length", 1),
                "max_len": self.config.get("max_message_length", 200),
                "cooldown": self.config.get("cooldown_time", DEFAULT_COOLDOWN),
                "cd_escalation": self.config.get("cooldown_escalation", True),
                "dup_suppress": self.config.get("duplicate_suppression_seconds", DUPLICATE_SUPPRESSION_SECONDS),
                "intr_prob": self.config.get("interrupt_probability", 0.1),
                "intr_cd_mul": self.config.get("interrupt_cooldown_multiplier", INTERRUPT_COOLDOWN_MULTIPLIER),
                "intr_shuffle": self.config.get("interrupt_shuffle", True),
                "intr_reverse": self.config.get("interrupt_reverse", True),
                "intr_custom": self.config.get("interrupt_custom", True),
                "intr_silent": self.config.get("interrupt_silent", False),
                "human_delay": self.config.get("human_delay", DEFAULT_HUMAN_DELAY),
                "fast_mode": self.config.get("fast_mode", False),
                "blacklist_re": self._compile_blacklist(),
                "ignored_groups": self._parse_set("ignored_groups"),
                "ignored_users": self._parse_set("ignored_users"),
                "debug": self.config.get("debug_mode", False),
                "hub_daily": self.config.get("husband_daily_limit", HUSBAND_DAILY_LIMIT),
                "hub_force_cd": self.config.get("husband_force_cd_days", HUSBAND_FORCE_CD_DAYS),
                "hub_force_daily": self.config.get("husband_force_daily", 1),
                "hub_propose_daily": self.config.get("husband_propose_daily", 3),
                "hub_propose_cd": self.config.get("husband_propose_cd", 86400),
                "hub_active_days": self.config.get("husband_active_days", HUSBAND_ACTIVE_DAYS),
                "hub_excluded": self._parse_set("husband_excluded_users"),
                "hub_keyword": self.config.get("husband_keyword_trigger", False),
                "hub_require_active": self.config.get("husband_require_active", True),
                "hub_draw_decay_days": self.config.get("husband_draw_decay_days", 7),
                "enable_husband": self.config.get("enable_husband", True),
                "enable_wife": self.config.get("enable_wife", True),
                "at_waifu": self.config.get("at_waifu", False),
                "auto_set_other_half": self.config.get("auto_set_other_half", False),
                "allow_marry_bot": self.config.get("allow_marry_bot", False),
                "keyword_trigger_mode": self.config.get("keyword_trigger_mode", "exact"),
                "auto_withdraw_enabled": self.config.get("auto_withdraw_enabled", False),
                "auto_withdraw_delay_seconds": self.config.get("auto_withdraw_delay_seconds", 30),
                "max_records": self.config.get("max_records", MAX_RECORDS_DEFAULT),
                "whitelist_groups": self._parse_set("whitelist_groups"),
                "blacklist_groups": self._parse_set("blacklist_groups"),
            }

            # 模式切换时重建关键词路由表
            new_husband = self._cfg.get("enable_husband", True)
            new_wife = self._cfg.get("enable_wife", True)
            if old_husband != new_husband or old_wife != new_wife:
                self._build_hub_keywords()

            # 配置变更 → 清除相似度缓存
            self._sim_cache.clear()

            # 清理过期群组上下文
            expired = [g for g, t in self.last_repeat_time.items() if now - t > CLEANUP_INTERVAL]
            for g in expired:
                self.group_history.pop(g, None)
                self.last_repeat_time.pop(g, None)
                self.fast_trigger_count.pop(g, None)
                self.last_repeated_sig.pop(g, None)
            if expired: self._dbg(f"已清理 {len(expired)} 个过期群组上下文")

            # 冷却衰减
            for g in list(self.fast_trigger_count.keys()):
                c = self.fast_trigger_count[g]
                if c > 0 and now - self.last_repeat_time.get(g, now) > FAST_TRIGGER_DECAY_SECONDS:
                    self.fast_trigger_count[g] = c - 1
                    self._dbg(f"群 {g} 冷却衰减: L{c}→L{c-1} (冷却{self._get_cd(g):.0f}s)")

            # 30天事件清理
            cutoff = now - RANK_RETENTION_DAYS * 86400
            pruned = 0
            for g in list(self.group_events.keys()):
                before = len(self.group_events[g])
                self.group_events[g] = [e for e in self.group_events[g] if e["ts"] >= cutoff]
                pruned += before - len(self.group_events[g])
                if not self.group_events[g]:
                    self.group_events.pop(g, None)
                    self.trigger_times.pop(g, None)
            for g in list(self.trigger_times.keys()):
                self.trigger_times[g] = [t for t in self.trigger_times[g] if t >= cutoff]
                if not self.trigger_times[g]:
                    self.trigger_times.pop(g, None)
            if pruned: self._dbg(f"已清理 {pruned} 条过期排行榜事件")

            # 抽老公/老婆活跃数据清理
            if now - self._hub_last_cleanup > HUSBAND_CLEANUP_INTERVAL:
                hub_cutoff = now - self._cfg["hub_active_days"] * 86400
                today_str = datetime.now().strftime("%Y-%m-%d")
                yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                hub_pruned = 0
                for g in list(self._hub_active.keys()):
                    before = len(self._hub_active[g])
                    self._hub_active[g] = {
                        u: d for u, d in self._hub_active[g].items()
                        if d.get("ts", 0) >= hub_cutoff
                    }
                    hub_pruned += before - len(self._hub_active[g])
                    # 仅当活跃用户为空且记录非今天/昨天时才清理该群数据
                    if not self._hub_active[g]:
                        if g in self._hub_records:
                            rec = self._hub_records[g]
                            rec_date = rec.get("date", "")
                            if rec_date != today_str and rec_date != yesterday_str:
                                self._hub_records.pop(g, None)
                        self._hub_active.pop(g, None)
                        self._hub_members_cache.pop(g, None)
                        self._hub_drawn_recent.pop(g, None)
                for g in list(self._hub_records.keys()):
                    rec = self._hub_records[g]
                    if "date" in rec:
                        rec_date = rec["date"]
                        if rec_date != today_str and rec_date != yesterday_str:
                            self._hub_records.pop(g, None)
                stale_cache = [g for g, v in self._hub_members_cache.items()
                               if time.time() - v[1] > 300]
                for g in stale_cache:
                    self._hub_members_cache.pop(g, None)
                # 清理过期的概率衰减记录（超过 2 倍衰减天数后已无影响）
                draw_decay = self._cfg.get("hub_draw_decay_days", 7) * 86400 * 2
                for gid, drawn in self._hub_drawn_recent.items():
                    stale = [u for u, t in drawn.items() if now - t > draw_decay]
                    for u in stale:
                        drawn.pop(u, None)
                if hub_pruned: self._dbg(f"已清理 {hub_pruned} 个过期活跃用户")
                force_cd_seconds = self._cfg["hub_force_cd"] * 86400 * 2
                stale_fc = [u for u, t in self._hub_force_cd.items()
                            if now - t > force_cd_seconds]
                for u in stale_fc:
                    self._hub_force_cd.pop(u, None)
                if stale_fc: self._dbg(f"已清理 {len(stale_fc)} 条过期强娶冷却记录")
                self._hub_last_cleanup = now

            # 每日重置求婚次数
            today = datetime.now().strftime("%Y-%m-%d")
            if self._hub_propose_count.get("_date", "") != today:
                self._hub_propose_count = {"_date": today}
            # 清理过期求婚 CD
            stale_pc = [u for u, t in self._hub_propose_cd.items()
                        if now - t > max(self._cfg["hub_propose_cd"] * 5, 86400)]
            for u in stale_pc:
                self._hub_propose_cd.pop(u, None)

            # 持久化保存 — 移出锁外，仅在数据变更时写入
            self._data_dirty = True

            self._cfg_sync_ts = now

        # 锁外持久化，避免阻塞热路径
        if self._data_dirty:
            self._save_persisted_data()
            self._data_dirty = False

    def _compile_blacklist(self):
        bl = self.config.get("content_blacklist", "")
        if not bl:
            return None
        try:
            return re.compile(bl)
        except re.error as e:
            self._log(logging.ERROR, f"正则黑名单语法错误: {e}")
            return None

    # ============================================================
    # 签名与相似度
    # ============================================================
    def _sig(self, chain: List[Any]) -> Tuple[str, str]:
        if not chain: return "", ""
        parts: List[str] = []
        text = ""
        for c in chain:
            if isinstance(c, Plain):
                t = getattr(c, 'text', '').strip()
                if t: parts.append(f"T:{t}"); text += t
            elif isinstance(c, Image):
                v = getattr(c, 'md5', None) or getattr(c, 'file_id', None) or \
                    getattr(c, 'file', None) or getattr(c, 'path', None) or \
                    getattr(c, 'url', None) or "unknown"
                parts.append(f"I:{str(v).split('?')[0]}")
            elif isinstance(c, Face):
                v = getattr(c, 'id', None) or getattr(c, 'face_id', None) or getattr(c, 'number', None) or "0"
                parts.append(f"F:{v}")
        return "|".join(parts), text

    @staticmethod
    def _has_media(sig: str) -> bool:
        return "|I:" in sig or "|F:" in sig or sig.startswith("I:") or sig.startswith("F:")

    def _similar(self, s1: str, t1: str, s2: str, t2: str) -> bool:
        key = (s1, s2)
        cached = self._sim_cache.get(key)
        if cached is not None:
            return cached
        if s1 == s2:
            result = True
        elif not t1 or not t2 or self._has_media(s1) or self._has_media(s2):
            result = False
        elif abs(len(t1) - len(t2)) / max(len(t1), len(t2), 1) > MAX_LENGTH_DEVIATION:
            result = False
        else:
            result = SequenceMatcher(None, t1, t2).ratio() >= self._cfg["fuzzy_threshold"]
        if len(self._sim_cache) >= SIM_CACHE_MAX:
            # FIFO 淘汰：弹出最早插入的键，避免全量清空导致的缓存雪崩
            self._sim_cache.pop(next(iter(self._sim_cache)), None)
        self._sim_cache[key] = result
        return result

    # ============================================================
    # 权重匹配
    # ============================================================
    def _weighted(self, hist: deque, sig: str, txt: str) -> Tuple[float, bool]:
        lm = False
        cfg = self._cfg
        if not cfg["enable_weight_decay"]:
            if cfg["allow_same_user"]:
                m = 0
                for i, h in enumerate(hist):
                    if self._similar(sig, txt, h[0], h[3]): m += 1
                    if i == len(hist) - 1 and m: lm = True
                return float(m), lm
            senders: Set[str] = set()
            for i, h in enumerate(hist):
                if self._similar(sig, txt, h[0], h[3]):
                    senders.add(h[1])
                    if i == len(hist) - 1: lm = True
            return float(len(senders)), lm
        tw, seen = 0.0, set()
        n = len(hist)
        for i, h in enumerate(hist):
            if self._similar(sig, txt, h[0], h[3]):
                if cfg["allow_same_user"]:
                    tw += (i + 1) / n
                elif h[1] not in seen:
                    seen.add(h[1]); tw += (i + 1) / n
                if i == len(hist) - 1: lm = True
        return tw, lm

    # ============================================================
    # 长度过滤
    # ============================================================
    def _pass_len(self, txt: str) -> bool:
        if not txt: return True
        cfg = self._cfg
        if len(txt) < cfg["min_len"]:
            self._dbg(f"过短: '{txt}' ({len(txt)}<{cfg['min_len']})"); return False
        if len(txt) > cfg["max_len"]:
            self._dbg(f"过长: ({len(txt)}>{cfg['max_len']})"); return False
        return True

    # ============================================================
    # 冷却
    # ============================================================
    def _get_cd(self, gid: str) -> float:
        cfg = self._cfg
        base = float(cfg["cooldown"])
        if not cfg["cd_escalation"]: return base
        return base * (1.0 + min(self.fast_trigger_count.get(gid, 0), COOLDOWN_ESCALATION_MAX))

    # ============================================================
    # 排行榜
    # ============================================================
    def _ts_min(self, mode: str) -> Optional[float]:
        n = datetime.now()
        if mode == "day":   s = n.replace(hour=0, minute=0, second=0, microsecond=0)
        elif mode == "week": s = (n - timedelta(days=n.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif mode == "month": s = n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else: return None
        return s.timestamp()

    def _win_label(self, mode: str) -> str:
        return self._WIN_LABELS.get(mode, "累计")

    def _agg_rank(self, gid: str, mode: str, top_n: int = 10) -> Tuple[List[Tuple[str, str, int]], int]:
        events = self.group_events.get(gid, [])
        if not events: return [], 0
        t0 = self._ts_min(mode)
        filtered = [e for e in events if t0 is None or e["ts"] >= t0]
        if not filtered: return [], 0
        uc: Dict[str, Tuple[str, int]] = {}
        for e in filtered:
            sid = e["sid"]; name = e.get("name", sid)
            if sid in uc: _, pc = uc[sid]; uc[sid] = (name, pc + 1)
            else: uc[sid] = (name, 1)
        sorted_u = sorted(uc.items(), key=lambda x: -x[1][1])
        r = []
        for sid, (name, cnt) in sorted_u:
            dn = name if name != sid else (sid[:10] + "…" if len(sid) > 10 else sid)
            r.append((sid, dn, cnt))
            if len(r) >= top_n: break
        return r, len(filtered)

    def _fmt_rank(self, gid: str, mode: str, top_n: int = 10) -> str:
        rank, total = self._agg_rank(gid, mode, top_n)
        tag = self._win_label(mode)
        if not rank:
            return (f"\U0001F4CA 复读排行榜 · {tag}\n"
                    f"{'─'*30}\n  本群暂无复读记录\n{'─'*30}\n"
                    f">> /复读日榜 /复读周榜 /复读月榜")
        lines = [
            f"\U0001F4CA 复读排行榜 · {tag}",
            f"   本群{tag}贡献 {total} 人次",
            "─" * 30,
        ]
        for i, (sid, name, cnt) in enumerate(rank):
            medals = ["🥇", "🥈", "🥉"]
            pf = medals[i] if i < 3 else f"  {i+1:>2}."
            bar = "█" * min(cnt, 15)
            lines.append(f"  {pf} {name}  {cnt}次  {bar}")
        lines.append("─" * 30)
        lines.append(">> /复读日榜 /复读周榜 /复读月榜")
        return "\n".join(lines)

    # ============================================================
    # 事件入口
    # ============================================================
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        try: await self._pipe(event)
        except Exception as e: self._log(logging.ERROR, f"核心逻辑异常: {e}", exc_info=True)

    # ============================================================
    # 排行榜指令
    # ============================================================
    async def _cmd_rank(self, event: AstrMessageEvent, cmd: str) -> None:
        gid = self._gid(event)
        if not gid: await event.send(event.plain_result("⚠️ 排行榜仅支持在群聊中使用。")); return
        await event.send(event.plain_result(self._fmt_rank(gid, self._RANK_MAP[cmd])))

    @filter.command("复读排行榜")
    async def on_rank(self, e: AstrMessageEvent) -> None: await self._cmd_rank(e, "复读排行榜")
    @filter.command("复读日榜")
    async def on_rd(self, e: AstrMessageEvent) -> None: await self._cmd_rank(e, "复读日榜")
    @filter.command("复读周榜")
    async def on_rw(self, e: AstrMessageEvent) -> None: await self._cmd_rank(e, "复读周榜")
    @filter.command("复读月榜")
    async def on_rm(self, e: AstrMessageEvent) -> None: await self._cmd_rank(e, "复读月榜")

    # ============================================================
    # 管理指令
    # ============================================================
    @filter.command("repeat")
    async def on_repeat(self, e: AstrMessageEvent) -> None:
        if not self._gid(e): await e.send(e.plain_result("⚠️ 此指令仅支持在群聊中使用。")); return
        await self._help(e)

    @filter.command("复读开启")
    async def on_on(self, e: AstrMessageEvent) -> None:
        g = self._gid(e)
        if not g: await e.send(e.plain_result("⚠️ 此指令仅支持在群聊中使用。")); return
        self.disabled_groups.discard(g)
        await e.send(e.plain_result("✅ 复读已开启 — 本群开始复读啦！"))

    @filter.command("复读关闭")
    async def on_off(self, e: AstrMessageEvent) -> None:
        g = self._gid(e)
        if not g: await e.send(e.plain_result("⚠️ 此指令仅支持在群聊中使用。")); return
        self.disabled_groups.add(g)
        await e.send(e.plain_result("🚫 复读已关闭 — 本群不再触发复读。"))

    @filter.command("复读状态")
    async def on_status(self, e: AstrMessageEvent) -> None:
        g = self._gid(e)
        if not g: await e.send(e.plain_result("⚠️ 此指令仅支持在群聊中使用。")); return
        if g in self.disabled_groups:
            await e.send(e.plain_result("🚫 复读状态：已关闭"))
            return
        cd = self._get_cd(g)
        elapsed = time.time() - self.last_repeat_time.get(g, 0)
        remain = max(0, cd - elapsed)
        bar_len = 10
        filled = min(bar_len, max(0, int((elapsed / cd) * bar_len) if cd > 0 else bar_len))
        bar = "█" * filled + "░" * (bar_len - filled)
        today = len([t for t in self.trigger_times.get(g, []) if t >= self._ts_min("day")])
        await e.send(e.plain_result(
            f"✅ 复读状态：已开启\n"
            f"⏱️ 冷却进度：{bar} {remain:.0f}s/{cd:.0f}s\n"
            f"\U0001F4CA 今日触发：{today} 次"))

    @filter.command("复读统计")
    async def on_stat(self, e: AstrMessageEvent) -> None:
        g = self._gid(e)
        if not g: await e.send(e.plain_result("⚠️ 此指令仅支持在群聊中使用。")); return
        await self._stats(e, g)

    @filter.command("复读帮助")
    async def on_help(self, e: AstrMessageEvent) -> None: await self._help(e)

    @filter.command("repeat_legacy")
    async def on_rl(self, e: AstrMessageEvent) -> None: await self._help(e)

    # ============================================================
    # 抽老公/老婆系统
    # ============================================================
    async def _hub_sync(self) -> None:
        """hub 命令专用同步：刷新配置 + 每日重置（独立于 _sync_config 的 debounce）"""
        await self._sync_config()
        # 每日重置求婚次数 — 不依赖 _sync_config 的 debounce
        today = datetime.now().strftime("%Y-%m-%d")
        if self._hub_propose_count.get("_date", "") != today:
            async with self.lock:
                if self._hub_propose_count.get("_date", "") != today:
                    self._hub_propose_count = {"_date": today}

    async def _hub_guard(self, event: AstrMessageEvent, mode: str = "husband") -> Optional[str]:
        """公共守卫：gid 检查 + 配置同步 + 模式开关检查，返回 gid 或 None（已发送错误消息）"""
        gid = self._gid(event)
        if not gid:
            await event.send(event.plain_result("⚠️ 此功能仅在群聊中可用。"))
            return None
        await self._hub_sync()
        if mode == "husband" and not self._cfg.get("enable_husband", True):
            await event.send(event.plain_result("❌ 老公模式未开启，请在管理面板中启用「开启老公模式」。"))
            return None
        if mode == "wife" and not self._cfg.get("enable_wife", True):
            await event.send(event.plain_result("❌ 老婆模式未开启，请在管理面板中启用「开启老婆模式」。"))
            return None
        return gid

    def _hub_today(self, gid: str) -> List[Dict[str, Any]]:
        """返回今日记录的副本（只读安全）"""
        rec = self._hub_records.get(gid, {})
        today = datetime.now().strftime("%Y-%m-%d")
        if rec.get("date") != today:
            return []
        return list(rec.get("records", []))

    def _already_msg(self, user_recs: List[Dict], daily: int, mode: str, sender_name: str, sender_id: str) -> Tuple[str, str, str]:
        """构造已绑定提示: 返回 (tpl_key, 格式化文本, husband_id)"""
        h = user_recs[0]
        tpl_key = "draw_already" if daily == 1 else "draw_already_multi"
        fmt = {"user": sender_name or sender_id, "husband": h["husband_name"]}
        if daily > 1: fmt["count"] = len(user_recs)
        return tpl_key, self._hb(tpl_key, mode).format(**fmt), h["husband_id"]

    def _hub_init_today(self, gid: str) -> List[Dict[str, Any]]:
        """初始化今日记录并返回记录列表引用 — 调用方必须在锁内"""
        today = datetime.now().strftime("%Y-%m-%d")
        rec = self._hub_records.setdefault(gid, {"date": today, "records": []})
        if rec.get("date") != today:
            rec["date"] = today
            rec["records"] = []
        return rec["records"]

    def _hub_rbq_incr(self, gid: str, target_id: str) -> None:
        """排行榜计数 +1（force/propose 共用）— 调用方必须在锁内"""
        inner = self._hub_rbq.setdefault(gid, {})
        inner[target_id] = inner.get(target_id, 0) + 1

    def _hub_active_pool(self, gid: str, uid: str, bid: str) -> List[str]:
        active = self._hub_active.get(gid, {})
        excluded = set(self._cfg["hub_excluded"])
        excluded.update([uid, "0"])
        if not self._cfg.get("allow_marry_bot"):
            excluded.add(bid)
        pool = [u for u in active if u not in excluded]
        max_recs = self._cfg.get("max_records", MAX_RECORDS_DEFAULT)
        if max_recs > 0 and len(pool) > max_recs:
            pool = random.sample(pool, max_recs)
        return pool

    async def _hub_all_members(self, event: AstrMessageEvent, gid: str,
                                uid: str, bid: str) -> List[str]:
        excluded = set(self._cfg["hub_excluded"])
        excluded.update([uid, "0"])
        if not self._cfg.get("allow_marry_bot"):
            excluded.add(bid)
        cached = self._hub_members_cache.get(gid)
        if cached and time.time() - cached[1] < 300:
            return [u for u in cached[0] if u not in excluded]
        pool: List[str] = []
        try:
            platform = event.get_platform_name()
            if platform == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import \
                    AiocqhttpMessageEvent
                if not isinstance(event, AiocqhttpMessageEvent):
                    self._dbg("非 aiocqhttp 事件类型，回退活跃池")
                    return pool
                resp = await event.bot.api.call_action(
                    "get_group_member_list", group_id=int(gid))
                # 兼容两种响应格式：直接列表 或 {"data": [...]}
                if isinstance(resp, dict) and "data" in resp and isinstance(resp["data"], list):
                    members = resp["data"]
                elif isinstance(resp, list):
                    members = resp
                else:
                    members = []
                new_members: Dict[str, Dict] = {}
                for m in members:
                    muid = str(m.get("user_id", ""))
                    if not muid or muid in excluded:
                        continue
                    pool.append(muid)
                    if muid not in self._hub_active.get(gid, {}):
                        new_members[muid] = {
                            "name": m.get("card") or m.get("nickname") or f"群友({muid})",
                            "ts": 0,
                        }
                # 批量加锁写入 _hub_active，使用独立锁避免与消息处理竞争
                if pool:
                    async with self._hub_active_lock:
                        active = self._hub_active.setdefault(gid, {})
                        for muid, info in new_members.items():
                            if muid not in active:
                                active[muid] = info
                    self._hub_members_cache[gid] = (pool, time.time())
            else:
                self._dbg(f"非 aiocqhttp 平台 ({platform})，无法获取群成员列表，回退活跃池")
        except Exception as e:
            self._log(logging.ERROR, f"获取群成员列表失败: {e}")
        return pool

    async def _hub_resolve_pool(self, event: AstrMessageEvent, gid: str,
                                 uid: str, bid: str) -> List[str]:
        require_active = self._cfg.get("hub_require_active", True)
        if require_active:
            return self._hub_active_pool(gid, uid, bid)
        pool = await self._hub_all_members(event, gid, uid, bid)
        if not pool:
            self._log(logging.WARNING, f"全员池获取失败，回退到活跃池 (gid={gid})")
            pool = self._hub_active_pool(gid, uid, bid)
        return pool

    def _hub_weighted_choice(self, gid: str, pool: List[str]) -> str:
        """加权随机抽取：近期被抽过的人概率降低，随时间自然恢复。
        
        权重公式: weight = max(0.05, min(1.0, days_since_drawn / decay_days))
        - 从未被抽过: weight = 1.0（满权重）
        - 今天被抽过: weight = 0.05（1/20 概率，仍可能被抽到）
        - 衰减天数后: weight = 1.0（完全恢复）
        """
        decay_days = self._cfg.get("hub_draw_decay_days", 7)
        decay_seconds = decay_days * 86400
        now = time.time()
        recent = self._hub_drawn_recent.get(gid, {})

        weights = []
        for uid in pool:
            last = recent.get(uid, 0)
            if last <= 0:
                weights.append(1.0)
            else:
                elapsed = now - last
                w = max(0.05, min(1.0, elapsed / decay_seconds))
                weights.append(w)

        # random.choices 内部使用 random() 而非 secrets，但权重引入的熵已足够
        return random.choices(pool, weights=weights, k=1)[0]

    async def _cmd_husband_draw(self, event: AstrMessageEvent, mode: str = "husband") -> None:
        gid = await self._hub_guard(event, mode)
        if not gid: return
        uid = str(event.get_sender_id())
        bid = str(getattr(event.message_obj, 'self_id', ''))

        daily = self._cfg["hub_daily"]
        # 预检查：用 _hub_today 只读快照，避免锁外调用 _hub_init_today 导致引用悬空
        pre_recs = self._hub_today(gid)
        user_recs = [r for r in pre_recs
                     if r["user_id"] == uid and r.get("source") in ("draw", "mutual")]

        if len(user_recs) >= daily:
            _, tpl, hid = self._already_msg(user_recs, daily, mode, event.get_sender_name() or uid, uid)
            chains: List[Any] = []
            if self._cfg.get("at_waifu"): chains.append(At(qq=hid))
            chains.append(Plain(f" {tpl}"))
            chains.append(Image.fromURL(f"https://q4.qlogo.cn/headimg_dl?dst_uin={hid}&spec=640"))
            await event.send(event.chain_result(chains))
            return

        pool = await self._hub_resolve_pool(event, gid, uid, bid)
        if not pool:
            await event.send(event.plain_result(self._hb("draw_empty", mode)))
            return

        husband_id = self._hub_weighted_choice(gid, pool)
        self._dbg(f"抽取池大小={len(pool)}, 抽中={husband_id}")
        husband_name = self._hub_active.get(gid, {}).get(husband_id, {}).get("name", f"用户({husband_id})")
        avatar_url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={husband_id}&spec=640"

        async with self.lock:
            # 在锁内获取 today_recs，确保引用不被 _sync_config 替换导致写入丢失
            today_recs = self._hub_init_today(gid)
            # double-check：防止并发抽取超过每日限制
            user_recs = [r for r in today_recs
                         if r["user_id"] == uid and r.get("source") in ("draw", "mutual")]
            if len(user_recs) >= daily:
                _, tpl2, hid2 = self._already_msg(user_recs, daily, mode, event.get_sender_name() or uid, uid)
                already_msg = (tpl2, hid2)
            else:
                remain = max(0, daily - len(user_recs) - 1)
                already_msg = None
                today_recs.append({
                    "user_id": uid, "user_name": event.get_sender_name() or uid,
                    "husband_id": husband_id, "husband_name": husband_name,
                    "ts": time.time(), "source": "draw",
                })
                # 概率衰减：记录被抽时间，后续抽取时降低权重
                self._hub_drawn_recent.setdefault(gid, {})[husband_id] = time.time()
                if self._cfg.get("auto_set_other_half"):
                    other_recs = [r for r in today_recs
                                  if r["user_id"] == husband_id and r.get("source") in ("draw", "mutual")]
                    if len(other_recs) < daily:
                        today_recs.append({
                            "user_id": husband_id, "user_name": husband_name,
                            "husband_id": uid, "husband_name": event.get_sender_name() or uid,
                            "ts": time.time(), "source": "mutual",
                        })
        self._data_dirty = True
        if already_msg:
            tpl2, hid2 = already_msg
            chains2: List[Any] = []
            if self._cfg.get("at_waifu"): chains2.append(At(qq=hid2))
            chains2.append(Plain(f" {tpl2}"))
            chains2.append(Image.fromURL(f"https://q4.qlogo.cn/headimg_dl?dst_uin={hid2}&spec=640"))
            await event.send(event.chain_result(chains2))
            return

        tpl = self._hb("draw_result", mode).format(
            user=event.get_sender_name() or uid, husband=husband_name,
            suffix=self._hb("draw_suffix", mode).format(remain=remain))

        chains: List[Any] = []
        if self._cfg.get("at_waifu"):
            chains.append(At(qq=husband_id))
        chains.append(Plain(f" {tpl}"))
        chains.append(Image.fromURL(avatar_url))
        result = await event.send(event.chain_result(chains))

        # auto_withdraw
        if self._cfg.get("auto_withdraw_enabled") and result:
            delay = self._cfg.get("auto_withdraw_delay_seconds", 30)
            _ = asyncio.create_task(self._auto_withdraw(event, result, delay))

    async def _auto_withdraw(self, event: AstrMessageEvent, result, delay: float) -> None:
        """自动撤回抽取结果消息"""
        try:
            await asyncio.sleep(delay)
            message_id = None
            if isinstance(result, dict) and 'message_id' in result:
                message_id = result['message_id']
            elif hasattr(result, 'message_id'):
                message_id = result.message_id
            if message_id is not None:
                try:
                    await event.bot.api.call_action('delete_msg', message_id=message_id)
                except Exception as e:
                    self._dbg(f"自动撤回失败: {e}")
        except Exception as e:
            self._dbg(f"自动撤回异常: {e}")

    async def _cmd_wife_draw(self, event: AstrMessageEvent) -> None:
        await self._cmd_husband_draw(event, mode="wife")

    async def _cmd_husband_my(self, event: AstrMessageEvent, mode: str = "husband") -> None:
        gid = await self._hub_guard(event, mode)
        if not gid: return
        uid = str(event.get_sender_id())
        recs = self._hub_today(gid)
        mine = [r for r in recs if r["user_id"] == uid]
        # 仅统计 draw/mutual 来源用于剩余次数，force/propose 不计入抽取次数
        mine_draw = [r for r in mine if r.get("source") in ("draw", "mutual")]
        daily = self._cfg["hub_daily"]
        if not mine:
            await event.send(event.plain_result(
                self._hb("my_empty", mode).format(
                    user=event.get_sender_name() or uid, remain=daily)))
            return
        lines = []
        for i, r in enumerate(mine, 1):
            src = r.get("source", "draw")
            if src == "propose":
                tag = self._hb("my_tag_propose", mode)
            elif src == "force":
                tag = self._hb("my_tag_force", mode)
            else:
                tag = self._hb("my_tag_draw", mode)
            lines.append(f"  {i}. 【{r['husband_name']}】 {tag}")
        chains: List[Any] = [
            Plain(self._hb("my_header", mode) + "\n" + "\n".join(lines) +
                  f"\n🎫 剩余次数 {max(0, daily - len(mine_draw))} 次"),
        ]
        await event.send(event.chain_result(chains))

    async def _cmd_wife_my(self, event: AstrMessageEvent) -> None:
        await self._cmd_husband_my(event, mode="wife")

    async def _cmd_husband_force(self, event: AstrMessageEvent, mode: str = "husband") -> None:
        gid = await self._hub_guard(event, mode)
        if not gid: return
        uid = str(event.get_sender_id())
        chain = getattr(event.message_obj, 'message', [])

        target_id = None
        for c in chain:
            if isinstance(c, At):
                qq = getattr(c, 'qq', None)
                if qq: target_id = str(qq); break
        if not target_id:
            await event.send(event.plain_result(self._hb("force_no_target", mode))); return
        if target_id == uid:
            await event.send(event.plain_result(self._hb("force_self", mode))); return

        force_daily = self._cfg.get("hub_force_daily", 1)
        force_cd = self._cfg["hub_force_cd"]
        now = time.time()

        bot_id = str(getattr(event.message_obj, 'self_id', ''))
        if target_id == bot_id and not self._cfg.get("allow_marry_bot"):
            await event.send(event.plain_result(f"🤖 机器人不参与强娶{self._hb_label(mode)}哦~")); return
        pool = await self._hub_resolve_pool(event, gid, uid, bot_id)
        if target_id not in pool:
            await event.send(event.plain_result(self._hb("force_not_active", mode)))
            return

        target_name = self._hub_active.get(gid, {}).get(target_id, {}).get("name", f"用户({target_id})")
        user_name = event.get_sender_name() or uid
        avatar_url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={target_id}&spec=640"

        async with self.lock:
            # 在锁内获取 today_recs，确保引用不被 _sync_config 替换导致写入丢失
            today_recs = self._hub_init_today(gid)
            # double-check：防止并发强娶超过每日限制 + CD 绕过
            lock_msg = None
            last_force2 = self._hub_force_cd.get(uid, 0)
            if now - last_force2 < force_cd * 86400:
                remain = force_cd * 86400 - (now - last_force2)
                d = int(remain // 86400); h = int((remain % 86400) // 3600)
                lock_msg = self._hb("force_cd", mode).format(d=d, h=h, cd=force_cd)
            elif force_daily > 0:
                today_force = sum(1 for r in today_recs
                                  if r.get("user_id") == uid and r.get("source") == "force")
                if today_force >= force_daily:
                    lock_msg = f"⏰ 你今天已经强娶了 {today_force} 次，明天再来吧！(每日上限: {force_daily} 次)"
            if lock_msg is None:
                self._hub_force_cd[uid] = now
                today_recs.append({
                    "user_id": uid, "user_name": user_name,
                    "husband_id": target_id, "husband_name": target_name,
                    "ts": now, "source": "force",
                })
                self._hub_rbq_incr(gid, target_id)
                self._data_dirty = True
        if lock_msg:
            await event.send(event.plain_result(lock_msg))
            return

        await event.send(event.chain_result([
            At(qq=uid),
            Plain(f" {self._hb('force_ok', mode).format(user=user_name, target=target_name, cd=force_cd)}"),
            Image.fromURL(avatar_url),
        ]))

    async def _cmd_wife_force(self, event: AstrMessageEvent) -> None:
        await self._cmd_husband_force(event, mode="wife")

    async def _cmd_husband_rank(self, event: AstrMessageEvent, mode: str = "husband") -> None:
        gid = await self._hub_guard(event, mode)
        if not gid: return
        rbq = self._hub_rbq.get(gid, {})
        if not rbq:
            label = self._hb_label(mode)
            await event.send(event.plain_result(
                self._hb("rank_title", mode) + "\n" +
                self._hb("rank_empty", mode) + "\n" +
                f">> /{label}帮助 查看所有指令"))
            return
        sorted_r = sorted(rbq.items(), key=lambda x: -x[1])
        label = self._hb_label(mode)
        lines = [
            self._hb("rank_title", mode),
        ]
        for i, (uid, cnt) in enumerate(sorted_r[:10]):
            name = self._hub_active.get(gid, {}).get(uid, {}).get("name", uid[:10])
            medals = ["🥇", "🥈", "🥉"]
            pf = medals[i] if i < 3 else f"  {i+1:>2}."
            bar = "█" * min(cnt, 15)
            lines.append(f"  {pf} {name}  {cnt}次  {bar}")
        lines.append("📌 被强娶次数越多越受欢迎！")
        lines.append(f">> /{label}帮助 查看所有指令")
        await event.send(event.plain_result("\n".join(lines)))

    async def _cmd_wife_rank(self, event: AstrMessageEvent) -> None:
        await self._cmd_husband_rank(event, mode="wife")

    async def _cmd_husband_help(self, event: AstrMessageEvent, mode: str = "husband") -> None:
        await self._hub_sync()
        hus, wife = self._hub_enabled()
        # 如果请求的模式关闭但另一个模式开启，fallback 到另一个模式
        if mode == "husband" and not hus:
            if wife:
                mode = "wife"
            else:
                await event.send(event.plain_result("❌ 老公模式未开启，请在管理面板中启用「开启老公模式」。")); return
        if mode == "wife" and not wife:
            if hus:
                mode = "husband"
            else:
                await event.send(event.plain_result("❌ 老婆模式未开启，请在管理面板中启用「开启老婆模式」。")); return
        active_status = "✅ 已关闭（全群可抽）" if not self._cfg.get("hub_require_active", True) else "默认开启（仅活跃成员）"
        label = self._hb_label(mode)
        force_label = self._hb_label(mode, "强娶老公", "强娶老婆")
        mode_str = "老公+老婆" if (hus and wife) else ("老公" if hus else "老婆")
        # 缩写仅在老婆模式下有意义（jrlp/wdlp/qiangqu 路由到老婆 handler）
        abbr_lines = ""
        if mode == "wife":
            abbr_lines = ("\n  /jrlp              抽取（英文缩写）\n"
                          "  /wdlp              我的记录（英文缩写）\n"
                          "  /qiangqu           强娶（英文缩写）")
        await event.send(event.plain_result(
            self._hb("help_intro", mode) + "\n" +
            f"  /今日{label} /抽{label}   随机抽取今日{label}\n" +
            f"  /我的{label} /{label}记录 查看今日抽取记录\n" +
            f"  /{force_label} @用户    强制与指定用户建立羁绊\n" +
            f"  /{label}排行榜 /{label}排行 被强娶次数排行\n" +
            f"  /不限制成员抽取     切换全群抽取/仅活跃\n" +
            f"  /{label}帮助          查看此帮助\n" +
            f"  /关系图 /gxt /羁绊图谱 生成羁绊关系图（含头像+统计）\n" +
            f"  /求婚 @用户 /qh     向指定用户求婚\n" +
            f"  /重置记录 /czjl     管理员重置记录\n" +
            f"  /重置强娶时间 /czqqsj 管理员重置强娶CD\n" +
            abbr_lines +
            "\n" +
            "  > 当前模式：" + mode_str + "\n" +
            "  > 活跃限制：" + active_status + "\n" +
            "  > 每天可抽次数由管理员设定，强娶有冷却期。\n" +
            "  > 开启关键词触发后，可直接发关键词无需 / 前缀。"))

    async def _cmd_wife_help(self, event: AstrMessageEvent) -> None:
        await self._cmd_husband_help(event, mode="wife")

    async def _cmd_husband_toggle_active(self, event: AstrMessageEvent) -> None:
        gid = self._gid(event)
        if not gid: await event.send(event.plain_result("⚠️ 此功能仅在群聊中可用。")); return
        await self._hub_sync()
        hus, wife = self._hub_enabled()
        if not hus and not wife:
            await event.send(event.plain_result("❌ 抽老公/老婆功能未开启，请在管理面板中启用。"))
            return
        if not await self._check_admin(event, gid):
            await event.send(event.plain_result("⛔ 仅群主/管理员可切换抽取模式。"))
            return
        async with self.lock:
            cur = self._cfg.get("hub_require_active", True)
            new_val = not cur
            self._cfg["hub_require_active"] = new_val
            # 同步到持久化配置（兼容 AstrBotConfig 的 setitem 和 setattr）
            try:
                self.config["husband_require_active"] = new_val
            except TypeError:
                try:
                    setattr(self.config, "husband_require_active", new_val)
                except Exception:
                    self._log(logging.WARNING, "无法持久化 husband_require_active 配置变更")
            try:
                if hasattr(self.config, 'save'):
                    self.config.save()
            except Exception as e:
                self._log(logging.ERROR, f"保存配置失败: {e}")
            # 强制下次 _sync_config 重新读取配置
            self._cfg_sync_ts = 0.0
        self._hub_members_cache.pop(gid, None)
        tag = "✅ 全群抽取模式已开启！\n现在抽人会覆盖所有群成员（包括潜水党）"
        if new_val: tag = "🔒 仅活跃成员模式已开启！\n只有最近发言的群友能进入抽取池"
        await event.send(event.plain_result(tag +
            f"\n>> 快捷切换：/不限制成员抽取\n>> 永久设置：WebUI 管理面板"))

    # ============================================================
    # 关系图 (Vis.js HTML 渲染，基于 wifepicker 方案)
    # ============================================================
    async def _cmd_relation_graph(self, event: AstrMessageEvent) -> None:
        gid = self._gid(event)
        if not gid: await event.send(event.plain_result("⚠️ 此功能仅在群聊中可用。")); return
        await self._hub_sync()
        hus, wife = self._hub_enabled()
        if not hus and not wife:
            await event.send(event.plain_result("❌ 抽老公/老婆功能未开启，请在管理面板中启用。"))
            return

        recs = self._hub_today(gid)
        if not recs:
            await event.send(event.plain_result("\U0001F4CA 今日暂无羁绊记录，无法生成关系图。"))
            return

        # 发送提示，让用户知道正在处理
        tip = await event.send(event.plain_result("🔍 正在生成关系图，请稍候..."))

        # 读取模板
        tpl = os.path.join(self.curr_dir, "template", "relation_graph.html")
        if not os.path.exists(tpl):
            await event.send(event.plain_result("❌ 关系图模板文件缺失，请重新安装插件。"))
            return
        with open(tpl, "r", encoding="utf-8") as f:
            html = f.read()

        # 构建 data 记录
        records = []
        node_roles: Dict[str, Set[str]] = {}
        for r in recs:
            records.append({
                "user_id": r["user_id"],
                "user_name": r.get("user_name", f"用户({r['user_id']})"),
                "husband_id": r["husband_id"],
                "husband_name": r.get("husband_name", f"用户({r['husband_id']})"),
                "source": r.get("source", "draw"),
            })
            uid, hid = r["user_id"], r["husband_id"]
            if uid not in node_roles: node_roles[uid] = set()
            if hid not in node_roles: node_roles[hid] = set()
            node_roles[uid].add("drawer")
            node_roles[hid].add("drawn")

        role_map: Dict[str, str] = {}
        for uid, roles in node_roles.items():
            if "drawer" in roles and "drawn" in roles:
                role_map[uid] = "both"
            elif "drawer" in roles:
                role_map[uid] = "drawer"
            else:
                role_map[uid] = "drawn"

        draw_count = sum(1 for r in recs if r.get("source") == "draw")
        force_count = sum(1 for r in recs if r.get("source") == "force")
        mutual_count = sum(1 for r in recs if r.get("source") == "mutual")
        propose_count = sum(1 for r in recs if r.get("source") == "propose")
        node_count = len(role_map)

        # 并行获取群名和成员名映射
        group_name = "未命名群聊"
        user_map: Dict[str, str] = {}
        try:
            if event.get_platform_name() == "aiocqhttp":
                async def _fetch_group_info():
                    info = await event.bot.api.call_action("get_group_info", group_id=int(gid))
                    if isinstance(info, dict):
                        info = info.get("data", info)
                    return info.get("group_name", "未命名群聊")

                async def _fetch_members():
                    um: Dict[str, str] = {}
                    members = await event.bot.api.call_action("get_group_member_list", group_id=int(gid))
                    if isinstance(members, dict):
                        members = members.get("data", members)
                    if isinstance(members, list):
                        for m in members:
                            mid = str(m.get("user_id"))
                            um[mid] = m.get("card") or m.get("nickname") or mid
                    return um

                group_name, user_map = await asyncio.gather(
                    _fetch_group_info(), _fetch_members()
                )
        except Exception:
            pass

        title = f"{group_name} 羁绊关系图"
        iter_count = self._cfg.get("hub_iterations", 100)

        # 渲染：重试最多 2 次，降低 scale 加速
        last_err = ""
        for attempt in range(2):
            try:
                url = await self.html_render(
                    html,
                    {
                        "title": title,
                        "records": records,
                        "user_map": user_map,
                        "node_roles": role_map,
                        "node_count": node_count,
                        "edge_count": len(recs),
                        "draw_count": draw_count,
                        "force_count": force_count,
                        "mutual_count": mutual_count,
                        "propose_count": propose_count,
                        "iterations": iter_count,
                    },
                    options={
                        "type": "png",
                        "quality": None,
                        "scale": "device",
                        "clip": {"x": 0, "y": 0, "width": 1600, "height": 900},
                        "full_page": False,
                        "device_scale_factor_level": "high",
                    },
                )
                await event.send(event.image_result(url))
                return
            except Exception as e:
                last_err = str(e)
                if attempt == 0:
                    self._log(logging.WARNING, f"关系图第1次渲染失败，重试中: {last_err}")
                    await asyncio.sleep(1)
                else:
                    self._log(logging.ERROR, f"关系图渲染失败(2次): {last_err}")

        await event.send(event.plain_result(
            f"❌ 关系图生成失败，请稍后重试。\n"
            f"💡 如持续失败，请检查 Playwright 环境是否正常。"
        ))

    # ============================================================
    # 求婚系统
    # ============================================================
    async def _cmd_propose(self, event: AstrMessageEvent) -> None:
        gid = self._gid(event)
        if not gid: await event.send(event.plain_result("⚠️ 此功能仅在群聊中可用。")); return
        await self._hub_sync()
        hus, wife = self._hub_enabled()
        if not hus and not wife:
            await event.send(event.plain_result("❌ 抽老公/老婆功能未开启，请在管理面板中启用。"))
            return
        uid = str(event.get_sender_id())
        chain = getattr(event.message_obj, 'message', [])

        target_id = None
        for c in chain:
            if isinstance(c, At):
                qq = getattr(c, 'qq', None)
                if qq: target_id = str(qq); break
        if not target_id:
            await event.send(event.plain_result("💍 请 @ 你想要求婚的对象！\n格式：/求婚 @用户"))
            return
        if target_id == uid:
            await event.send(event.plain_result("🤔 你不能向自己求婚哦！"))
            return
        bot_id = str(getattr(event.message_obj, 'self_id', ''))
        if target_id == bot_id and not self._cfg.get("allow_marry_bot"):
            await event.send(event.plain_result("🤖 不能向机器人求婚哦~"))
            return

        now_ts = time.time()
        propose_cd = self._cfg.get("hub_propose_cd", 86400)
        propose_daily = self._cfg.get("hub_propose_daily", 3)

        target_name = self._hub_active.get(gid, {}).get(target_id, {}).get("name", f"用户({target_id})")
        user_name = event.get_sender_name() or uid
        propose_mode = "wife" if wife else "husband"
        label = self._hb_label(propose_mode)

        async with self.lock:
            # double-check：防止并发求婚超过每日限制 + CD 绕过
            lock_msg = None
            if propose_cd > 0:
                last_p2 = self._hub_propose_cd.get(uid, 0)
                if now_ts - last_p2 < propose_cd:
                    lock_msg = f"⏰ 你的求婚冷却中，{int(propose_cd - (now_ts - last_p2))} 秒后可再次发起求婚。"
            if lock_msg is None and propose_daily > 0:
                count = self._hub_propose_count.get(uid, 0)
                if count >= propose_daily:
                    lock_msg = f"⏰ 你今天已经求婚了 {count} 次，明天再来吧！(每日上限: {propose_daily} 次)"
            if lock_msg is None:
                if propose_cd > 0:
                    self._hub_propose_cd[uid] = now_ts
                self._hub_propose_count[uid] = self._hub_propose_count.get(uid, 0) + 1
                self._proposals[gid] = {
                    "from": uid, "from_name": user_name,
                    "to": target_id, "to_name": target_name,
                    "ts": now_ts,
                }
        if lock_msg:
            await event.send(event.plain_result(lock_msg))
            return
        await event.send(event.chain_result([
            At(qq=target_id),
            Plain(f"\n💍 {user_name} 向你求婚了！\n\n"
                  f"「从今天起，你就是我的{label}了！」\n\n"
                  f">> 对方回复 /接受求婚 或 /拒绝求婚 来回应"),
        ]))

    @filter.command("接受求婚")
    async def on_accept_proposal(self, e: AstrMessageEvent) -> None:
        gid = self._gid(e)
        if not gid: await e.send(e.plain_result("⚠️ 此功能仅在群聊中可用。")); return
        await self._hub_sync()
        hus, wife = self._hub_enabled()
        if not hus and not wife:
            await e.send(e.plain_result("❌ 抽老公/老婆功能未开启，请在管理面板中启用。"))
            return
        uid = str(e.get_sender_id())

        # 在锁内读取 proposal 并做原子操作，防止并发覆盖
        async with self.lock:
            proposal = self._proposals.get(gid)
            if not proposal or proposal["to"] != uid:
                await e.send(e.plain_result("💍 你当前没有待处理的求婚请求。"))
                return
            if time.time() - proposal["ts"] > 300:
                from_uid = proposal["from"]
                self._hub_propose_count[from_uid] = max(0, self._hub_propose_count.get(from_uid, 1) - 1)
                self._hub_propose_cd.pop(from_uid, None)
                self._proposals.pop(gid, None)
                await e.send(e.plain_result("⏰ 求婚请求已过期（5分钟），请重新发起。\n💡 求婚次数已返还~"))
                return

            propose_mode = "wife" if wife else "husband"
            label = self._hb_label(propose_mode)
            now = time.time()
            self._hub_init_today(gid).append({
                "user_id": proposal["from"], "user_name": proposal["from_name"],
                "husband_id": proposal["to"], "husband_name": proposal["to_name"],
                "ts": now, "source": "propose",
            })
            self._hub_rbq_incr(gid, proposal["to"])
            self._proposals.pop(gid, None)
            self._data_dirty = True
            # 保存 proposal 数据供锁外发送消息使用
            from_name = proposal["from_name"]
            to_name = proposal["to_name"]

        await e.send(e.plain_result(
            f"💒 恭喜！{from_name} 和 {to_name} 喜结连理！\n"
            f"从今天起，{to_name} 就是 {from_name} 的{label}了！🎉"))

    async def _cmd_accept_proposal(self, event: AstrMessageEvent) -> None:
        await self.on_accept_proposal(event)

    @filter.command("拒绝求婚")
    async def on_reject_proposal(self, e: AstrMessageEvent) -> None:
        gid = self._gid(e)
        if not gid: await e.send(e.plain_result("⚠️ 此功能仅在群聊中可用。")); return
        uid = str(e.get_sender_id())

        async with self.lock:
            proposal = self._proposals.get(gid)
            if not proposal or proposal["to"] != uid:
                await e.send(e.plain_result("💍 你当前没有待处理的求婚请求。"))
                return
            # 返还求婚次数和冷却
            from_uid = proposal["from"]
            self._hub_propose_count[from_uid] = max(0, self._hub_propose_count.get(from_uid, 1) - 1)
            self._hub_propose_cd.pop(from_uid, None)
            self._proposals.pop(gid, None)
            self._data_dirty = True
            from_name = proposal["from_name"]

        await e.send(e.plain_result(f"💔 {from_name} 的求婚被拒绝了...\n💡 求婚次数已返还，可以重新求婚~"))

    async def _cmd_reject_proposal(self, event: AstrMessageEvent) -> None:
        await self.on_reject_proposal(event)

    # ============================================================
    # 管理员重置命令
    # ============================================================
    async def _cmd_reset_records(self, event: AstrMessageEvent) -> None:
        gid = self._gid(event)
        if not gid: await event.send(event.plain_result("⚠️ 此功能仅在群聊中可用。")); return
        if not await self._check_admin(event, gid):
            await event.send(event.plain_result("⛔ 仅群主/管理员可执行此操作。"))
            return
        await self._hub_sync()
        async with self.lock:
            if gid in self._hub_records:
                self._hub_records.pop(gid, None)
            if gid in self._hub_rbq:
                self._hub_rbq.pop(gid, None)
            self._hub_drawn_recent.pop(gid, None)  # 同时重置轮换去重池
        self._save_persisted_data()
        await event.send(event.plain_result("✅ 本群抽取记录和排行榜已重置！"))

    async def _cmd_reset_force_cd(self, event: AstrMessageEvent) -> None:
        uid = str(event.get_sender_id())
        chain = getattr(event.message_obj, 'message', [])

        # 支持 @ 他人来重置对方的强娶冷却（需管理员权限）
        target_uid = None
        target_name = None
        for c in chain:
            if isinstance(c, At):
                qq = getattr(c, 'qq', None)
                if qq: target_uid = str(qq); break
        if target_uid and target_uid != uid:
            gid = self._gid(event)
            if not gid: await event.send(event.plain_result("⚠️ 此功能仅在群聊中可用。")); return
            if not await self._check_admin(event, gid):
                await event.send(event.plain_result("⛔ 仅群主/管理员可重置他人的强娶冷却。\n💡 你可以重置自己的强娶冷却（无需 @ 他人）。"))
                return
            if target_uid in self._hub_force_cd:
                target_name = self._hub_active.get(
                    gid, {}).get(target_uid, {}).get("name", target_uid)
                async with self.lock:
                    self._hub_force_cd.pop(target_uid, None)
                self._save_persisted_data()
                await event.send(event.plain_result(
                    f"✅ 已重置 {target_name} 的强娶冷却时间！"))
            else:
                await event.send(event.plain_result(
                    f"ℹ️ {target_name or target_uid} 当前没有强娶冷却记录，无需重置。"))
            return

        if uid in self._hub_force_cd:
            async with self.lock:
                self._hub_force_cd.pop(uid, None)
            self._save_persisted_data()
            await event.send(event.plain_result("✅ 你的强娶冷却时间已重置！"))
        else:
            await event.send(event.plain_result("ℹ️ 你当前没有强娶冷却记录，无需重置。"))

    # ============================================================
    # 指令注册 - 抽老公/老婆（双模式指令同步注册）
    # ============================================================
    @filter.command("今日老公", alias={"抽老公"})
    async def on_husband_draw(self, e: AstrMessageEvent) -> None:
        await self._cmd_husband_draw(e)

    @filter.command("今日老婆", alias={"抽老婆", "jrlp"})
    async def on_wife_draw(self, e: AstrMessageEvent) -> None:
        await self._cmd_wife_draw(e)

    @filter.command("我的老公", alias={"老公记录"})
    async def on_husband_my(self, e: AstrMessageEvent) -> None:
        await self._cmd_husband_my(e)

    @filter.command("我的老婆", alias={"老婆记录", "wdlp"})
    async def on_wife_my(self, e: AstrMessageEvent) -> None:
        await self._cmd_wife_my(e)

    @filter.command("强娶老公")
    async def on_husband_force(self, e: AstrMessageEvent) -> None:
        await self._cmd_husband_force(e)

    @filter.command("强娶老婆", alias={"qiangqu"})
    async def on_wife_force(self, e: AstrMessageEvent) -> None:
        await self._cmd_wife_force(e)

    @filter.command("强娶")
    async def on_force_default(self, e: AstrMessageEvent) -> None:
        hus, wife = self._hub_enabled()
        if hus and not wife:
            await self._cmd_husband_force(e)
        else:
            await self._cmd_wife_force(e)

    @filter.command("老公排行榜", alias={"老公排行"})
    async def on_husband_rank(self, e: AstrMessageEvent) -> None:
        await self._cmd_husband_rank(e)

    @filter.command("老婆排行榜", alias={"老婆排行"})
    async def on_wife_rank(self, e: AstrMessageEvent) -> None:
        await self._cmd_wife_rank(e)

    @filter.command("老公帮助")
    async def on_husband_help(self, e: AstrMessageEvent) -> None:
        await self._cmd_husband_help(e)

    @filter.command("老婆帮助")
    async def on_wife_help(self, e: AstrMessageEvent) -> None:
        await self._cmd_wife_help(e)

    @filter.command("不限制成员抽取")
    async def on_husband_toggle(self, e: AstrMessageEvent) -> None:
        await self._cmd_husband_toggle_active(e)

    @filter.command("关系图", alias={"gxt", "羁绊图谱"})
    async def on_relation_graph(self, e: AstrMessageEvent) -> None:
        await self._cmd_relation_graph(e)

    @filter.command("求婚", alias={"qh"})
    async def on_propose(self, e: AstrMessageEvent) -> None:
        await self._cmd_propose(e)

    @filter.command("重置记录", alias={"czjl"})
    async def on_reset_records(self, e: AstrMessageEvent) -> None:
        await self._cmd_reset_records(e)

    @filter.command("重置强娶时间", alias={"czqqsj"})
    async def on_reset_force_cd(self, e: AstrMessageEvent) -> None:
        await self._cmd_reset_force_cd(e)

    # ============================================================
    # 统计 / 帮助
    # ============================================================
    async def _stats(self, event: AstrMessageEvent, gid: str) -> None:
        tr = self.trigger_times.get(gid, [])
        ev = self.group_events.get(gid, [])
        d0 = self._ts_min("day"); w0 = self._ts_min("week")
        cd = self._get_cd(gid)
        await event.send(event.plain_result(
            f"\U0001F4CA 本群复读统计\n{'─'*30}\n"
            f"  今日触发  {len([t for t in tr if t >= d0]):>4} 次\n"
            f"  本周触发  {len([t for t in tr if t >= w0]):>4} 次\n"
            f"  累计触发  {len(tr):>4} 次\n"
            f"  累计贡献  {len(ev):>4} 人次\n"
            f"  当前冷却  {cd:>4.0f}s\n"
            f"{'─'*30}\n>> /复读排行榜 查看排行\n>> /复读状态 查看冷却进度"))

    async def _help(self, event: AstrMessageEvent) -> None:
        rl = "\n".join(f"  /{cmd:<12} {self._win_label(mode)}" for cmd, mode in self._RANK_MAP.items())
        hus, wife = self._hub_enabled()
        if hus or wife:
            both = hus and wife
            label = "老公/老婆" if both else ("老公" if hus else "老婆")
            main = "老公" if hus else "老婆"
            abbr = "  /jrlp /wdlp /qiangqu 老婆模式英文缩写\n" if wife else ""
            dual_note = " — 将 /老公 替换为 /老婆 即可切换模式\n" if both else "\n"
            hub_section = (
                f"💕 抽{label}（仅群聊）{dual_note}"
                f"  /今日{main} /抽{main}   随机抽取今日{main}\n"
                f"  /我的{main} /{main}记录  查看今日记录\n"
                f"  /强娶{main} @用户    强行娶某人为{main}\n"
                f"  /{main}排行 /{main}排行榜 被强娶排行\n"
                f"  /不限制成员抽取     切换全群抽取模式\n"
                f"  /{main}帮助          抽{main}帮助\n"
                f"  /关系图 /gxt       生成羁绊关系图（含头像+统计）\n"
                f"  /求婚 @用户 /qh    向指定用户求婚\n"
                f"  /重置记录 /czjl    管理员重置记录\n"
                f"  /重置强娶时间 /czqqsj 重置强娶冷却\n{abbr}"
            )
        else:
            hub_section = "💕 抽老公/老婆功能未开启，请在管理面板中启用。\n"
        await event.send(event.plain_result(
            f"\U0001F4DF 复读插件 v2.0.5 指令帮助\n{'─'*30}\n"
            f"🔧 管理（仅群聊）\n"
            "  /复读开启          在本群开启复读\n"
            "  /复读关闭          在本群关闭复读\n"
            "  /复读状态          冷却进度+今日统计\n"
            "  /复读统计          本群今日/本周/累计\n"
            f"{'─'*30}\n"
            f"🏆 排行榜（仅群聊）\n{rl}\n{'─'*30}\n{hub_section}"
            f"{'─'*30}\n"
            f"🔥 v2.0.5: 概率衰减加权 / Vis.js CDN / 性能优化\n"
            f"⚙️ 更多参数请在 WebUI 管理面板调整"))

    # ============================================================
    # 消息流水线 — 热路径，零 config.get() 调用
    # ============================================================
    async def _pipe(self, event: AstrMessageEvent) -> None:
        mo = getattr(event, 'message_obj', None)
        if not mo: return
        gid = str(getattr(mo, 'group_id', ''))
        sid = str(event.get_sender_id())
        bid = str(getattr(mo, 'self_id', ''))
        if not gid or (bid and sid == bid): return

        await self._sync_config()
        cfg = self._cfg

        # 抽老公/老婆活跃追踪 — 独立于复读白名单/黑名单，只要发了消息就记录
        async with self._hub_active_lock:
            self._hub_active.setdefault(gid, {})[sid] = {
                "name": event.get_sender_name() or sid,
                "ts": time.time(),
            }

        # 群组白名单/黑名单检查（仅影响复读功能）
        wl = cfg.get("whitelist_groups", set())
        bl = cfg.get("blacklist_groups", set())
        if wl and gid not in wl:
            return
        if bl and gid in bl:
            return

        if gid in cfg["ignored_groups"] or sid in cfg["ignored_users"]: return
        if gid in self.disabled_groups: return

        effective_cd = self._get_cd(gid)
        now = time.time()
        if now - self.last_repeat_time.get(gid, 0) < effective_cd: return

        chain = getattr(mo, 'message', [])
        sig, txt = self._sig(chain)
        if not sig: return

        stripped = txt.strip() if txt else ""
        # 抽老公/老婆关键词触发（支持 exact/starts_with/contains 三种模式）
        # 检查命令前缀：避免与 @filter.command 双重触发（如 /强娶 在 contains 模式下同时被两个路径命中）
        if cfg.get("hub_keyword") and stripped and not stripped.startswith(COMMAND_PREFIXES):
            kw_mode = cfg.get("keyword_trigger_mode", "exact")
            handler = None
            if kw_mode == "exact":
                handler = self._hub_kw.get(stripped)
            elif kw_mode == "starts_with":
                for kw, h in sorted(self._hub_kw.items(), key=lambda x: -len(x[0])):
                    if stripped.startswith(kw):
                        handler = h; break
            elif kw_mode == "contains":
                for kw, h in sorted(self._hub_kw.items(), key=lambda x: -len(x[0])):
                    if kw in stripped:
                        handler = h; break
            if handler:
                await handler(event)
                return
        if stripped.startswith(COMMAND_PREFIXES) or stripped in COMMAND_KEYWORDS: return
        if not self._pass_len(txt): return
        if txt and cfg["blacklist_re"] and cfg["blacklist_re"].search(txt):
            self._dbg(f"命中黑名单: '{txt[:30]}'"); return

        # 窗口维护
        ws = cfg["window_size"]
        if gid not in self.group_history or self.group_history[gid].maxlen != ws:
            if gid in self.group_history and self.group_history[gid].maxlen != ws:
                self._dbg(f"群 {gid} 窗口: {self.group_history[gid].maxlen}→{ws}")
            self.group_history[gid] = deque(self.group_history.get(gid, []), maxlen=ws)

        hist = self.group_history[gid]
        hist.append((sig, sid, chain, txt, event.get_sender_name() or sid))

        threshold = cfg["threshold"]
        if len(hist) < threshold: return

        wc, lm = self._weighted(hist, sig, txt)
        if wc >= float(threshold) and lm:
            async with self.lock:
                if time.time() - self.last_repeat_time.get(gid, 0) < effective_cd:
                    return
                self.last_repeat_time[gid] = now
            await self._fire(event, gid, chain, int(wc), threshold, sig, txt)

    # ============================================================
    # 复读执行
    # ============================================================
    def _contribs_and_filter(self, gid: str, saved_sig: str, saved_txt: str, sid: str, sname: str
                  ) -> Tuple[List[Tuple[str, str]], List[Any]]:
        """合并贡献者收集 + 窗口清理，一次遍历完成两项工作"""
        contrib: List[Tuple[str, str]] = []
        remaining: List[Any] = []
        seen: Set[str] = set()
        same = self._cfg["allow_same_user"]
        for h in self.group_history[gid]:
            hs, hi, _, ht, hn = h
            if hs == saved_sig or self._similar(saved_sig, saved_txt, hs, ht):
                if same or hi not in seen:
                    contrib.append((hi, sname if hi == sid else hn))
                    if not same: seen.add(hi)
            else:
                remaining.append(h)
        return contrib, remaining

    async def _fire(self, event: AstrMessageEvent, gid: str, chain: List[Any],
                     count: int, threshold: int, saved_sig: str, saved_txt: str) -> None:
        sid = str(event.get_sender_id())
        sname = event.get_sender_name() or sid
        now = time.time()
        cfg = self._cfg

        # 重复抑制：同一签名在抑制窗口内只处理一次（加锁防竞态）
        if cfg["dup_suppress"] > 0:
            async with self.lock:
                ls, lt = self.last_repeated_sig.get(gid, ("", 0))
                if saved_sig == ls and now - lt < cfg["dup_suppress"]:
                    self._dbg(f"群 {gid} 重复抑制: {saved_sig[:30]}")
                    self.group_history[gid] = deque(
                        [h for h in self.group_history[gid]
                         if not self._similar(saved_sig, saved_txt, h[0], h[3])],
                        maxlen=self.group_history[gid].maxlen)
                    return
                self.last_repeated_sig[gid] = (saved_sig, now)

        # 贡献者收集 + 窗口清理（合并为一次遍历）
        contrib, remaining = self._contribs_and_filter(gid, saved_sig, saved_txt, sid, sname)

        async with self.lock:
            self.fast_trigger_count[gid] = self.fast_trigger_count.get(gid, 0) + 1
            if gid not in self.group_events: self.group_events[gid] = []
            for cs, cn in contrib: self.group_events[gid].append({"sid": cs, "name": cn, "ts": now})
            if gid not in self.trigger_times: self.trigger_times[gid] = []
            self.trigger_times[gid].append(now)
            # 窗口清理：用已过滤的剩余条目替换，无需再遍历
            self.group_history[gid] = deque(remaining, maxlen=self.group_history[gid].maxlen)

        self._dbg(f"群 {gid} 触发 (C:{count} T:{threshold} contrib:{len(contrib)})")

        # 真人延迟
        if not cfg["fast_mode"]:
            dc = str(cfg["human_delay"])
            try:
                if "-" in dc: lo, hi = map(float, dc.split("-"))
                else: lo = hi = float(dc)
                if lo > 0 or hi > 0: await asyncio.sleep(random.uniform(lo, hi))
            except (ValueError, TypeError):
                self._dbg(f"human_delay 配置解析失败: '{dc}'，跳过延迟")

        # 分支
        bp = cfg["intr_prob"]
        dp = min(bp + (count - threshold) * INTERRUPT_SCALE_FACTOR, 1.0)
        intensity = max(1, count - threshold + 1)
        if random.random() < dp:
            await self._intr(event, gid, chain, intensity)
        else:
            await self._normal(event, gid, chain)

    # ============================================================
    # 打断执行
    # ============================================================
    async def _intr(self, event: AstrMessageEvent, gid: str, chain: List[Any], intensity: int) -> None:
        cfg = self._cfg
        pool: List[str] = []
        if cfg["intr_shuffle"]: pool.append("原话洗牌")
        if cfg["intr_reverse"]: pool.append("反向复读")
        if cfg["intr_custom"]:  pool.append("自定义话术")
        if cfg["intr_silent"]: pool.append("终止复读")
        if not pool: pool.append("终止复读")

        mode = random.choice(pool)
        st = self.strategies.get(mode)
        if st: await st.execute(event, chain, intensity)
        else: self._dbg(f"打断行为: {mode} (沉默)")

        async with self.lock:
            mul = cfg["intr_cd_mul"]
            penalty = max(0, self._get_cd(gid) * mul)
            self.last_repeat_time[gid] = time.time() + penalty
            self._dbg(f"群 {gid} 打断惩罚: +{self._get_cd(gid) * mul:.0f}s")

    # ============================================================
    # 正常复读
    # ============================================================
    async def _normal(self, event: AstrMessageEvent, gid: str, chain: List[Any]) -> None:
        try: await event.send(event.chain_result(chain))
        except Exception as e:
            self._log(logging.ERROR, f"发送失败: {e}")
            await event.send(event.plain_result("+1"))
