"""Synthetic parser and evidence-gate regressions; no media/model calls."""
import contextlib
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "transcript_check", ROOT / "skills/podcast-study/scripts/check_transcript.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

SRT = "1\n00:00:00,000 --> 00:00:02,000\n不是每次都增长。\n第二行保留。\n\n2\n00:00:02,000 --> 00:00:04,000\n收益率是 3.1%。\n"


class TranscriptChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "synthetic.srt"
        self.path.write_text(SRT, encoding="utf-8")

    def prepare(self, review=None, kind="asr", duration=4, path=None):
        return checker.prepare(path or self.path, "synthetic-media-v1", kind, duration, review)

    def review(self, package=None):
        package = package or self.prepare()
        return dict(source_version_id=package["source_version_id"],
                    transcript_sha256=package["transcript_sha256"],
                    media_duration_seconds=package["media_duration_seconds"],
                    checks={name: dict(status="passed", evidence="Synthetic human-reviewed audio intervals 0–4 s.",
                                       basis="audio_review") for name in checker.CHECK_NAMES}, issues=[])

    def test_preserves_payload_hash_and_source_bound_ids(self):
        raw = b"\xef\xbb\xbf" + SRT.replace("\n", "\r\n").encode()
        self.path.write_bytes(raw)
        result = self.prepare()
        self.assertEqual(result["transcript_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["segments"][0]["text"], "不是每次都增长。\n第二行保留。")
        self.assertEqual(result["segments"], self.prepare()["segments"])
        other = checker.prepare(self.path, "another-version", "asr", 4)
        self.assertNotEqual(result["segments"][0]["id"], other["segments"][0]["id"])
        self.assertEqual(self.path.read_bytes(), raw)

    def test_structure_alone_never_passes_full_span(self):
        result = self.prepare()
        self.assertEqual(result["qa"]["readiness"], "needs_review")
        self.assertEqual(result["qa"]["checks"]["fidelity"]["status"], "pending")

    def test_bound_audio_review_passes_and_run_wrapper_supported(self):
        result = self.prepare({"input_review": self.review()})
        self.assertEqual(result["qa"]["readiness"], "ready")
        self.assertIn("does not inspect audio", result["qa"]["limitations"][0])

    def test_stale_source_or_transcript_review_is_blocked(self):
        for key in ("source_version_id", "transcript_sha256"):
            with self.subTest(key=key):
                review = self.review()
                review[key] = "stale"
                self.assertEqual(self.prepare(review)["qa"]["readiness"], "blocked")

    def test_review_duration_must_be_explicit_valid_and_current(self):
        review = self.review()
        self.assertEqual(self.prepare(review, duration=7200)["qa"]["readiness"], "blocked")
        self.assertEqual(self.prepare(review, duration=None)["qa"]["readiness"], "blocked")
        for value in (None, True, False, "4", math.nan, math.inf, -1, 0):
            with self.subTest(value=value):
                review["media_duration_seconds"] = value
                self.assertEqual(self.prepare(review)["qa"]["readiness"], "blocked")
        del review["media_duration_seconds"]
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "blocked")
        self.assertEqual(self.prepare(review, duration=None)["qa"]["readiness"], "blocked")
        review["media_duration_seconds"] = 4.0
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "ready")

    def test_unknown_duration_retains_limitations_and_new_duration_requires_review(self):
        review = self.review(self.prepare(duration=None))
        result = self.prepare(review, duration=None)
        self.assertEqual(result["qa"]["readiness"], "ready_with_limitations")
        self.assertIn("Media duration is unknown", " ".join(result["qa"]["limitations"]))
        self.assertEqual(self.prepare(review, duration=4)["qa"]["readiness"], "blocked")

    def test_missing_or_ungrounded_required_evidence_needs_review(self):
        for name in checker.CHECK_NAMES:
            with self.subTest(name=name):
                review = self.review()
                review["checks"][name]["evidence"] = " "
                self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")
                del review["checks"][name]
                self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")

    def test_partial_coverage_or_wrong_identity_blocks(self):
        for name in ("coverage", "identity"):
            review = self.review()
            review["checks"][name]["status"] = "failed"
            self.assertEqual(self.prepare(review)["qa"]["readiness"], "blocked")

    def test_fidelity_or_timing_failure_requires_review(self):
        for name in ("fidelity", "timing"):
            review = self.review()
            review["checks"][name]["status"] = "failed"
            self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")

    def test_text_only_and_coherence_cannot_pass_fidelity(self):
        for basis in ("text_only", "coherence", "two_asr_agree", None):
            review = self.review()
            review["checks"]["fidelity"]["basis"] = basis
            self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")

    def test_time_span_alone_cannot_establish_coverage(self):
        review = self.review()
        review["checks"]["coverage"]["basis"] = "full_span"
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")

    def test_native_untimed_text_accepted_with_honest_limitations(self):
        path = self.root / "synthetic.txt"
        text = "\n\n原文😀保留。\n\n 第二段，不猜说话人。 \n\n"
        path.write_text(text, encoding="utf-8")
        package = self.prepare(path=path, kind="native")
        self.assertEqual("".join(item["text"] for item in package["segments"]), text)
        self.assertTrue(all(item["start_seconds"] is None for item in package["segments"]))
        review = self.review(package)
        review["checks"]["coverage"]["basis"] = "publisher_transcript"
        for name in ("fidelity", "timing"):
            review["checks"][name] = dict(status="unavailable", basis=None, evidence="No audio/timing reference available.")
        result = self.prepare(review, path=path, kind="native")
        self.assertEqual(result["qa"]["readiness"], "ready_with_limitations")
        self.assertIn("full audio coverage is not independently verified", " ".join(result["qa"]["limitations"]))

    def test_asr_or_mixed_without_fidelity_review_cannot_pass(self):
        for kind in ("asr", "mixed"):
            review = self.review()
            review["checks"]["fidelity"] = dict(status="unavailable", basis=None, evidence="Audio inaccessible.")
            self.assertEqual(self.prepare(review, kind=kind)["qa"]["readiness"], "needs_review")

    def test_untimed_text_cannot_claim_timing_passed(self):
        path = self.root / "synthetic.txt"
        path.write_text("原文", encoding="utf-8")
        review = self.review(self.prepare(path=path))
        self.assertEqual(self.prepare(review, path=path)["qa"]["readiness"], "needs_review")

    def test_vtt_headers_cue_id_multiline_settings_and_metadata(self):
        self.path = self.root / "synthetic.vtt"
        self.path.write_bytes(b"\xef\xbb\xbfWEBVTT test\r\nLanguage: zh\r\n\r\nNOTE source note\r\n\r\n"
                              b"cue-a\r\n00:00.000 --> 00:02.000 align:start\r\n<v A>Hello\r\nworld\r\n")
        result = self.prepare()
        self.assertFalse(result["qa"]["structural_errors"])
        self.assertEqual(result["segments"][0]["text"], "<v A>Hello\nworld")
        self.assertEqual(result["segments"][0]["source_cue_id"], "cue-a")
        self.assertEqual(len(result["metadata_blocks"]), 2)

    def test_multiple_blank_and_whitespace_only_cue_separators(self):
        for extension in ("srt", "vtt"):
            for separator in ("\n\n\n", "\n \n\t\n\n", "\n\t\n"):
                with self.subTest(extension=extension, separator=separator):
                    path = self.root / f"separators.{extension}"
                    text = SRT if extension == "srt" else "WEBVTT\n\n" + SRT.replace(",000", ".000")
                    path.write_text(text.replace("\n\n", separator), encoding="utf-8")
                    result = self.prepare(path=path)
                    self.assertFalse(result["qa"]["structural_errors"])
                    self.assertEqual(len(result["segments"]), 2)
                    self.assertEqual(result["segments"][0]["text"], "不是每次都增长。\n第二行保留。")

    def test_malformed_and_nonfinite_timestamps_fail_closed(self):
        variants = ("NaN", "inf", "00:00:99,000", "-00:00:01,000", "00:00:00.000", "0:0:0,0")
        for value in variants:
            with self.subTest(value=value):
                self.path.write_text(SRT.replace("00:00:00,000", value), encoding="utf-8")
                result = self.prepare()
                self.assertEqual(result["qa"]["readiness"], "blocked")
                self.assertTrue(result["qa"]["structural_errors"])

    def test_malformed_or_missing_separator_block_is_not_skipped(self):
        for text in (SRT + "\nnot a cue\n", SRT.replace("\n\n2\n", "\n2\n")):
            self.path.write_text(text, encoding="utf-8")
            self.assertEqual(self.prepare()["qa"]["readiness"], "blocked")

    def test_invalid_interval_and_reversed_order_and_bounds(self):
        texts = (SRT.replace("00:00:02,000", "00:00:00,000", 1),
                 SRT.replace("00:00:02,000 -->", "00:00:00,000 -->").replace("00:00:00,000 -->", "00:00:01,000 -->", 1),
                 SRT.replace("00:00:04,000", "00:00:05,000"))
        for text in texts:
            self.path.write_text(text, encoding="utf-8")
            self.assertEqual(self.prepare()["qa"]["readiness"], "blocked")

    def test_invalid_duration_cannot_generate_nonfinite_json(self):
        for value in (math.nan, math.inf, -1, 0, True):
            result = self.prepare(duration=value)
            self.assertEqual(result["qa"]["readiness"], "blocked")
            json.dumps(result, allow_nan=False)

    def test_repetition_duplicate_source_ids_and_gaps_are_diagnostics_only(self):
        self.path.write_text("1\n00:00:00,000 --> 00:00:01,000\nYes.\n\n1\n00:00:03,000 --> 00:00:04,000\nYes.\n", encoding="utf-8")
        result = self.prepare(self.review())
        self.assertEqual(result["qa"]["readiness"], "ready")
        self.assertEqual({item["type"] for item in result["qa"]["diagnostics"]},
                         {"repeated_text", "duplicate_cue_id", "uncovered_interval"})
        self.assertNotEqual(result["segments"][0]["id"], result["segments"][1]["id"])

    def test_legitimate_overlap_needs_review_and_can_be_accepted(self):
        self.path.write_text(SRT.replace("00:00:02,000 -->", "00:00:01,000 -->"), encoding="utf-8")
        package = self.prepare()
        self.assertEqual(package["qa"]["readiness"], "needs_review")
        self.assertIn("overlap", {item["type"] for item in package["qa"]["diagnostics"]})
        review = self.review(package)
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "ready")
        review["checks"]["timing"] = dict(status="unavailable", evidence="Not checked.", basis=None)
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")

    def test_empty_cue_is_preserved_but_requires_review(self):
        self.path.write_text("1\n00:00:00,000 --> 00:00:02,000\n\n2\n00:00:02,000 --> 00:00:04,000\nValid.\n", encoding="utf-8")
        result = self.prepare(self.review())
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["qa"]["readiness"], "needs_review")

    def test_malformed_statuses_and_issues_fail_closed(self):
        variants = []
        for value in ("done", [], None):
            review = self.review()
            review["checks"]["identity"]["status"] = value
            variants.append(review)
        review = self.review()
        review["issues"] = [dict(id="test", type="gap", severity="critical", status="fixed",
                                segment_ids=[], reason="test", evidence=None)]
        variants.append(review)
        for review in variants:
            self.assertEqual(self.prepare(review)["qa"]["readiness"], "blocked")

    def test_open_critical_and_unsupported_resolution_require_review(self):
        review = self.review()
        issue = dict(id="test", type="negation", severity="critical", status="open",
                     segment_ids=[self.prepare()["segments"][0]["id"]], reason="Possible missing negation.", evidence=None)
        review["issues"] = [issue]
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")
        issue["status"] = "resolved"
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "needs_review")
        issue["evidence"] = "Synthetic audio checked; negation is present."
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "ready")
        issue["segment_ids"] = ["nonexistent"]
        self.assertEqual(self.prepare(review)["qa"]["readiness"], "blocked")

    def test_cli_atomic_output_exit_codes_and_input_protection(self):
        review_path = self.root / "review.json"
        review_path.write_text(json.dumps(self.review()), encoding="utf-8")
        original, original_review = self.path.read_bytes(), review_path.read_bytes()
        output = self.root / "prepared.json"
        base = [str(self.path), "--source-version", "synthetic-media-v1", "--kind", "asr", "--duration", "4"]
        for options, expected in (([], 1), (["--review", str(review_path), "--output", str(output)], 0),
                                  (["--review", str(review_path), "--output", str(self.path)], 2),
                                  (["--review", str(review_path), "--output", str(review_path)], 2)):
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(checker.main(base + options), expected)
            json.loads(stream.getvalue())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(review_path.read_bytes(), original_review)
        self.assertEqual(json.loads(output.read_text())["qa"]["readiness"], "ready")

    def test_atomic_failure_leaves_previous_package_and_no_temporary_files(self):
        output = self.root / "prepared.json"
        output.write_text("previous", encoding="utf-8")
        with patch.object(checker.os, "replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                checker.write_atomic(output, self.prepare(), [self.path])
        self.assertEqual(output.read_text(), "previous")
        self.assertFalse(list(self.root.glob(".transcript-*")))

    def test_null_malformed_and_stale_json_review_cli_blocks(self):
        review_path = self.root / "review.json"
        for text in ("null", "{broken", '{"input_review": null}'):
            review_path.write_text(text)
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                result = checker.main([str(self.path), "--source-version", "synthetic-media-v1", "--kind", "asr", "--review", str(review_path)])
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(stream.getvalue())["qa"]["readiness"], "blocked")

    def test_review_json_rejects_duplicate_keys_and_nonfinite_values(self):
        review_path = self.root / "review.json"
        valid = json.dumps(self.review())
        variants = [valid.replace('"status": "passed"', '"status": "failed", "status": "passed"', 1),
                    valid.replace('"media_duration_seconds": 4', '"media_duration_seconds": 7200, "media_duration_seconds": 4')]
        variants += [valid[:-1] + ', "ignored": ' + number + '}'
                     for number in ("NaN", "Infinity", "-Infinity", "1e999")]
        for text in variants:
            with self.subTest(text=text):
                review_path.write_text(text, encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()) as stream:
                    result = checker.main([str(self.path), "--source-version", "synthetic-media-v1",
                                           "--kind", "asr", "--duration", "4", "--review", str(review_path)])
                self.assertEqual(result, 2)
                package = json.loads(stream.getvalue())
                self.assertEqual(package["qa"]["readiness"], "blocked")
                self.assertIn("Cannot read review", " ".join(package["qa"]["structural_errors"]))


if __name__ == "__main__":
    unittest.main()
