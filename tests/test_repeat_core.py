import asyncio
import importlib.util
import json
import re
import sys
import time
import types
import unittest
from collections import deque
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


class Plain:
    def __init__(self, text="", **kwargs):
        self.text = text
        self.__dict__.update(kwargs)


class Image:
    def __init__(self, file=None, **kwargs):
        self.file = file
        self.url = kwargs.pop("url", "")
        self.path = kwargs.pop("path", "")
        self.__dict__.update(kwargs)

    @staticmethod
    def fromURL(url, **kwargs):
        return Image(file=url, **kwargs)


class Face:
    def __init__(self, id=None, **kwargs):
        self.id = id
        self.__dict__.update(kwargs)


class At:
    def __init__(self, qq=None, **kwargs):
        self.qq = qq
        self.__dict__.update(kwargs)


class DummyFilter:
    class EventMessageType:
        GROUP_MESSAGE = "group"

    @staticmethod
    def command(*args, **kwargs):
        return lambda func: func

    @staticmethod
    def event_message_type(*args, **kwargs):
        return lambda func: func


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    components = types.ModuleType("astrbot.api.message_components")

    class AstrMessageEvent:
        pass

    class Context:
        pass

    class Star:
        def __init__(self, context=None):
            self.context = context

    class AstrBotConfig(dict):
        pass

    event.filter = DummyFilter
    event.AstrMessageEvent = AstrMessageEvent
    star.Context = Context
    star.Star = Star
    components.Plain = Plain
    components.Image = Image
    components.Face = Face
    components.At = At
    api.AstrBotConfig = AstrBotConfig

    sys.modules.update({
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star,
        "astrbot.api.message_components": components,
    })


_install_astrbot_stubs()
MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("repeat_promax_test_module", MODULE_PATH)
PLUGIN_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PLUGIN_MODULE)
RepeatProMaxPlugin = PLUGIN_MODULE.RepeatProMaxPlugin


class FakeEvent:
    def __init__(self, chain, sender="10001", group="20001", raw_message=None):
        self.message_obj = SimpleNamespace(
            group_id=group,
            self_id="99999",
            message=chain,
            raw_message=raw_message,
        )
        self._sender = sender
        self.sent = []

    def get_sender_id(self):
        return self._sender

    def get_sender_name(self):
        return f"user-{self._sender}"

    def get_platform_name(self):
        return "test"

    def is_admin(self):
        return False

    def plain_result(self, text):
        return text

    def chain_result(self, chain):
        return list(chain)

    async def send(self, result):
        self.sent.append(result)
        return result


def make_plugin(**overrides):
    plugin = RepeatProMaxPlugin.__new__(RepeatProMaxPlugin)
    plugin._cfg = {
        "threshold": 3,
        "window_size": 5,
        "fuzzy_threshold": 0.9,
        "enable_weight_decay": False,
        "allow_same_user": True,
        "min_len": 0,
        "max_len": 200,
        "cooldown": 0,
        "cd_escalation": False,
        "dup_suppress": 0,
        "intr_prob": 0,
        "intr_cd_mul": 2,
        "intr_shuffle": True,
        "intr_reverse": True,
        "intr_custom": False,
        "intr_silent": False,
        "human_delay": "0",
        "fast_mode": True,
        "blacklist_re": None,
        "ignored_groups": set(),
        "ignored_users": set(),
        "debug": False,
        "hub_keyword": False,
        "keyword_trigger_mode": "exact",
        "whitelist_groups": set(),
        "blacklist_groups": set(),
        "hub_daily": 10,
        "hub_force_cd": 0,
        "hub_force_daily": 3,
        "hub_propose_daily": 3,
        "hub_propose_cd": 0,
        "hub_active_days": 30,
        "hub_excluded": set(),
        "hub_require_active": False,
        "hub_draw_decay_days": 7,
        "enable_husband": True,
        "enable_wife": True,
        "at_waifu": False,
        "auto_set_other_half": False,
        "allow_marry_bot": False,
        "auto_withdraw_enabled": False,
        "auto_withdraw_delay_seconds": 30,
    }
    plugin._cfg.update(overrides)
    plugin.group_history = {}
    plugin.last_repeat_time = {}
    plugin.fast_trigger_count = {}
    plugin.last_repeated_sig = {}
    plugin.disabled_groups = set()
    plugin.group_events = {}
    plugin.trigger_times = {}
    plugin.lock = asyncio.Lock()
    plugin._hub_active_lock = asyncio.Lock()
    plugin._hub_active = {}
    plugin._hub_records = {}
    plugin._hub_draw_usage = {"_date": datetime.now().strftime("%Y-%m-%d")}
    plugin._hub_force_cd = {}
    plugin._hub_drawn_recent = {}
    plugin._hub_members_cache = {}
    plugin._hub_propose_cd = {}
    plugin._hub_propose_count = {"_date": datetime.now().strftime("%Y-%m-%d")}
    plugin._proposals = {}
    plugin._data_dirty = False
    plugin._sim_cache = {}
    plugin._hub_kw = {}
    plugin._handled_command_events = {}

    async def no_sync():
        return None

    plugin._sync_config = no_sync
    plugin._flush_persisted_data = lambda: setattr(plugin, "_data_dirty", False)
    return plugin


