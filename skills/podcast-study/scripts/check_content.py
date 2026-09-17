#!/usr/bin/env python3
"""Validate source-bound reading content and review records before publication.

Standard library only. This verifies structure and recorded assessments, not the
truth of a model's assessment. No model calls, web requests or personal notes.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import sys
from urllib.parse import urlsplit

from check_transcript import BASES, read_review, write_atomic

OUTLINE_CHECKS = ("faithfulness", "coverage", "structure")
FINAL_CHECKS = OUTLINE_CHECKS + ("attribution", "consistency", "citation_support")
QUALITY = ("overview", "understanding", "organization", "concision")
ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
HEX = re.compile(r"[a-f0-9]{64}\Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def records(value, label, empty=False):
    require(isinstance(value, list) and (empty or bool(value)), f"{label}: expected {'a' if empty else 'a nonempty'} list")
    result = {}
    for row in value:
        require(isinstance(row, dict) and isinstance(row.get("id"), str) and ID.fullmatch(row["id"]), f"{label}: invalid ID")
        require(row["id"] not in result, f"{label}: duplicate ID {row['id']}")
        result[row["id"]] = row
    return result


def references(value, known, label, empty=False):
    require(isinstance(value, list) and (empty or bool(value)), f"{label}: missing references")
    require(all(isinstance(item, str) and item in known for item in value), f"{label}: unknown reference")
    require(len(set(value)) == len(value), f"{label}: duplicate reference")
    return value


def validate_structure(draft, transcript, stage):
    require(isinstance(draft, dict) and isinstance(transcript, dict), "Expected content and transcript objects")
    require(type(draft.get("schema_version")) is int and draft["schema_version"] == 1, "Unsupported content schema")
    require(type(transcript.get("schema_version")) is int and transcript["schema_version"] == 1,
            "Unsupported transcript schema")
    require(transcript.get("offset_unit", "unicode_codepoint") == "unicode_codepoint", "Unsupported source offset unit")
    require(not (set(draft) - {"schema_version", "episode", "source", "citations", "nodes", "coverage", "summary", "questions"}),
            "Unknown content fields; personal notes must be stored separately")
    episode = draft.get("episode")
    require(isinstance(episode, dict) and isinstance(episode.get("id"), str) and ID.fullmatch(episode["id"])
            and nonempty(episode.get("title")), "Invalid episode identity/title")
    require(type(episode.get("demo", False)) is bool, "episode.demo must be a boolean")
    require("subtitle" not in episode or isinstance(episode["subtitle"], str), "episode.subtitle must be text")
    require(transcript.get("qa", {}).get("readiness") in {"ready", "ready_with_limitations"}, "Transcript has not passed input checks")
    require(transcript["qa"].get("structural_errors", []) == [], "Transcript still has structural errors")
    require(transcript.get("time_precision") in {"cue", "segment_start", "unavailable"}, "Unknown time precision")
    limitations = transcript.get("qa", {}).get("limitations", [])
    require(isinstance(limitations, list) and all(nonempty(item) for item in limitations), "Invalid source limitations")
    segments = records(transcript.get("segments"), "segments")
    require(all(nonempty(row.get("text")) for row in segments.values()), "Empty source text")
    duration = transcript.get("media_duration_seconds")
    require(duration is None or (type(duration) in {int, float} and math.isfinite(duration) and duration > 0),
            "Invalid media duration")
    previous_start = -1
    for row in segments.values():
        start, end = row.get("start_seconds"), row.get("end_seconds")
        for value in (start, end):
            require(value is None or (type(value) in {int, float} and math.isfinite(value) and value >= 0),
                    "Source times must be finite nonnegative numbers or null")
        require(end is None or (start is not None and end > start), "Source end must follow its start")
        require(transcript["time_precision"] == "unavailable" or start is not None,
                "Declared source precision requires a start time for every segment")
        require(transcript["time_precision"] != "cue" or end is not None,
                "Cue precision requires an end time for every segment")
        if start is not None:
            require(start >= previous_start, "Source start times move backwards")
            previous_start = start
        require(duration is None or all(value is None or value <= duration for value in (start, end)),
                "Source time exceeds media duration")
    source = draft.get("source")
    require(isinstance(source, dict), "Missing source binding")
    if "url" in source:
        require(isinstance(source["url"], str), "Source URL must be text")
        url = urlsplit(source["url"])
        require(url.scheme in {"http", "https"} and bool(url.hostname)
                and not url.username and not url.password
                and not any(c.isspace() for c in source["url"]), "Invalid source URL")
    for key in ("label", "reading_note"):
        require(key not in source or nonempty(source[key]), f"Source {key} must be text")
    for key in ("source_version_id", "transcript_sha256"):
        require(nonempty(transcript.get(key)) and source.get(key) == transcript[key], f"Source {key} mismatch")
    require(HEX.fullmatch(source["transcript_sha256"]), "Invalid transcript hash")
    citations = records(draft.get("citations"), "citations")
    positions, numbers = set(), set()
    for citation in citations.values():
        number = citation.get("number")
        require(type(number) is int and 1 <= number <= 1000000 and number not in numbers,
                "Citation needs a unique persistent display number")
        numbers.add(number)
        sid, start, end = (citation.get(key) for key in ("segment_id", "start", "end"))
        require(isinstance(sid, str) and sid in segments, f"Citation {citation['id']}: unknown source")
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(segments[sid]["text"]),
                f"Citation {citation['id']}: invalid Unicode codepoint range")
        require(citation.get("quote") == segments[sid]["text"][start:end], f"Citation {citation['id']}: quote mismatch")
        key = sid, start, end
        require(key not in positions, "The same source span must reuse one citation ID")
        positions.add(key)
    nodes = records(draft.get("nodes"), "nodes")
    kinds = {1: {"topic"}, 2: {"claim"}, 3: {"reason", "example", "condition", "explanation"}}
    for node in nodes.values():
        level = node.get("level")
        require(type(level) is int and level in kinds and node.get("kind") in kinds[level], f"Node {node['id']}: invalid level/kind")
        require(nonempty(node.get("title")) and nonempty(node.get("text")), f"Node {node['id']}: missing explanation")
        references(node.get("citation_ids"), citations, f"Node {node['id']} citations")
        if level == 1:
            require("parent_id" in node and node["parent_id"] is None, "Topics must explicitly be roots")
        else:
            parent = nodes.get(node.get("parent_id")) if isinstance(node.get("parent_id"), str) else None
            require(parent is not None and parent.get("level") == level - 1, f"Node {node['id']}: invalid parent")
    topics = {key: node for key, node in nodes.items() if node["level"] == 1}
    claims = {key: node for key, node in nodes.items() if node["level"] == 2}
    require(topics and claims, "Need topics and substantive claims")
    for topic in topics:
        require(any(n["parent_id"] == topic for n in claims.values()), f"Topic {topic}: no claims")

    def topic_of(node_id):
        node = nodes[node_id]
        while node["level"] > 1:
            node = nodes[node["parent_id"]]
        return node["id"]

    evidence_by_topic = {key: set() for key in topics}
    for node in nodes.values():
        evidence_by_topic[topic_of(node["id"])].update(citations[c]["segment_id"] for c in node["citation_ids"])
    coverage = draft.get("coverage")
    require(isinstance(coverage, list), "Missing whole-source coverage map")
    seen = set()
    for row in coverage:
        require(isinstance(row, dict) and isinstance(row.get("segment_id"), str), "Invalid coverage record")
        sid = row["segment_id"]
        require(sid in segments and sid not in seen, "Unknown or duplicate coverage segment")
        seen.add(sid)
        if row.get("disposition") == "covered":
            ids = references(row.get("topic_ids"), topics, "Coverage topics")
            require(all(sid in evidence_by_topic[topic] for topic in ids), f"Coverage {sid}: no topic evidence")
        else:
            require(row.get("disposition") == "omitted" and nonempty(row.get("reason"))
                    and row.get("topic_ids") == [], f"Coverage {sid}: omission needs a reason")
    require(seen == set(segments), "Coverage map must account for every source segment")
    targets = dict(nodes)
    if stage == "outline":
        return segments, targets

    def add_target(row):
        require(row["id"] not in targets, "Output IDs must be unique across sections")
        targets[row["id"]] = row

    def block(row):
        add_target(row)
        require(nonempty(row.get("text")), f"Block {row['id']}: missing text")
        attribution = row.get("attribution")
        require(attribution in {"source", "ai_inference", "editor_example"}, f"Block {row['id']}: invalid attribution")
        references(row.get("claim_ids"), claims, f"Block {row['id']} claims")
        references(row.get("citation_ids"), citations, f"Block {row['id']} citations", empty=attribution == "editor_example")
        return {topic_of(cid) for cid in row["claim_ids"]}

    summary = records(draft.get("summary"), "summary")
    summary_topics = set()
    for row in summary.values():
        require(nonempty(row.get("title")), "Summary section needs a title")
        summary_topics.update(block(row))
    require(summary_topics == set(topics), "Summary must represent each main topic")
    questions = records(draft.get("questions"), "questions")
    for row in questions.values():
        add_target(row)
        require(nonempty(row.get("question")), "Missing question")
        ids = references(row.get("topic_ids"), topics, "Question topics")
        actual_topics = set()
        for answer in records(row.get("answer"), "answer").values():
            actual_topics.update(block(answer))
        require(set(ids) == actual_topics, "Question topics must match the answer's claim references")
    return segments, targets


def check_assessment(assessment, expected_hash, source_hash, checks, segments, targets, final, requests, legacy_hash=None):
    if assessment is None:
        requests.append("Missing final review" if final else "Missing outline review")
        return
    require(isinstance(assessment, dict), "Review must be an object")
    require((assessment.get("content_sha256") == expected_hash
             or (legacy_hash is not None and assessment.get("content_sha256") == legacy_hash))
            and assessment.get("transcript_package_sha256") == source_hash,
            "Review is stale or bound to a different content/source version")
    require(assessment.get("method") in {"independent_call", "human", "separate_review"}, "Record actual review method")
    reviewed = references(assessment.get("reviewed_segment_ids"), segments, "Reviewed source segments")
    require(set(reviewed) == set(segments), "Review must account for the whole source, not only selected citations")
    values = assessment.get("checks")
    require(isinstance(values, dict) and set(values) == set(checks), "Missing/unknown review criteria")
    for name in checks:
        item = values[name]
        require(isinstance(item, dict) and item.get("status") in {"passed", "failed", "uncertain"}, f"Invalid {name} assessment")
        if item["status"] != "passed" or not nonempty(item.get("evidence")):
            requests.append(f"{name}: not passed with evidence")
    points = assessment.get("essential_points")
    require(isinstance(points, list) and points, "Independent review needs essential points from the source")
    for point in points:
        require(isinstance(point, dict) and nonempty(point.get("text")), "Invalid essential point")
        references(point.get("segment_ids"), segments, "Essential point source")
        references(point.get("output_ids"), targets, "Essential point output", empty=True)
        require(point.get("status") in {"covered", "missing", "uncertain"}, "Invalid essential point status")
        if point["status"] != "covered" or not point["output_ids"] or not nonempty(point.get("reason")):
            requests.append("Important source point is missing or uncertain: " + point["text"])
    issues = assessment.get("issues")
    require(isinstance(issues, list), "Review issues must be a list")
    for issue in issues:
        require(isinstance(issue, dict) and issue.get("severity") in {"major", "minor"}
                and issue.get("status") in {"open", "resolved"} and nonempty(issue.get("reason")), "Malformed review issue")
        references(issue.get("output_ids"), targets, "Issue output", empty=True)
        references(issue.get("segment_ids"), segments, "Issue source", empty=True)
        if issue["status"] == "resolved":
            require(nonempty(issue.get("resolution")), "Resolved issue lacks repair evidence")
        elif issue["severity"] == "major":
            requests.append("Unresolved major issue: " + issue["reason"])
    if final:
        scores = assessment.get("quality")
        require(isinstance(scores, dict) and set(scores) == set(QUALITY), "Missing/unknown reading quality dimensions")
        for name in QUALITY:
            item = scores[name]
            require(isinstance(item, dict) and type(item.get("score")) is int and 0 <= item["score"] <= 3
                    and nonempty(item.get("reason")), f"Invalid {name} score/reason")
            if item["score"] < 2:
                requests.append(f"{name}: below publishable level 2")


def evaluate(draft, transcript, review=None, stage="final"):
    report = {"stage": stage, "readiness": "blocked", "digests": {}, "errors": [], "review_requests": [],
              "limitation": "Checks validate structure and recorded evidence; they do not certify semantic truth or run a model."}
    try:
        require(stage in {"outline", "final"}, "Invalid stage")
        segments, targets = validate_structure(draft, transcript, stage)
        core = {key: draft[key] for key in ("schema_version", "episode", "source", "citations", "nodes", "coverage")}
        # Legacy reviews remain valid only against the current complete core.
        # New outline reviews bind all node evidence, not prose-only citations.
        legacy_outline_hash = digest(core)
        outline_citations = {cid for node in draft["nodes"] for cid in node["citation_ids"]}
        core["citations"] = [row for row in draft["citations"] if row["id"] in outline_citations]
        hashes = {"outline": digest(core), "final": digest(draft), "transcript_package": digest(transcript)}
        report["digests"] = hashes
        if review is None:
            review = {}
        require(isinstance(review, dict), "Review must be an object")
        outline_targets = {row["id"]: row for row in draft["nodes"]}
        check_assessment(review.get("outline"), hashes["outline"], hashes["transcript_package"],
                         OUTLINE_CHECKS, segments, outline_targets, False, report["review_requests"], legacy_outline_hash)
        if stage == "final":
            check_assessment(review.get("final"), hashes["final"], hashes["transcript_package"],
                             FINAL_CHECKS, segments, targets, True, report["review_requests"])
        report["readiness"] = "needs_review" if report["review_requests"] else "ready"
    except (Invalid, TypeError, KeyError, ValueError, OverflowError, AttributeError, RecursionError) as error:
        report["errors"].append(str(error))
    return report


def publication(draft, transcript, report):
    require(report["stage"] == "final" and report["readiness"] == "ready", "Only accepted final content can be published")
    require(report.get("digests", {}).get("final") == digest(draft)
            and report.get("digests", {}).get("transcript_package") == digest(transcript),
            "Content or source changed after acceptance; review again before publication")
    precision = transcript.get("time_precision", "unavailable")
    checks = transcript.get("qa", {}).get("checks", {})
    timing = checks.get("timing", {}) if isinstance(checks, dict) else {}
    timing_verified = (isinstance(timing, dict) and timing.get("status") == "passed"
                       and isinstance(timing.get("basis"), str) and timing["basis"] in BASES["timing"]
                       and nonempty(timing.get("evidence")))
    limitations = list(transcript.get("qa", {}).get("limitations", []))
    if precision != "unavailable" and not timing_verified:
        precision = "unavailable"
        limitations.append("Source timestamps are retained but unverified; navigate by original text only.")
    return {"schema_version": 1, "revision": report["digests"]["final"], "episode": draft["episode"],
            "source": {**draft["source"], "offset_unit": "unicode_codepoint", "segments": transcript["segments"],
                       "time_precision": precision, "limitations": limitations},
            "summary": draft["summary"], "nodes": draft["nodes"], "questions": draft["questions"], "citations": draft["citations"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content", type=Path)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--stage", choices=("outline", "final"), default="final")
    parser.add_argument("--publish", type=Path, help="Atomically replace the site's episode.json only after final acceptance")
    args = parser.parse_args(argv)
    protected = [args.content, args.transcript] + ([args.review] if args.review else [])
    try:
        draft, transcript = read_review(args.content), read_review(args.transcript)
        report = evaluate(draft, transcript, read_review(args.review) if args.review else None, args.stage)
        if args.publish:
            if report["readiness"] == "ready" and args.stage == "final":
                write_atomic(args.publish, publication(draft, transcript, report), protected)
                report["published"] = str(args.publish)
            else:
                report["errors"].append("Previous published file preserved; final acceptance is required")
                report["readiness"] = "blocked"
        code = {"ready": 0, "needs_review": 1, "blocked": 2}[report["readiness"]]
        if args.publish and "published" not in report:
            code = max(code, 2)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        report, code = {"readiness": "blocked", "errors": [str(error)]}, 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
