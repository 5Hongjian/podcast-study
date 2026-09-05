# Repository instructions

Maintain the portable podcast-study skill and its public support files. Follow CONTRIBUTING.md for iteration and versioning.

- Never copy a user's preferences, episode records, media, transcripts, private document URLs, credentials, or machine-specific paths into this repository. Only the empty run template and synthetic evaluation cases belong here.
- Keep user overrides above bundled defaults and below the current user request. Skill upgrades must preserve local preferences, document-format overrides, and run records.
- Preserve the native-transcript-first decision and the order: finish Google Docs, verify, then move eligible temporary files to system trash.
- Do not run an actual podcast, download models, or edit Google Docs when asked only to maintain this skill.
- Use a `codex/` branch for further iterations. Run the repository validator and installer tests before publishing relevant changes. Do not claim behavioral evaluation or live Docs verification unless actually performed.
- Keep changes bounded. Do not introduce a scheduler, multi-agent runtime, or cloud transcription dependency without a task that needs it.
