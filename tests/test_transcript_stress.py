"""Controlled complete-transcript boundaries; fixtures are entirely synthetic."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "transcript_stress_check", ROOT / "skills/podcast-study/scripts/check_transcript.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CompleteTranscriptStress(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, text, fmt="txt", bom=False, newline="\n"):
        path = self.root / ("synthetic." + fmt)
        raw = (b"\xef\xbb\xbf" if bom else b"") + text.replace("\n", newline).encode("utf-8")
        path.write_bytes(raw)
        return path

    def review(self, package, timed=False):
        checks = {
            name: dict(status="passed", basis="human_reference",
                       evidence="Controlled fixture: every sentence and speaker checked against the authored reference.")
            for name in checker.CHECK_NAMES}
        if not timed:
            checks["timing"] = dict(status="unavailable", basis=None,
                                    evidence="The synthetic reference has no verified timing.")
        return dict(source_version_id=package["source_version_id"],
                    transcript_sha256=package["transcript_sha256"],
                    media_duration_seconds=package["media_duration_seconds"], checks=checks, issues=[])

    def test_txt_roundtrip_preserves_chinese_unicode_and_every_separator(self):
        rng = random.Random(424)
        utterances = ["甲：不是所有变化都有因果关系。", "乙：增长 3.1%，不是 31%。",
                      "甲：e\u0301 与 é 不合并；👩🏽‍💻、🎧 都保留。", "乙：हाँ，我同意。", "甲：同意。"]
        separators = ["\n\n", "\n \n", "\n\t\n\n", "\n\n \n"]
        for case in range(48):
            text = "\n \n" + "".join(rng.choice(utterances) + rng.choice(separators)
                                      for _ in range(12)) + "结尾。\n\n"
            with self.subTest(case=case):
                path = self.write(text, bom=case % 2 == 0, newline=("\n", "\r\n", "\r")[case % 3])
                raw = path.read_bytes()
                package = checker.prepare(path, "synthetic-complete-v1", "native")
                self.assertFalse(package["qa"]["structural_errors"])
                self.assertEqual("".join(s["text"] for s in package["segments"]), text)
                self.assertEqual(package["transcript_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(package["segments"], checker.prepare(path, "synthetic-complete-v1", "native")["segments"])

    def test_srt_literal_arrow_is_text_not_a_hidden_cue(self):
        path = self.write("1\n00:00:00,000 --> 00:00:03,000\nA --> B\n不是 B --> A。\n", "srt")
        initial = checker.prepare(path, "synthetic-complete-v1", "native", 3)
        self.assertFalse(initial["qa"]["structural_errors"])
        self.assertEqual(initial["segments"][0]["text"], "A --> B\n不是 B --> A。")
        accepted = checker.prepare(path, "synthetic-complete-v1", "native", 3,
                                   self.review(initial, timed=True))
        self.assertEqual(accepted["qa"]["readiness"], "ready")

    def test_missing_separator_still_blocks_instead_of_hiding_the_second_cue(self):
        for hour in ("00", "٠٠"):
            with self.subTest(hour=hour):
                first = "1\n00:00:00,000 --> 00:00:01,000\n第一句\n"
                second = f"2\n{hour}:00:01,000 --> {hour}:00:02,000\n第二句\n"
                separated = checker.prepare(self.write(first + "\n" + second, "srt"),
                                            "synthetic-complete-v1", "native", 2)
                self.assertEqual(len(separated["segments"]), 2)
                result = checker.prepare(self.write(first + second, "srt"),
                                         "synthetic-complete-v1", "native", 2)
                self.assertEqual(result["qa"]["readiness"], "blocked")
                self.assertIn("nested cue", " ".join(result["qa"]["structural_errors"]))

    def test_vtt_escape_voice_tags_and_simultaneous_speech_are_retained(self):
        text = ("WEBVTT 多人访谈\nLanguage: zh\n\nNOTE 人工合成完整参考\n\n"
                "甲\n00:00.000 --> 00:03.000 align:left\n<v 甲>不是 A --&gt; B。🎧\n\n"
                "乙\n00:00.000 --> 00:01.000 align:right\n<v 乙>我不同意。\n\n"
                "甲\n00:01.000 --> 00:04.000\n<v 甲>我不同意。\n")
        path = self.write(text, "vtt", bom=True, newline="\r\n")
        initial = checker.prepare(path, "synthetic-complete-v1", "native", 4)
        self.assertFalse(initial["qa"]["structural_errors"])
        self.assertEqual(len(initial["segments"]), 3)
        self.assertEqual(initial["segments"][0]["text"], "<v 甲>不是 A --&gt; B。🎧")
        self.assertEqual(initial["segments"][0]["cue_settings"], "align:left")
        self.assertEqual(len({s["id"] for s in initial["segments"]}), 3)
        review = self.review(initial, timed=True)
        result = checker.prepare(path, "synthetic-complete-v1", "native", 4, review)
        self.assertEqual(result["qa"]["readiness"], "ready")
        review["checks"]["timing"] = dict(status="unavailable", basis=None, evidence="Not checked.")
        self.assertEqual(checker.prepare(path, "synthetic-complete-v1", "native", 4, review)["qa"]["readiness"],
                         "needs_review")

    def test_natural_repetition_and_silence_do_not_become_automatic_hallucinations(self):
        path = self.write("1\n00:00:00,000 --> 00:00:01,000\n对。\n\n"
                          "2\n00:00:09,000 --> 00:00:10,000\n对。\n", "srt")
        initial = checker.prepare(path, "synthetic-complete-v1", "native", 12)
        self.assertEqual({d["type"] for d in initial["qa"]["diagnostics"]},
                         {"repeated_text", "uncovered_interval"})
        reviewed = checker.prepare(path, "synthetic-complete-v1", "native", 12, self.review(initial, timed=True))
        self.assertEqual(reviewed["qa"]["readiness"], "ready")
        self.assertEqual(len(reviewed["segments"]), 2)

    def test_txt_with_partial_timestamps_cannot_claim_full_timing(self):
        path = self.write("[00:00] 主持人：开场。\n\n嘉宾：这里没有时间。\n\n[26:48] 主持人：结束。")
        initial = checker.prepare(path, "synthetic-complete-v1", "native", 1700)
        self.assertEqual(initial["time_precision"], "unavailable")
        self.assertTrue(all(s["start_seconds"] is None and s["end_seconds"] is None for s in initial["segments"]))
        review = self.review(initial)
        self.assertEqual(checker.prepare(path, "synthetic-complete-v1", "native", 1700, review)["qa"]["readiness"],
                         "ready_with_limitations")
        review["checks"]["timing"] = dict(status="passed", basis="publisher_timestamps", evidence="Three labels exist.")
        self.assertEqual(checker.prepare(path, "synthetic-complete-v1", "native", 1700, review)["qa"]["readiness"],
                         "needs_review")

    def test_unhashable_source_kind_returns_blocked_not_an_exception(self):
        path = self.write("完整合成稿。")
        for kind in ([], {}, ["native"]):
            with self.subTest(kind=kind):
                result = checker.prepare(path, "synthetic-complete-v1", kind)
                self.assertEqual(result["qa"]["readiness"], "blocked")
                json.dumps(result, allow_nan=False)

    def test_reencoding_or_single_character_revision_invalidates_prior_review(self):
        text = "不是 31%。\n\n这里是 3.1%。\n"
        path = self.write(text)
        initial = checker.prepare(path, "synthetic-complete-v1", "native")
        review = self.review(initial)
        for revised, bom, newline in ((text.replace("不是", "是"), False, "\n"),
                                       (text, True, "\n"), (text, False, "\r\n")):
            with self.subTest(bom=bom, newline=newline, revised=revised):
                self.write(revised, bom=bom, newline=newline)
                result = checker.prepare(path, "synthetic-complete-v1", "native", review=review)
                self.assertEqual(result["qa"]["readiness"], "blocked")
                self.assertNotEqual(result["segments"][0]["id"], initial["segments"][0]["id"])

    def test_long_complete_transcript_has_stable_distinct_ids(self):
        # A 2,000-turn input catches accidental truncation and repeated-cue ID reuse.
        text = "\n\n".join(f"第 {i} 轮：{'对。' if i % 3 else '不是同一结论。🎧'}" for i in range(2000))
        path = self.write(text)
        initial = checker.prepare(path, "synthetic-complete-v1", "native")
        self.assertEqual(len(initial["segments"]), 2000)
        self.assertEqual(len({s["id"] for s in initial["segments"]}), 2000)
        self.assertEqual("".join(s["text"] for s in initial["segments"]), text)
        reviewed = checker.prepare(path, "synthetic-complete-v1", "native", review=self.review(initial))
        self.assertEqual(reviewed["qa"]["readiness"], "ready_with_limitations")

    def test_excessively_nested_review_fails_with_a_structured_block(self):
        path = self.write("完整合成稿。")
        review = self.root / "deep-review.json"
        review.write_text("[" * 20000 + "0" + "]" * 20000, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code = checker.main([str(path), "--source-version", "synthetic-complete-v1",
                                 "--kind", "native", "--review", str(review)])
        self.assertEqual(code, 2)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["qa"]["readiness"], "blocked")
        self.assertIn("Cannot read review", " ".join(result["qa"]["structural_errors"]))

    def test_output_cannot_overwrite_inputs_via_symlinks_or_hardlinks(self):
        path = self.write("完整合成稿。")
        initial = checker.prepare(path, "synthetic-complete-v1", "native")
        review = self.root / "review.json"
        review.write_text(json.dumps(self.review(initial)), encoding="utf-8")
        originals = {p: p.read_bytes() for p in (path, review)}
        for source in (path, review):
            for kind in ("symlink", "hardlink"):
                with self.subTest(source=source.name, kind=kind):
                    output = self.root / (source.name + "." + kind)
                    output.symlink_to(source) if kind == "symlink" else os.link(source, output)
                    with contextlib.redirect_stdout(io.StringIO()) as stream:
                        code = checker.main([str(path), "--source-version", "synthetic-complete-v1",
                                             "--kind", "native", "--review", str(review), "--output", str(output)])
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(stream.getvalue())["qa"]["readiness"], "blocked")
                    self.assertEqual(source.read_bytes(), originals[source])


if __name__ == "__main__":
    unittest.main()
