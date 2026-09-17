"""Controlled full-text boundary tests; fixture reviews are not real evaluations."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_content import content, example


def bind_fixture_review(draft, transcript, review):
    """Bind synthetic expectations only; never use this to renew real reviews."""
    hashes = content.evaluate(draft, transcript)["digests"]
    for stage in ("outline", "final"):
        review[stage]["content_sha256"] = hashes[stage]
        review[stage]["transcript_package_sha256"] = content.digest(transcript)
        review[stage]["reviewed_segment_ids"] = [row["id"] for row in transcript["segments"]]
    return review


class ContentBoundaryStress(unittest.TestCase):
    def setUp(self):
        self.draft, self.transcript, self.review = example()

    def accepted(self):
        bind_fixture_review(self.draft, self.transcript, self.review)
        report = content.evaluate(self.draft, self.transcript, self.review)
        self.assertEqual(report["readiness"], "ready", report)
        return report

    def add_answer_citation(self):
        text = self.transcript["segments"][0]["text"]
        end = text.index("，")
        self.draft["citations"].append({"id": "answer-only", "number": 2, "segment_id": "s1",
                                        "start": 1, "end": end, "quote": text[1:end]})
        self.draft["questions"][0]["answer"][0]["citation_ids"].append("answer-only")

    def test_answer_citation_repair_preserves_outline_but_requires_final_review(self):
        before = content.evaluate(self.draft, self.transcript, self.review)
        self.add_answer_citation()
        outline = content.evaluate(self.draft, self.transcript, self.review, "outline")
        self.assertEqual(outline["readiness"], "ready", outline)
        self.assertEqual(outline["digests"]["outline"], before["digests"]["outline"])
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review)["readiness"], "blocked")
        # Only the final fixture assessment is renewed; the accepted outline is reused.
        original_outline = copy.deepcopy(self.review["outline"])
        self.review["final"]["content_sha256"] = outline["digests"]["final"]
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review)["readiness"], "ready")
        self.assertEqual(self.review["outline"], original_outline)

    def test_prose_only_citation_changes_and_removal_do_not_expire_new_outline(self):
        self.add_answer_citation()
        self.accepted()
        for remove in (False, True):
            draft = copy.deepcopy(self.draft)
            if remove:
                draft["citations"].pop()
                draft["questions"][0]["answer"][0]["citation_ids"].remove("answer-only")
            else:
                citation = draft["citations"][-1]
                citation["end"] -= 1
                citation["quote"] = citation["quote"][:-1]
            self.assertEqual(content.evaluate(draft, self.transcript, self.review, "outline")["readiness"], "ready")
            self.assertEqual(content.evaluate(draft, self.transcript, self.review)["readiness"], "blocked")

    def test_outline_dependencies_still_expire_new_and_legacy_reviews(self):
        self.add_answer_citation()
        self.accepted()
        legacy = copy.deepcopy(self.review)
        core = {key: self.draft[key] for key in
                ("schema_version", "episode", "source", "citations", "nodes", "coverage")}
        legacy["outline"]["content_sha256"] = content.digest(core)
        mutations = {
            "node": lambda draft, source: draft["nodes"][1].update(text="修订后的论点。"),
            "node evidence": lambda draft, source: draft["nodes"][1]["citation_ids"].append("answer-only"),
            "evidence range": lambda draft, source: draft["citations"][0].update(
                end=draft["citations"][0]["end"] - 1, quote=draft["citations"][0]["quote"][:-1]),
            "coverage": lambda draft, source: draft["coverage"][0].update(
                disposition="omitted", topic_ids=[], reason="合成待复核省略判断。"),
            "source metadata": lambda draft, source: draft["source"].update(label="另一来源说明"),
            "source package": lambda draft, source: source["segments"][0].update(start_seconds=12),
        }
        for version, review in (("new", self.review), ("legacy", legacy)):
            for name, mutate in mutations.items():
                with self.subTest(version=version, dependency=name):
                    draft, source = copy.deepcopy(self.draft), copy.deepcopy(self.transcript)
                    mutate(draft, source)
                    report = content.evaluate(draft, source, review, "outline")
                    self.assertEqual(report["readiness"], "blocked", report)
                    self.assertIn("Review is stale", report["errors"][0])

    def test_legacy_review_accepts_same_core_without_rewriting_record(self):
        self.add_answer_citation()
        self.accepted()
        core = {key: self.draft[key] for key in
                ("schema_version", "episode", "source", "citations", "nodes", "coverage")}
        self.review["outline"]["content_sha256"] = content.digest(core)
        original = copy.deepcopy(self.review)
        report = content.evaluate(self.draft, self.transcript, self.review)
        self.assertEqual(report["readiness"], "ready", report)
        self.assertNotEqual(report["digests"]["outline"], original["outline"]["content_sha256"])
        self.assertEqual(self.review, original)
        # A legacy digest covering a prose citation cannot be rebound after it changes.
        self.draft["citations"][-1]["number"] = 3
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review, "outline")["readiness"], "blocked")

    def add_background_topic(self):
        text = "这次试验在周二进行。"
        self.transcript["segments"].append({"id": "s2", "text": text})
        self.draft["citations"].append({"id": "2", "number": 2, "segment_id": "s2",
                                        "start": 0, "end": len(text), "quote": text})
        self.draft["nodes"].extend([
            {"id": "t2", "level": 1, "kind": "topic", "parent_id": None,
             "title": "试验背景", "text": "介绍本次试验时间。", "citation_ids": ["2"]},
            {"id": "p2", "level": 2, "kind": "claim", "parent_id": "t2",
             "title": "周二进行", "text": text, "citation_ids": ["2"]},
        ])
        self.draft["coverage"].append({"segment_id": "s2", "disposition": "covered", "topic_ids": ["t2"]})
        self.draft["summary"].append({"id": "o2", "title": "试验时间", "text": text,
                                     "attribution": "source", "claim_ids": ["p2"], "citation_ids": ["2"]})
        for stage in ("outline", "final"):
            self.review[stage]["essential_points"].append({"text": text, "segment_ids": ["s2"],
                "output_ids": ["p2"], "status": "covered", "reason": "p2 保留时间背景，无需重复问答。"})

    def test_questions_can_select_topics_while_summary_covers_the_whole_episode(self):
        self.add_background_topic()
        report = self.accepted()
        published = content.publication(self.draft, self.transcript, report)
        self.assertEqual(len(published["summary"]), 2)
        self.assertEqual(len(published["questions"]), 1)
        self.assertEqual(published["nodes"], self.draft["nodes"])

    def test_selected_questions_keep_summary_topic_and_nonempty_answer_requirements(self):
        self.add_background_topic()
        self.accepted()
        mutations = {
            "missing summary topic": lambda draft: draft["summary"].pop(),
            "empty questions": lambda draft: draft.update(questions=[]),
            "empty answer": lambda draft: draft["questions"][0].update(answer=[]),
            "mismatched topics": lambda draft: draft["questions"][0].update(topic_ids=["t2"]),
            "missing answer evidence": lambda draft: draft["questions"][0]["answer"][0].update(citation_ids=[]),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                draft = copy.deepcopy(self.draft)
                mutate(draft)
                self.assertEqual(content.evaluate(draft, self.transcript)["readiness"], "blocked")
        self.review["final"]["essential_points"][-1].update(status="missing", output_ids=[])
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review)["readiness"], "needs_review")

    def test_transcript_schema_and_offsets_are_not_trusted_from_readiness(self):
        for key, value in (("schema_version", True), ("schema_version", 99),
                           ("offset_unit", "utf16")):
            with self.subTest(key=key, value=value):
                source = copy.deepcopy(self.transcript)
                source[key] = value
                self.assertEqual(content.evaluate(self.draft, source)["readiness"], "blocked")

    def test_structural_errors_cannot_coexist_with_accepted_input(self):
        self.transcript["qa"]["structural_errors"] = ["truncated cue"]
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_source_segment_times_are_finite_ordered_numbers(self):
        for start, end in ((True, 10), ("1", 10), (-1, 10), (3, 2),
                           (1, False), (None, 10), (1, float("nan")), (1, float("inf"))):
            with self.subTest(start=start, end=end):
                source = copy.deepcopy(self.transcript)
                source["segments"][0].update(start_seconds=start, end_seconds=end)
                self.assertEqual(content.evaluate(self.draft, source)["readiness"], "blocked")

    def test_known_duration_is_an_upper_bound(self):
        self.transcript.update(media_duration_seconds=5, time_precision="cue")
        self.transcript["segments"][0].update(start_seconds=1, end_seconds=6)
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_declared_time_precision_needs_actual_positions(self):
        for precision in ("cue", "segment_start"):
            self.transcript["time_precision"] = precision
            self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")
        self.transcript["segments"][0]["start_seconds"] = 0
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "needs_review")
        self.transcript["time_precision"] = "cue"
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_explicit_root_parent_is_required_by_the_website(self):
        del self.draft["nodes"][0]["parent_id"]
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_publication_rechecks_the_current_content_and_source(self):
        accepted = self.accepted()
        for changed in ("content", "source"):
            with self.subTest(changed=changed):
                draft, source = copy.deepcopy(self.draft), copy.deepcopy(self.transcript)
                if changed == "content":
                    draft["summary"][0]["text"] = "评估之后被替换的断言。"
                else:
                    source["segments"][0]["text"] += "评估后改变的原文。"
                with self.assertRaises(ValueError):
                    content.publication(draft, source, accepted)

    def test_unverified_raw_timestamps_do_not_become_verified_navigation(self):
        self.transcript.update(time_precision="cue", media_duration_seconds=10)
        self.transcript["segments"][0].update(start_seconds=1, end_seconds=8)
        self.transcript["qa"]["checks"] = {"timing": {"status": "unavailable", "evidence": "未对齐媒体版本。"}}
        result = content.publication(self.draft, self.transcript, self.accepted())
        self.assertEqual(result["source"]["time_precision"], "unavailable")
        self.assertEqual(result["source"]["segments"][0]["start_seconds"], 1)

    def test_verified_cue_times_still_publish(self):
        self.transcript.update(time_precision="cue", media_duration_seconds=10)
        self.transcript["segments"][0].update(start_seconds=1, end_seconds=8)
        self.transcript["qa"]["checks"] = {"timing": {"status": "passed", "basis": "publisher_timestamps", "evidence": "合成媒体版本已核对。"}}
        result = content.publication(self.draft, self.transcript, self.accepted())
        self.assertEqual(result["source"]["time_precision"], "cue")

    def test_bool_cannot_replace_integer_schema_level_range_number_or_score(self):
        for target, field in ((self.draft, "schema_version"), (self.draft["nodes"][0], "level"),
                              (self.draft["citations"][0], "start"), (self.draft["citations"][0], "number")):
            original = target[field]
            target[field] = True
            self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")
            target[field] = original
        self.review["final"]["quality"]["overview"]["score"] = True
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review)["readiness"], "blocked")

    def test_malformed_nested_types_fail_closed(self):
        for key in ("episode", "source", "citations", "nodes", "coverage", "summary", "questions"):
            for value in (None, True, 17, "invalid", {"unexpected": []}):
                with self.subTest(key=key, value=value):
                    draft = copy.deepcopy(self.draft)
                    draft[key] = value
                    self.assertEqual(content.evaluate(draft, self.transcript)["readiness"], "blocked")
        for key in ("method", "checks", "essential_points", "issues", "quality", "reviewed_segment_ids"):
            review = copy.deepcopy(self.review)
            review["final"][key] = [None, {}]
            self.assertEqual(content.evaluate(self.draft, self.transcript, review)["readiness"], "blocked")

    def test_repeat_utterances_keep_distinct_exact_unicode_locations(self):
        repeated = "🎧可能有用。e\u0301／é／👩‍🔬"
        text = repeated + "\n" + repeated
        self.transcript["segments"][0]["text"] = text
        self.draft["citations"][0].update(start=len(repeated) + 1, end=len(text), quote=repeated)
        self.transcript["segments"].append({"id": "s2", "text": repeated, "start_seconds": None, "end_seconds": None})
        self.draft["citations"].append({"id": "c2", "number": 2, "segment_id": "s2", "start": 0, "end": len(repeated), "quote": repeated})
        self.draft["nodes"][1]["citation_ids"].append("c2")
        self.draft["coverage"].append({"segment_id": "s2", "disposition": "covered", "topic_ids": ["t"]})
        self.accepted()
        # A UTF-16 offset is invalid even when its quote looks the same.
        self.draft["citations"][0]["start"] = len((repeated + "\n").encode("utf-16-le")) // 2
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_cross_segment_quote_and_normalized_quote_are_rejected(self):
        self.transcript["segments"][0]["text"] = "边界e\u0301"
        self.transcript["segments"].append({"id": "s2", "text": "后半句。"})
        self.draft["coverage"].append({"segment_id": "s2", "disposition": "omitted", "topic_ids": [], "reason": "合成边界辅助片段。"})
        self.draft["citations"][0].update(start=0, end=9, quote="边界e\u0301后半句。")
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")
        self.draft["citations"][0].update(start=0, end=4, quote="边界é")
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_other_source_same_text_does_not_reuse_review(self):
        self.transcript["source_version_id"] = "synthetic-other-edition"
        self.draft["source"]["source_version_id"] = self.transcript["source_version_id"]
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review)["readiness"], "blocked")

    def test_coverage_requires_evidence_for_each_declared_topic(self):
        self.transcript["segments"].append({"id": "s2", "text": "合成片段没有任何引用。"})
        self.draft["coverage"].append({"segment_id": "s2", "disposition": "covered", "topic_ids": ["t"]})
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "blocked")

    def test_large_complete_source_and_outline_do_not_require_fake_timing(self):
        # Repeated revisits to one topic need distinct positions, not one invented range.
        for i in range(2, 1202):
            sid, cid = f"s{i}", f"c{i}"
            text = f"第{i}次重访：这个结论仍然有条件。"
            self.transcript["segments"].append({"id": sid, "text": text, "start_seconds": None, "end_seconds": None})
            self.draft["citations"].append({"id": cid, "number": i, "segment_id": sid, "start": 0, "end": len(text), "quote": text})
            self.draft["nodes"][1]["citation_ids"].append(cid)
            self.draft["coverage"].append({"segment_id": sid, "disposition": "covered", "topic_ids": ["t"]})
        self.accepted()

    def test_rejected_review_does_not_overwrite_a_previous_release(self):
        for stage, check in (("outline", "coverage"), ("final", "citation_support")):
            with self.subTest(stage=stage, check=check):
                self.review[stage]["checks"][check]["status"] = "failed"
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for name, value in (("draft", self.draft), ("source", self.transcript), ("review", self.review)):
                        (root / name).write_text(json.dumps(value, ensure_ascii=False))
                    target = root / "episode.json"
                    previous = b'{"previous":"accepted"}\n'
                    target.write_bytes(previous)
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = content.main([str(root / "draft"), "--transcript", str(root / "source"),
                                             "--review", str(root / "review"), "--publish", str(target)])
                    self.assertEqual(code, 2)
                    self.assertEqual(target.read_bytes(), previous)
                self.review[stage]["checks"][check]["status"] = "passed"

    def test_atomic_replace_failure_preserves_the_accepted_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("draft", self.draft), ("source", self.transcript), ("review", self.review)):
                (root / name).write_text(json.dumps(value, ensure_ascii=False))
            target = root / "episode.json"
            previous = b'{"previous":"accepted"}\n'
            target.write_bytes(previous)
            with patch("check_transcript.os.replace", side_effect=OSError("controlled replace failure")), contextlib.redirect_stdout(io.StringIO()):
                code = content.main([str(root / "draft"), "--transcript", str(root / "source"),
                                     "--review", str(root / "review"), "--publish", str(target)])
            self.assertEqual(code, 2)
            self.assertEqual(target.read_bytes(), previous)
            self.assertEqual(list(root.glob(".transcript-*")), [])

    def test_deep_or_nonfinite_json_is_reported_without_overwriting(self):
        for bad in ('{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}', '{"x":1,"x":2}',
                    '[' * 12000 + '0' + ']' * 12000):
            with self.subTest(length=len(bad)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "draft").write_text(bad)
                (root / "source").write_text(json.dumps(self.transcript))
                target = root / "episode.json"
                target.write_text("previous accepted release")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = content.main([str(root / "draft"), "--transcript", str(root / "source"), "--publish", str(target)])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output.getvalue())["readiness"], "blocked")
                self.assertEqual(target.read_text(), "previous accepted release")


if __name__ == "__main__":
    unittest.main()
