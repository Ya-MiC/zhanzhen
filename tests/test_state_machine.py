"""状态机迁移表测试 —— 与 specs/voucher-state-machine-v1.md 逐条对照。"""

import unittest

from zhanzhen import state_machine as sm


class TestTransitions(unittest.TestCase):
    def test_happy_path_full_lifecycle(self):
        path = [sm.INGESTED, sm.OCR_QUEUED, sm.OCR_COMPLETED,
                sm.REVIEWED, sm.JOURNAL_DRAFTED, sm.JOURNAL_CONFIRMED,
                sm.RULES_EVALUATED, sm.EXPORTED, sm.ARCHIVED]
        for cur, nxt in zip(path, path[1:]):
            self.assertTrue(sm.can_transition(cur, nxt), f"{cur}->{nxt}")

    def test_review_branches(self):
        self.assertTrue(sm.can_transition(sm.OCR_COMPLETED, sm.NEEDS_REVIEW))
        self.assertTrue(sm.can_transition(sm.OCR_FAILED, sm.OCR_QUEUED))     # 可重试
        self.assertTrue(sm.can_transition(sm.OCR_FAILED, sm.NEEDS_REVIEW))   # 坏损转人工
        self.assertTrue(sm.can_transition(sm.JOURNAL_DRAFTED, sm.REVIEWED))  # 驳回

    def test_illegal_shortcuts_blocked(self):
        for bad in [(sm.INGESTED, sm.JOURNAL_CONFIRMED),
                    (sm.INGESTED, sm.ARCHIVED),
                    (sm.NEEDS_REVIEW, sm.JOURNAL_DRAFTED),      # 未覆核不得做账
                    (sm.ARCHIVED, sm.EXPORTED),                  # 终态不可出
                    (sm.CAPTURED, sm.RULES_EVALUATED)]:
            self.assertFalse(sm.can_transition(*bad), bad)
            with self.assertRaises(sm.InvalidTransition):
                sm.assert_transition(*bad)

    def test_confirmed_cannot_go_back_to_draft(self):
        self.assertFalse(sm.can_transition(sm.JOURNAL_CONFIRMED, sm.JOURNAL_DRAFTED))

    def test_all_states_have_entries(self):
        for s in sm.STATES:
            self.assertIn(s, sm.TRANSITIONS)


if __name__ == "__main__":
    unittest.main()
