#!/usr/bin/env python3
"""Preserve a local transcript and gate recorded evidence; never listen or infer text."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile


CHECK_NAMES = ("identity", "coverage", "fidelity", "timing")
STATUSES = {"pending", "passed", "failed", "unavailable"}
BASES = {
    "identity": {"metadata", "publisher_transcript", "audio_review", "human_reference"},
    "coverage": {"publisher_transcript", "audio_review", "human_reference"},
    "fidelity": {"audio", "audio_review", "human_reference"},
    "timing": {"publisher_timestamps", "alignment_review", "audio", "audio_review", "human_reference"},
}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def timestamp(value, fmt):
    pattern = r"\d{2,}:[0-5]\d:[0-5]\d,\d{3}" if fmt == "srt" else r"(?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3}"
    if not re.fullmatch(pattern, value):
        raise ValueError(f"Invalid {fmt.upper()} timestamp: {value!r}")
    fields = value.replace(",", ".").split(":")
    seconds = float(fields[-1]) + 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[0])
    if not math.isfinite(seconds):
        raise ValueError("Non-finite timestamp")
    return seconds


def parse_transcript(raw, fmt):
    """Only normalize UTF-8 BOM and line endings; retain cue payload verbatim."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise ValueError("NUL bytes are not supported; supply a UTF-8 transcript")
    if not text.strip():
        raise ValueError("Transcript is empty")
    if fmt == "txt":
        # Keep paragraph separators as part of each segment so concatenation is lossless.
        parts = re.split(r"(\n[ \t]*\n+)", text)
        paragraphs, prefix = [], ""
        for i in range(0, len(parts), 2):
            chunk = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
            if chunk.strip():
                paragraphs.append(prefix + chunk)
                prefix = ""
            elif paragraphs:
                paragraphs[-1] += chunk
            else:
                prefix += chunk
        return [dict(text=paragraph, start_seconds=None, end_seconds=None, source_cue_id=None)
                for paragraph in paragraphs], []
    if fmt not in {"srt", "vtt"}:
        raise ValueError("Supported file extensions are .srt, .vtt and .txt")
    blocks = re.split(r"\n(?:[ \t]*\n)+", text.strip("\n"))
    metadata = []
    if fmt == "vtt":
        header = blocks.pop(0)
        if not re.match(r"^WEBVTT(?:[ \t][^\n]*)?(?:\n|$)", header):
            raise ValueError("VTT must start with a WEBVTT header and blank separator")
        if "-->" in header:
            raise ValueError("VTT header must be separated from cues by a blank line")
        metadata.append(header)
    segments = []
    for block_number, block in enumerate(blocks, 1):
        if not block.strip():
            continue
        lines = block.split("\n")
        if fmt == "vtt" and re.match(r"^(?:NOTE(?:[ \t]|$)|STYLE$|REGION$)", lines[0]):
            if "-->" in block:
                raise ValueError(f"Block {block_number}: cue found inside metadata")
            metadata.append(block)
            continue
        cue_id = None
        if "-->" not in lines[0]:
            cue_id = lines.pop(0)
            if not cue_id.strip() or (fmt == "srt" and not cue_id.isdigit()):
                raise ValueError(f"Block {block_number}: invalid cue identifier")
        if not lines:
            raise ValueError(f"Block {block_number}: missing timing line")
        timing = re.fullmatch(r"([^\s]+)[ \t]+-->[ \t]+([^\s]+)(?:[ \t]+(.*))?", lines.pop(0))
        if not timing:
            raise ValueError(f"Block {block_number}: malformed timing line")
        if fmt == "srt" and timing.group(3):
            raise ValueError(f"Block {block_number}: unexpected SRT timing suffix")
        start, end = (timestamp(timing.group(i), fmt) for i in (1, 2))
        if end <= start:
            raise ValueError(f"Block {block_number}: end must be after start")
        # SRT dialogue may contain a literal arrow ("A --> B"). Only a
        # timestamp-shaped line is evidence of a lost cue separator.
        nested = (r"\d{2,}:\d{2}:\d{2},\d{3}[ \t]+-->[ \t]+\S+"
                  if fmt == "srt" else r"\S+[ \t]+-->[ \t]+\S+")
        if any(re.match(nested, line) for line in lines):
            raise ValueError(f"Block {block_number}: nested cue; missing blank separator")
        segment = dict(text="\n".join(lines), start_seconds=start, end_seconds=end,
                       source_cue_id=cue_id)
        if timing.group(3):
            segment["cue_settings"] = timing.group(3)
        segments.append(segment)
    if not segments:
        raise ValueError("Transcript contains no cues")
    return segments, metadata


