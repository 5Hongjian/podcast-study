"""Synthetic regressions: acceptance evidence, stale reviews and safe publication."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/podcast-study/scripts"
sys.path.insert(0, str(SCRIPTS))
import check_content as content


def example():
    text = "🎧小范围试验可能有用，但不适用于所有场景。"
    transcript = {"schema_version": 1, "source_version_id": "synthetic-v1", "transcript_sha256": "a" * 64,
                  "qa": {"readiness": "ready_with_limitations", "limitations": ["Synthetic; no media"]},
                  "segments": [{"id": "s1", "text": text, "start_seconds": None, "end_seconds": None}],
                  "time_precision": "unavailable"}
    draft = {"schema_version": 1, "episode": {"id": "synthetic", "title": "有限试验", "demo": True},
             "source": {k: transcript[k] for k in ("source_version_id", "transcript_sha256")},
             "citations": [{"id": "1", "number": 1, "segment_id": "s1", "start": 1, "end": len(text), "quote": text[1:]}],
             "nodes": [
                 {"id": "t", "level": 1, "kind": "topic", "parent_id": None, "title": "试验价值", "text": "讨论试验的作用与范围。", "citation_ids": ["1"]},
                 {"id": "p", "level": 2, "kind": "claim", "parent_id": "t", "title": "可能有用但有限制", "text": "小范围试验可能有用，但不能直接推广。", "citation_ids": ["1"]}],
             "coverage": [{"segment_id": "s1", "disposition": "covered", "topic_ids": ["t"]}],
             "summary": [{"id": "o", "title": "有限的价值", "text": "小范围试验可能有用，但不普遍适用。", "attribution": "source", "claim_ids": ["p"], "citation_ids": ["1"]}],
             "questions": [{"id": "q", "question": "试验总是有用吗？", "topic_ids": ["t"], "answer": [
                 {"id": "a", "text": "原文只说可能有用，并明确限制适用范围。", "attribution": "source", "claim_ids": ["p"], "citation_ids": ["1"]}]}]}
    hashes = content.evaluate(draft, transcript)["digests"]
    review = {}
    for stage, checks in (("outline", content.OUTLINE_CHECKS), ("final", content.FINAL_CHECKS)):
        review[stage] = {"content_sha256": hashes[stage], "transcript_package_sha256": hashes["transcript_package"],
                         "method": "separate_review", "reviewed_segment_ids": ["s1"],
                         "checks": {k: {"status": "passed", "evidence": "合成测试记录：s1 的可能性与范围限制均保留。"} for k in checks},
                         "essential_points": [{"text": "试验仅可能有用且适用有限。", "segment_ids": ["s1"], "output_ids": ["p"], "status": "covered", "reason": "p 保留可能与范围。"}],
                         "issues": []}
    review["final"]["quality"] = {k: {"score": 2, "reason": "合成测试夹具的程序输入，不代表真实评测结果。"} for k in content.QUALITY}
    return draft, transcript, review


class ContentChecks(unittest.TestCase):
    def setUp(self):
        self.draft, self.transcript, self.review = example()

    def report(self):
        return content.evaluate(self.draft, self.transcript, self.review)

    def test_accepted_unicode_and_untimed_source(self):
        self.assertEqual(self.report()["readiness"], "ready")
        bundle = content.publication(self.draft, self.transcript, self.report())
        self.assertEqual(bundle["source"]["time_precision"], "unavailable")
        self.assertNotIn("review", bundle)
        self.assertNotIn("coverage", bundle)

    def test_missing_review_never_passes(self):
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "needs_review")

    def test_source_link_rejects_unsafe_schemes_and_credentials(self):
        for url in ('javascript:alert(1)', 'https://user:secret@example.org/', 'https://example.org/a b', 42):
            self.draft['source']['url'] = url
            self.assertEqual(content.evaluate(self.draft, self.transcript)['readiness'], 'blocked')
        self.draft['source'].update(url='https://example.org/episode', label='原节目', reading_note='只有文字依据，未核对音频。')
        self.assertEqual(content.evaluate(self.draft, self.transcript)['readiness'], 'needs_review')

    def test_outline_can_run_before_prose(self):
        del self.draft["summary"], self.draft["questions"]
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review, "outline")["readiness"], "ready")

    def test_prose_change_expires_final_only(self):
        self.draft["summary"][0]["text"] += "这是修订稿。"
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review, "outline")["readiness"], "ready")
        self.assertEqual(self.report()["readiness"], "blocked")

    def test_structure_change_expires_outline(self):
        self.draft["nodes"][1]["title"] += "，保留边界"
        self.assertEqual(content.evaluate(self.draft, self.transcript, self.review, "outline")["readiness"], "blocked")

    def test_source_package_change_expires_reviews(self):
        self.transcript["segments"][0]["start_seconds"] = 12
        self.assertEqual(self.report()["readiness"], "blocked")

    def test_bad_citation_ranges_unknown_ids_and_duplicate_spans(self):
        for field, value in (("start", 2), ("end", True), ("segment_id", "missing"), ("quote", "断言一定有用")):
            with self.subTest(field=field):
                draft = copy.deepcopy(self.draft);draft["citations"][0][field] = value
                self.assertEqual(content.evaluate(draft, self.transcript)["readiness"], "blocked")
        self.draft["citations"].append({**self.draft["citations"][0], "id": "2", "number": 2})
        self.assertEqual(self.report()["readiness"], "blocked")

    def test_hierarchy_cycle_or_promoted_example_rejected(self):
        for change in ({"parent_id": "p"}, {"level": 2}, {"kind": "example"}):
            draft = copy.deepcopy(self.draft);draft["nodes"][0].update(change)
            self.assertEqual(content.evaluate(draft, self.transcript)["readiness"], "blocked")

    def test_every_segment_requires_accounting(self):
        self.transcript["segments"].append({"id": "s2", "text": "欢迎收听。"})
        self.assertIn("Coverage map", self.report()["errors"][0])
        self.draft["coverage"].append({"segment_id": "s2", "disposition": "omitted", "topic_ids": [], "reason": ""})
        self.assertEqual(self.report()["readiness"], "blocked")
        self.draft["coverage"][-1]["reason"] = "开场问候，没有实质论点。"
        self.assertEqual(content.evaluate(self.draft, self.transcript)["readiness"], "needs_review")

    def test_personal_notes_do_not_belong_in_generated_package(self):
        self.draft["notes"] = [{"text": "虚构用户认同"}]
        self.assertEqual(self.report()["readiness"], "blocked")

    def test_evidence_status_quality_and_major_issue_are_gates(self):
        cases = [lambda r: r["final"]["checks"]["faithfulness"].update(status="uncertain"),
                 lambda r: r["outline"]["checks"]["coverage"].update(evidence=""),
                 lambda r: r["final"]["quality"]["understanding"].update(score=1),
                 lambda r: r["final"]["essential_points"][0].update(status="missing", output_ids=[]),
                 lambda r: r["final"]["issues"].append({"severity": "major", "status": "open", "output_ids": ["a"], "segment_ids": ["s1"], "reason": "回答遗漏关键限制"})]
        for mutate in cases:
            r = copy.deepcopy(self.review);mutate(r)
            self.assertEqual(content.evaluate(self.draft, self.transcript, r)["readiness"], "needs_review")

    def test_partial_review_or_unknown_evidence_is_rejected(self):
        for ids in ([], ["s2"]):
            self.review["final"]["reviewed_segment_ids"] = ids
            self.assertEqual(self.report()["readiness"], "blocked")

    def test_malformed_input_fails_closed(self):
        for value in (None, [], {"qa": []}, 2):
            self.assertEqual(content.evaluate(self.draft, value)["readiness"], "blocked")

    def test_publication_preserves_previous_on_rejection_and_protects_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in (("draft", self.draft), ("transcript", self.transcript), ("review", self.review)):
                (root / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False))
            published = root / "episode.json";published.write_text("previous")
            base = [sys.executable, str(SCRIPTS / "check_content.py"), str(root / "draft.json"), "--transcript", str(root / "transcript.json")]
            failed = subprocess.run(base + ["--publish", str(published)], capture_output=True)
            self.assertEqual(failed.returncode, 2);self.assertEqual(published.read_text(), "previous")
            self.assertEqual(json.loads(failed.stdout)["readiness"], "blocked")
            success = subprocess.run(base + ["--review", str(root / "review.json"), "--publish", str(published)], capture_output=True)
            self.assertEqual(success.returncode, 0, success.stdout)
            self.assertEqual(json.loads(published.read_text())["revision"], self.report()["digests"]["final"])
            original = (root / "draft.json").read_bytes()
            rejected = subprocess.run(base + ["--review", str(root / "review.json"), "--publish", str(root / "draft.json")], capture_output=True)
            self.assertEqual(rejected.returncode, 2);self.assertEqual((root / "draft.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
