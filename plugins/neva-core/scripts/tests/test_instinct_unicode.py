#!/usr/bin/env python3
"""Lessons in Arabic (or any non-Latin script) are read as words, never as nothing.

The tokenizer kept only [a-z0-9], so every Arabic lesson had no tokens and the same content key, and
rejecting one Arabic lesson suppressed every other. These tests prove two different Arabic lessons
never match, the same lesson with diacritics or tatweel added does, and a text with no words at all
(emoji, punctuation) matches nothing.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import sys
import unittest

from test_instinct_learning import LEARNING_SCRIPTS, InstinctSandbox

sys.path.insert(0, LEARNING_SCRIPTS)
import instinct_match  # noqa: E402

ERRORS_TRIGGER = "عند التعامل مع أخطاء النموذج"
ERRORS_ACTION = ("اكتب رسالة الخطأ "
                 "باسم الحقل وطريقة "
                 "الإصلاح.")
# The same lesson, vowelled and with a tatweel stretching one word.
ERRORS_ACTION_VOWELLED = ("اكتُبْ رسالةَ "
                          "الخطــأ باسمِ "
                          "الحقل وطريقة "
                          "الإصلاح.")
BACKUP_TRIGGER = "عند تعديل جداول قاعدة البيانات"
BACKUP_ACTION = ("احفظ نسخة احتياطية "
                 "من قاعدة البيانات "
                 "قبل كل ترحيل.")


class ArabicContentCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)

    def _lesson(self, iid, trigger, action):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", iid, "--trigger", trigger, "--action", action,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)

    def _reject_errors_lesson(self):
        self._lesson("ar-one", ERRORS_TRIGGER, ERRORS_ACTION)
        self.sb.run("propose")
        self.sb.tick(self.sb.proposal_path(), "promote-global:ar-one", "reject")
        self.sb.run("apply-promotions")

    def test_a_different_arabic_lesson_is_not_suppressed_by_a_rejection(self):
        self._reject_errors_lesson()
        self._lesson("ar-two", BACKUP_TRIGGER, BACKUP_ACTION)
        r = self.sb.run("propose")
        self.assertNotIn("says the same as", r.stdout)
        with open(self.sb.proposal_path(), encoding="utf-8") as fh:
            self.assertIn("block_id: promote-global:ar-two", fh.read(), r.stdout + r.stderr)

    def test_the_same_arabic_lesson_vowelled_is_still_the_same(self):
        self._reject_errors_lesson()
        self._lesson("ar-one-again", ERRORS_TRIGGER, ERRORS_ACTION_VOWELLED)
        r = self.sb.run("propose")
        self.assertIn("Skipped promote-global:ar-one-again: says the same as promote-global:ar-one", r.stdout)


class TokenizerCase(unittest.TestCase):
    def test_arabic_words_are_tokens_and_diacritics_do_not_matter(self):
        plain, vowelled = instinct_match.tokens(ERRORS_ACTION), instinct_match.tokens(ERRORS_ACTION_VOWELLED)
        self.assertGreaterEqual(len(plain), 4)
        self.assertEqual(plain, vowelled)

    def test_english_tokens_are_unchanged(self):
        self.assertEqual(instinct_match.tokens("Testing the snake_case Boards, 42 times!"),
                         ["test", "snak", "case", "board", "time"])

    def test_emoji_or_punctuation_only_text_has_no_tokens(self):
        for text in ("\U0001F680\U0001F525✨", "?!... --- ***", ""):
            self.assertEqual(instinct_match.tokens(text), [])

    def test_no_tokens_matches_nothing(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        from test_instinct_rule_text import _module
        cli = _module(sb)
        emoji_a = cli._content_from_fields({}, "\U0001F680\U0001F525")
        emoji_b = cli._content_from_fields({}, "✨✨")
        self.assertEqual(emoji_a['content_tokens'], [])
        self.assertNotEqual(emoji_a['content_key'], emoji_b['content_key'])
        ledger = {"promote-global:old": dict(status="rejected", kind="promote-global", **emoji_a)}
        block = {'block_id': "promote-global:new", 'kind': "promote-global"}
        self.assertIsNone(cli._matching_decision(ledger, block, emoji_a), "an empty token list matched")
        self.assertIsNone(cli._matching_decision(ledger, block, emoji_b))


if __name__ == "__main__":
    unittest.main()