def review_evidence(review, package, qa):
    """Validate supplied claims and bind them to these bytes, not an older revision."""
    if review is None:
        qa["limitations"].append("No bound identity, coverage, fidelity or timing review supplied.")
        return False, False, True
    if not isinstance(review, dict):
        qa["structural_errors"].append("Review must be an object")
        return True, False, True
    if "input_review" in review:
        review = review["input_review"]
    if not isinstance(review, dict):
        qa["structural_errors"].append("input_review must be an object")
        return True, False, True
    for key in ("source_version_id", "transcript_sha256"):
        if review.get(key) != package[key]:
            qa["structural_errors"].append(f"Review {key} is missing or does not match this input")
    reviewed_duration = review.get("media_duration_seconds")
    if ("media_duration_seconds" not in review
            or (reviewed_duration is not None and
                (isinstance(reviewed_duration, bool) or not isinstance(reviewed_duration, (int, float))
                 or not math.isfinite(reviewed_duration) or reviewed_duration <= 0))
            or reviewed_duration != package["media_duration_seconds"]):
        qa["structural_errors"].append("Review media_duration_seconds is invalid, missing or does not match this input")
    if qa["structural_errors"]:
        return True, False, True
    checks = review.get("checks", {})
    issues = review.get("issues", [])
    if not isinstance(checks, dict) or not isinstance(issues, list):
        qa["structural_errors"].append("Review checks must be an object and issues must be a list")
        return True, False, True
    unknown = set(checks) - set(CHECK_NAMES)
    if unknown:
        qa["structural_errors"].append(f"Unknown review check names: {sorted(unknown)}")
    blocked, limited, pending = False, False, False
    for name in CHECK_NAMES:
        check = checks.get(name, {"status": "pending", "evidence": None, "basis": None})
        if (not isinstance(check, dict) or not isinstance(check.get("status"), str)
                or check["status"] not in STATUSES):
            qa["structural_errors"].append(f"Invalid {name} check/status")
            continue
        if any(check.get(key) is not None and not isinstance(check.get(key), str)
               for key in ("evidence", "basis")):
            qa["structural_errors"].append(f"{name} evidence/basis must be text or null")
            continue
        qa["checks"][name] = {key: check.get(key) for key in ("status", "evidence", "basis")}
        status, basis = check["status"], check.get("basis")
        grounded = nonempty(check.get("evidence"))
        if status == "failed":
            blocked |= name in {"identity", "coverage"}
            pending = True
        elif status == "pending" or not grounded:
            pending = True
            qa["limitations"].append(f"{name}: pending or missing evidence/explanation.")
        elif status == "unavailable":
            if name in {"identity", "coverage"} or (name == "fidelity" and package["kind"] != "native"):
                pending = True
            limited = True
            qa["limitations"].append(f"{name} unavailable: {check['evidence']}")
        elif basis not in BASES[name]:
            pending = True
            qa["limitations"].append(f"{name}: basis {basis!r} cannot establish a passed check.")
        elif name == "timing" and package["time_precision"] == "unavailable":
            pending = True
            qa["limitations"].append("Untimed text cannot have a passed timestamp check; record timing unavailable.")
        elif name == "coverage" and basis == "publisher_transcript":
            limited = True
            qa["limitations"].append("Publisher transcript coverage recorded; full audio coverage is not independently verified.")
    ids, issue_ids = {segment["id"] for segment in package["segments"]}, set()
    for issue in issues:
        if (not isinstance(issue, dict) or not nonempty(issue.get("id"))
                or issue["id"] in issue_ids or not nonempty(issue.get("type"))
                or not isinstance(issue.get("severity"), str)
                or issue["severity"] not in {"critical", "warning"}
                or not isinstance(issue.get("status"), str)
                or issue["status"] not in {"open", "resolved"}
                or not nonempty(issue.get("reason"))
                or not isinstance(issue.get("segment_ids"), list)
                or any(not isinstance(item, str) or item not in ids for item in issue.get("segment_ids", []))
                or (issue.get("evidence") is not None and not isinstance(issue.get("evidence"), str))):
            qa["structural_errors"].append("Malformed issue, duplicate issue ID or unknown segment ID")
            continue
        issue_ids.add(issue["id"])
        qa["issues"].append(issue)
        if issue["status"] == "open":
            pending |= issue["severity"] == "critical"
            limited = True
        elif not nonempty(issue.get("evidence")):
            pending = True
            qa["limitations"].append(f"Resolved issue {issue['id']} lacks resolution evidence.")
    if any(item["type"] == "overlap" for item in qa["diagnostics"]):
        timing = qa["checks"].get("timing", {})
        if timing.get("status") != "passed" or timing.get("basis") not in BASES["timing"] or not nonempty(timing.get("evidence")):
            pending = True
            qa["limitations"].append("Overlapping cues need a recorded timing review; concurrent speech can be valid.")
    return blocked, limited, pending


