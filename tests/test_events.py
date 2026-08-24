"""事件哈希链测试：追加、连续性、篡改检测（specs/events-v1.md）。"""

import copy
import unittest

from zhanzhen.events import EventLog


class TestEventChain(unittest.TestCase):
    def test_append_builds_chain(self):
        log = EventLog()
        e1 = log.append("t1", "voucher", "v-1", "voucher.created", {"sha256": "ab" * 32})
        e2 = log.append("t1", "voucher", "v-1", "voucher.ocr_queued", {})
        e3 = log.append("t1", "voucher", "v-2", "voucher.created", {})  # 另一聚合
        self.assertEqual(e1["sequence"], 1)
        self.assertEqual(e2["sequence"], 2)
        self.assertIsNone(e1["previous_event_hash"])
        self.assertEqual(e2["previous_event_hash"], e1["event_hash"])
        self.assertIsNone(e3["previous_event_hash"])  # 新聚合从 null 开始
        ok, errors = log.verify_chain()
        self.assertTrue(ok, errors)
        self.assertEqual(len(errors), 0)

    def test_tamper_detection(self):
        log = EventLog()
        log.append("t1", "voucher", "v-1", "voucher.created", {"amount": 100})
        log.append("t1", "voucher", "v-1", "rules.evaluated", {"count": 0})
        # 模拟有人偷改历史 payload（不重算哈希）
        tampered = copy.deepcopy(log.all())
        tampered[0]["payload"]["amount"] = 0.01
        log2 = EventLog(tampered)
        ok, errors = log2.verify_chain()
        self.assertFalse(ok)
        self.assertTrue(any("不匹配" in e for e in errors))

    def test_sequence_gap_detected(self):
        events = []
        log = EventLog()
        e1 = log.append("t", "voucher", "v", "voucher.created")
        fake = dict(e1); fake["sequence"] = 5  # 跳号
        events = [e1, fake]
        log2 = EventLog(events)
        ok, errors = log2.verify_chain()
        self.assertFalse(ok)
        self.assertTrue(any("sequence" in e for e in errors))

    def test_unknown_aggregate_rejected(self):
        with self.assertRaises(ValueError):
            EventLog().append("t", "hacker", "x", "y")


if __name__ == "__main__":
    unittest.main()