async def send_three(plugin, chain_factory, senders=("10001", "10001", "10001"), raw_factory=None):
    events = []
    for index, sender in enumerate(senders):
        raw = raw_factory(index) if raw_factory else None
        event = FakeEvent(chain_factory(index), sender=sender, raw_message=raw)
        events.append(event)
        await plugin._pipe(event)
    return events


class RepeatCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_emoji_triggers_on_third_message(self):
        plugin = make_plugin()
        events = await send_three(plugin, lambda _: [Plain("😀")])
        self.assertEqual(events[0].sent, [])
        self.assertEqual(events[1].sent, [])
        self.assertEqual(len(events[2].sent), 1)

    async def test_native_qq_face_triggers_on_third_message(self):
        plugin = make_plugin()
        events = await send_three(plugin, lambda _: [Face(id=14)])
        self.assertEqual(len(events[2].sent), 1)

    async def test_market_face_uses_stable_emoji_id(self):
        plugin = make_plugin()

        def image(index):
            return [Image(
                file=f"temporary-{index}.gif",
                url=f"https://example.test/image?rkey={index}",
                emoji_id="abc123",
                emoji_package_id="42",
            )]

        events = await send_three(plugin, image)
        self.assertEqual(len(events[2].sent), 1)

    async def test_raw_mface_is_recovered_and_repeated_as_image(self):
        plugin = make_plugin()

        def raw(_):
            return {"message": [{
                "type": "mface",
                "data": {
                    "emoji_id": "abcdef123456",
                    "emoji_package_id": "42",
                    "key": "key",
                    "summary": "[测试表情]",
                },
            }]}

        events = await send_three(plugin, lambda _: [], raw_factory=raw)
        self.assertEqual(len(events[2].sent), 1)
        self.assertIsInstance(events[2].sent[0][0], Image)
        self.assertEqual(events[2].sent[0][0].emoji_id, "abcdef123456")

    async def test_volatile_url_tokens_do_not_break_image_matching(self):
        plugin = make_plugin()

        def image(index):
            url = f"https://multimedia.test/download?fileid=same-content&rkey={index}&expires={index}"
            return [Image(file=url)]

        events = await send_three(plugin, image)
        self.assertEqual(len(events[2].sent), 1)

    async def test_favorite_emoji_uses_raw_file_unique(self):
        plugin = make_plugin()
        stable_unique = "f5ef025d465873a0a025bb0b6de3bb5b.jpg"

        def image(index):
            # AstrBot Image 不声明 file_unique，模拟该字段只存在于原始 OneBot 段。
            return [Image(
                file=f"temporary-message-file-{index}.jpg",
                url=f"https://multimedia.nt.qq.com.cn/download?fileid=temp-{index}&rkey={index}",
            )]

        def raw(index):
            return {"message": [{
                "type": "image",
                "data": {
                    "summary": "[动画表情]",
                    "file": f"temporary-message-file-{index}.jpg",
                    "url": f"https://multimedia.nt.qq.com.cn/download?fileid=temp-{index}&rkey={index}",
                    "file_unique": stable_unique,
                    "file_size": 264118,
                },
            }]}

        events = await send_three(plugin, image, raw_factory=raw)
        self.assertEqual(len(events[2].sent), 1)

    async def test_image_prefers_stable_url_over_changing_temp_filename(self):
        plugin = make_plugin()

        def image(index):
            return [Image(
                file=f"temporary-{index}.jpg",
                url=f"https://cdn.example.test/favorite/stable-image?rkey={index}",
            )]

        events = await send_three(plugin, image)
        self.assertEqual(len(events[2].sent), 1)

    async def test_different_favorite_emoji_unique_ids_do_not_match(self):
        plugin = make_plugin()

        def raw(index):
            return {"message": [{
                "type": "image",
                "data": {
                    "file": f"temporary-{index}.jpg",
                    "file_unique": f"{index + 1:032x}.jpg",
                },
            }]}

        events = await send_three(
            plugin,
            lambda index: [Image(file=f"temporary-{index}.jpg")],
            raw_factory=raw,
        )
        self.assertEqual(events[2].sent, [])

    async def test_bot_own_image_is_never_counted_as_repeat_input(self):
        plugin = make_plugin()
        event = FakeEvent([Image(file="same.jpg")], sender="99999")
        await plugin._pipe(event)
        self.assertEqual(event.sent, [])
        self.assertEqual(plugin.group_history, {})

    async def test_different_market_faces_do_not_match(self):
        plugin = make_plugin()
        events = await send_three(
            plugin,
            lambda index: [Image(file="x.gif", emoji_id=f"emoji-{index}", emoji_package_id="42")],
        )
        self.assertEqual(events[2].sent, [])

    async def test_weight_decay_keeps_threshold_as_message_count(self):
        plugin = make_plugin(enable_weight_decay=True)
        events = await send_three(plugin, lambda _: [Plain("复读")])
        self.assertEqual(len(events[2].sent), 1)

    async def test_same_user_disabled_requires_distinct_senders(self):
        plugin = make_plugin(allow_same_user=False)
        same_sender = await send_three(plugin, lambda _: [Plain("复读")])
        self.assertEqual(same_sender[2].sent, [])

        plugin = make_plugin(allow_same_user=False)
        distinct = await send_three(
            plugin, lambda _: [Plain("复读")], senders=("1", "2", "3"))
        self.assertEqual(len(distinct[2].sent), 1)

    async def test_gameplay_whitelist_does_not_disable_repeat(self):
        plugin = make_plugin(whitelist_groups={"another-group"})
        events = await send_three(plugin, lambda _: [Plain("复读")])
        self.assertEqual(len(events[2].sent), 1)

    async def test_gameplay_whitelist_is_enforced_by_gameplay_guard(self):
        plugin = make_plugin(whitelist_groups={"another-group"})
        event = FakeEvent([Plain("抽老婆")])
        allowed = await plugin._check_hub_group_scope(event, "20001")
        self.assertFalse(allowed)
        self.assertIn("关系玩法白名单", event.sent[0])

    async def test_random_draw_consumes_only_independent_draw_quota(self):
        plugin = make_plugin(hub_daily=3)
        plugin._hub_active = {"20001": {"30001": {"name": "目标", "ts": time.time()}}}

        async def pool(*_):
            return ["30001"]

        plugin._hub_resolve_pool = pool
        plugin._hub_weighted_choice = lambda _gid, candidates: candidates[0]
        event = FakeEvent([Plain("抽老公")])
        await plugin._cmd_husband_draw(event)

        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 1)
        self.assertEqual(plugin._hub_today("20001")[0]["source"], "draw")
        self.assertTrue(event.sent)

    async def test_force_is_recorded_without_changing_draw_quota(self):
        plugin = make_plugin(hub_daily=3, hub_force_cd=0)
        plugin._hub_consume_draw("20001", "10001")

        async def member(*_):
            return True, "指定目标"

        plugin._hub_lookup_group_member = member
        event = FakeEvent([Plain("强娶老公"), At(qq="30002")])
        await plugin._cmd_husband_force(event)

        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 1)
        records = plugin._hub_today("20001")
        self.assertEqual(records[-1]["source"], "force")
        self.assertEqual(records[-1]["husband_id"], "30002")

    async def test_failed_force_changes_neither_quota_nor_records(self):
        plugin = make_plugin(hub_force_cd=0)
        plugin._hub_consume_draw("20001", "10001")

        async def not_member(*_):
            return False, "群外用户"

        plugin._hub_lookup_group_member = not_member
        event = FakeEvent([Plain("强娶老公"), At(qq="30003")])
        await plugin._cmd_husband_force(event)

        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 1)
        self.assertEqual(plugin._hub_today("20001"), [])
        self.assertTrue(event.sent)

    async def test_accepted_proposal_does_not_reset_or_consume_draw_quota(self):
        plugin = make_plugin()
        plugin._hub_consume_draw("20001", "10001")
        plugin._hub_consume_draw("20001", "10001")
        plugin._proposals = {"20001": {"30001": {
            "from": "10001", "from_name": "发起者",
            "to": "30001", "to_name": "接受者",
            "mode": "husband", "ts": time.time(),
        }}}
        event = FakeEvent([Plain("接受求婚")], sender="30001")
        await plugin.on_accept_proposal(event)

        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 2)
        self.assertEqual(plugin._hub_today("20001")[-1]["source"], "propose")
        self.assertNotIn("30001", plugin._proposals.get("20001", {}))

    async def test_rejected_and_expired_proposals_only_refund_proposal_quota(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                plugin = make_plugin()
                plugin._hub_consume_draw("20001", "10001")
                plugin._hub_propose_count["10001"] = 1
                plugin._hub_propose_cd["10001"] = time.time()
                plugin._proposals = {"20001": {"30001": {
                    "from": "10001", "from_name": "发起者",
                    "to": "30001", "to_name": "接收者",
                    "mode": "wife",
                    "ts": time.time() - (301 if expired else 0),
                }}}
                event = FakeEvent(
                    [Plain("接受求婚" if expired else "拒绝求婚")],
                    sender="30001",
                )
                if expired:
                    await plugin.on_accept_proposal(event)
                else:
                    await plugin.on_reject_proposal(event)

                self.assertEqual(plugin._hub_draw_used("20001", "10001"), 1)
                self.assertEqual(plugin._hub_propose_count.get("10001"), 0)

    async def test_proposal_daily_reset_does_not_touch_draw_usage(self):
        plugin = make_plugin()
        plugin._hub_consume_draw("20001", "10001")
        plugin._hub_consume_draw("20001", "10001")
        plugin._hub_propose_count = {"_date": "2000-01-01", "10001": 3}

        await RepeatProMaxPlugin._hub_sync(plugin)

        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(plugin._hub_propose_count, {"_date": today})
        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 2)

    def test_relation_record_rollover_cannot_reset_draw_quota(self):
        plugin = make_plugin()
        plugin._hub_consume_draw("20001", "10001")
        plugin._hub_consume_draw("20001", "10001")
        plugin._hub_records["20001"] = {
            "date": "2000-01-01",
            "records": [{"user_id": "10001", "source": "force"}],
        }

        plugin._hub_init_today("20001")

        self.assertEqual(plugin._hub_today("20001"), [])
        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 2)

    async def test_auto_mutual_binding_consumes_each_users_own_quota(self):
        plugin = make_plugin(hub_daily=3, auto_set_other_half=True)
        plugin._hub_active = {"20001": {"30001": {"name": "目标", "ts": time.time()}}}

        async def pool(*_):
            return ["30001"]

        plugin._hub_resolve_pool = pool
        plugin._hub_weighted_choice = lambda _gid, candidates: candidates[0]
        await plugin._cmd_husband_draw(FakeEvent([Plain("抽老公")]))

        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 1)
        self.assertEqual(plugin._hub_draw_used("20001", "30001"), 1)
        self.assertEqual(
            {r["source"] for r in plugin._hub_today("20001")},
            {"draw", "mutual"},
        )

    async def test_rank_ignores_force_and_proposal_records(self):
        plugin = make_plugin()
        today = datetime.now().strftime("%Y-%m-%d")
        plugin._hub_records["20001"] = {"date": today, "records": [
            {
                "user_id": "10001", "user_name": "甲",
                "husband_id": "30001", "husband_name": "随机目标",
                "source": "draw", "ts": time.time(),
            },
            {
                "user_id": "10001", "user_name": "甲",
                "husband_id": "30002", "husband_name": "强娶目标",
                "source": "force", "ts": time.time(),
            },
            {
                "user_id": "10001", "user_name": "甲",
                "husband_id": "30003", "husband_name": "求婚目标",
                "source": "propose", "ts": time.time(),
            },
        ]}

        event = FakeEvent([Plain("老公排行榜")])
        await plugin._cmd_husband_rank(event)
        result = event.sent[0]

        self.assertIn("随机目标", result)
        self.assertNotIn("强娶目标", result)
        self.assertNotIn("求婚目标", result)
        self.assertIn("强娶与求婚不参与排行", result)

    def test_first_upgrade_migrates_only_random_draw_usage(self):
        plugin = make_plugin()
        today = datetime.now().strftime("%Y-%m-%d")
        stored = {
            "active_users.json": {},
            "forced_marriage.json": {},
            "wife_records.json": {"20001": {"date": today, "records": [
                {"user_id": "10001", "source": "draw"},
                {"user_id": "10001", "source": "mutual"},
                {"user_id": "10001", "source": "force"},
                {"user_id": "10001", "source": "propose"},
            ]}},
            "draw_usage.json": None,
            "propose_cd.json": {},
            "propose_count.json": {},
            "proposals.json": {},
        }
        plugin._load_json = lambda filename, default=None: stored.get(filename, default)

        RepeatProMaxPlugin._load_persisted_data(plugin)

        self.assertEqual(plugin._hub_draw_used("20001", "10001"), 2)

    def test_persistence_includes_draw_usage_and_pending_proposals(self):
        plugin = make_plugin()
        plugin._hub_consume_draw("20001", "10001")
        plugin._proposals = {"20001": {"30001": {"from": "10001"}}}
        saved = {}
        plugin._save_json = lambda filename, data: saved.update({filename: data})

        RepeatProMaxPlugin._save_persisted_data(plugin)

        self.assertIn("draw_usage.json", saved)
        self.assertIn("proposals.json", saved)
        self.assertEqual(saved["draw_usage.json"]["20001"]["10001"], 1)

    def test_zero_max_length_means_unlimited(self):
        plugin = make_plugin(max_len=0)
        self.assertTrue(plugin._pass_len("很长的文字" * 1000))

    def test_config_bounds_prevent_impossible_threshold(self):
        window = plugin_window = RepeatProMaxPlugin._bounded_int("5", 5, 1, 20)
        threshold = min(RepeatProMaxPlugin._bounded_int("99", 3, 1, 20), window)
        self.assertEqual(plugin_window, 5)
        self.assertEqual(threshold, 5)

    def test_dashboard_defaults_match_requested_profile(self):
        schema = json.loads((MODULE_PATH.parent / "_conf_schema.json").read_text(encoding="utf-8"))
        expected = {
            "threshold": 3,
            "window_size": 5,
            "fuzzy_threshold": 0.9,
            "enable_weight_decay": False,
            "allow_same_user": True,
            "min_message_length": 0,
            "max_message_length": 200,
            "cooldown_time": 10,
            "cooldown_escalation": True,
            "duplicate_suppression_seconds": 60,
            "interrupt_cooldown_multiplier": 2,
            "interrupt_probability": 0.1,
            "interrupt_shuffle": True,
            "interrupt_reverse": True,
            "interrupt_custom": False,
            "interrupt_silent": False,
            "human_delay": "0.5-2.0",
            "fast_mode": True,
            "content_blacklist": "admin|【|抽老婆|抽老公",
            "enable_husband": True,
            "enable_wife": True,
            "husband_daily_limit": 10,
            "husband_active_days": 30,
            "husband_require_active": False,
            "husband_draw_decay_days": 7,
            "max_records": 500,
            "husband_force_cd_days": 3,
            "husband_force_daily": 3,
            "husband_propose_daily": 3,
            "husband_propose_cd": 86400,
            "allow_marry_bot": False,
            "husband_keyword_trigger": True,
            "keyword_trigger_mode": "exact",
            "at_waifu": False,
            "auto_set_other_half": False,
            "auto_withdraw_enabled": False,
            "auto_withdraw_delay_seconds": 30,
            "relation_graph_iterations": 100,
            "debug_mode": False,
        }
        for key, value in expected.items():
            self.assertEqual(schema[key]["default"], value, key)


if __name__ == "__main__":
    unittest.main()