def prepare(path, source_version_id, kind, duration=None, review=None):
    qa = dict(readiness="blocked", structural_errors=[], diagnostics=[],
              checks={name: dict(status="pending", evidence=None, basis=None) for name in CHECK_NAMES}, issues=[],
              limitations=["This tool does not inspect audio. Readiness is not proof of completeness or zero hallucinations."])
    package = dict(schema_version=1, source_version_id=source_version_id, transcript_sha256=None,
                   kind=kind, format=Path(path).suffix.lower().lstrip("."), time_precision="unavailable",
                   offset_unit="unicode_codepoint", media_duration_seconds=duration, segments=[], qa=qa)
    try:
        if not nonempty(source_version_id) or not isinstance(kind, str) or kind not in {"native", "asr", "mixed"}:
            raise ValueError("A nonempty source version and kind native/asr/mixed are required")
        if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float))
                                     or not math.isfinite(duration) or duration <= 0):
            package["media_duration_seconds"] = None
            raise ValueError("Duration must be a finite positive number")
        raw = Path(path).read_bytes()
        package["transcript_sha256"] = hashlib.sha256(raw).hexdigest()
        segments, metadata = parse_transcript(raw, package["format"])
        if metadata:
            package["metadata_blocks"] = metadata
        prefix = hashlib.sha256((source_version_id + "\0" + package["transcript_sha256"]).encode()).hexdigest()[:24]
        seen_ids, seen_text = {}, {}
        previous_start, farthest_end = -1, 0
        for i, segment in enumerate(segments, 1):
            segment["id"] = f"seg_{prefix}_{i:06d}"
            segment_id = segment["id"]
            package["segments"].append(segment)
            if not segment["text"].strip():
                qa["diagnostics"].append(dict(type="empty_text", segment_ids=[segment_id]))
            cue_id = segment["source_cue_id"]
            if cue_id is not None and cue_id in seen_ids:
                qa["diagnostics"].append(dict(type="duplicate_cue_id", segment_ids=[seen_ids[cue_id], segment_id]))
            if cue_id is not None:
                seen_ids[cue_id] = segment_id
            payload = segment["text"].strip()
            if payload and payload in seen_text:
                qa["diagnostics"].append(dict(type="repeated_text", segment_ids=[seen_text[payload], segment_id]))
            seen_text[payload] = segment_id
            start, end = segment["start_seconds"], segment["end_seconds"]
            if start is None:
                continue
            package["time_precision"] = "cue"
            if start < previous_start:
                qa["structural_errors"].append(f"{segment_id}: cue start time moves backwards")
            if duration is not None and end > duration:
                qa["structural_errors"].append(f"{segment_id}: timestamp exceeds supplied media duration")
            if start < farthest_end:
                qa["diagnostics"].append(dict(type="overlap", segment_ids=[segment_id],
                                               start_seconds=start, end_seconds=min(end, farthest_end)))
            elif start > farthest_end:
                qa["diagnostics"].append(dict(type="uncovered_interval", start_seconds=farthest_end, end_seconds=start))
            previous_start, farthest_end = start, max(farthest_end, end)
        if package["time_precision"] == "cue" and duration is not None and farthest_end < duration:
            qa["diagnostics"].append(dict(type="uncovered_interval", start_seconds=farthest_end, end_seconds=duration))
        if package["time_precision"] == "unavailable":
            qa["limitations"].append("No timestamps available; do not infer exact listening positions.")
        blocked, limited, pending = review_evidence(review, package, qa)
        if package["time_precision"] == "cue" and duration is None:
            limited = True
            qa["limitations"].append("Media duration is unknown; timestamp upper bounds and trailing coverage cannot be checked.")
        if any(item["type"] == "empty_text" for item in qa["diagnostics"]):
            pending = True
            qa["limitations"].append("Empty text segments require source inspection; no text was invented to fill them.")
        if qa["structural_errors"] or blocked:
            qa["readiness"] = "blocked"
        elif pending:
            qa["readiness"] = "needs_review"
        else:
            qa["readiness"] = "ready_with_limitations" if limited else "ready"
    except (OSError, UnicodeError, ValueError, OverflowError) as error:
        qa["structural_errors"].append(str(error))
    return package


def write_atomic(destination, package, protected):
    destination = Path(destination)
    for source in protected:
        if destination.resolve() == Path(source).resolve() or (destination.exists() and os.path.samefile(destination, source)):
            raise ValueError("Output must not overwrite transcript or review input")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".transcript-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(package, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_review(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON object key: {key}")
            result[key] = value
        return result

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"Non-finite JSON number: {value}")
        return result

    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object,
                      parse_constant=finite_float, parse_float=finite_float)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--kind", required=True, choices=("native", "asr", "mixed"))
    parser.add_argument("--duration", type=float)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    review, review_error = None, None
    if args.review:
        try:
            review = read_review(args.review)
            if review is None:
                raise ValueError("Review file cannot be null")
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            review_error = str(error)
    package = prepare(args.transcript, args.source_version, args.kind, args.duration, review)
    if review_error:
        package["qa"]["structural_errors"].append(f"Cannot read review: {review_error}")
        package["qa"]["readiness"] = "blocked"
    if args.output:
        try:
            write_atomic(args.output, package, [args.transcript] + ([args.review] if args.review else []))
        except (OSError, ValueError) as error:
            package["qa"]["structural_errors"].append(f"Cannot save output: {error}")
            package["qa"]["readiness"] = "blocked"
    print(json.dumps(package, ensure_ascii=False, indent=2, allow_nan=False))
    return {"ready": 0, "ready_with_limitations": 0, "needs_review": 1, "blocked": 2}[package["qa"]["readiness"]]


if __name__ == "__main__":
    sys.exit(main())
