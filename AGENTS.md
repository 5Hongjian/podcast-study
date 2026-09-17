# Repository instructions

Maintain the portable podcast-study skill and its public support files. Follow the iteration and versioning rules below.

- Never copy user profile data, episode records, media, transcripts, private document URLs, credentials, or machine-specific paths into this repository. Only the empty run template and synthetic evaluation cases belong here.
- Use the fixed website content and layout rules. Do not load, create, or maintain personal content or layout override files. Skill upgrades must preserve run records, source archives, personal notes, and unrelated existing state.
- Preserve the native-transcript-first decision and the order: publish the website, verify, then move eligible temporary files to system trash.
- Do not run an actual podcast, download models, or publish episode content when asked only to maintain this skill.
- Use a `codex/` branch for further iterations. Run the repository validator and installer tests before publishing relevant changes. Do not claim behavioral evaluation or live website verification unless actually performed.
- Keep changes bounded. Do not introduce a scheduler, multi-agent runtime, or cloud transcription dependency without a task that needs it.

## Iteration and versioning

Start each iteration from the latest `main` on a new `codex/<change-name>` branch in this repository. Record one concrete problem and its acceptance criteria in an issue or local note; use only synthetic or explicitly permitted minimal examples in public material. Do not turn a one-off preference into a universal skill restriction.

Run `python3 scripts/validate.py` and `python3 -m unittest discover -s tests -v`, and select relevant behavioral scenarios from [the evaluation cases](docs/evaluation-cases.md). Installer changes must verify preservation of old records, source archives and unrelated state, plus backup recovery. Review the diff and exact file list, then open a PR describing the final behavior, validation and any unverified scope. Merge into `main` after the required checks pass.

For a release, synchronize `VERSION`, the skill's `metadata.version`, the blank template's `skill_version`, and `CHANGELOG.md`, then tag the release commit `vX.Y.Z`. Use a patch version for fixes and compatible packaging or wording changes, a minor version for compatible new capabilities, and a major version with migration notes for breaking installation, configuration or record changes. Workflow version and record `schema_version` describe different contracts and must not be bumped just to match the skill version.

Resume old tasks from recorded stages and evidence; never backfill checks or rerun completed work merely to adopt a new version. For rollback, check out a verified tag and reinstall; use a new revert or fix commit instead of force-pushing shared history. Installation backups and real task state stay local.
