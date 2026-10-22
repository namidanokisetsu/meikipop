# Development conventions

- Keep responses and code concise. Comment only non-obvious decisions.
- Keep README to a couple of short paragraphs and a compact tech/model list. No em dashes, hype, filler, AI stock phrases or repeated explanations. Release notes stay empty or one short sentence; desktop releases contain only the Windows EXE and the two macOS DMGs.
- Keep UI copy compact: no instructional clutter, implementation diagnostics, redundant labels, or em dashes. Prefer obvious controls with short tooltips.
- Make UI behavior logical and geometry-driven: derive placement and size from layouts, content bounds and stable anchors. Do not patch visual problems with arbitrary pixel offsets, delayed repositioning or viewport jumps. Preserve scroll, selection and window geometry during disclosure; avoid rebuilding unchanged content and batch necessary document/layout updates once. Meaning cutoffs must be explicit settings, not hidden constants. Labels must describe user-facing behavior.
- Keep initialization, corpus scans and other expensive preparation out of hover and click handlers. Reuse prepared analyzers and stable OCR/cache identities; check both cold-start and repeated interaction paths when fixing latency. Measure the reported path before claiming a performance issue is resolved.
- Prioritize transferable input features for Japanese; reuse its existing lookup and rendering. Keep Turkish-specific behavior and settings separate; do not redesign Japanese UI without an explicit request.
- Keep non-OCR lookup features opt-in and every text shortcut independently configurable or disabled, using key recording and sensible presets rather than syntax entry. Preserve an OCR-only workflow.
- Follow the architecture and constraints in `docs/DEVELOPMENT.md`; preserve Japanese behavior.
- Inspect and reuse existing Meikipop components, UI conventions, and pipeline logic before adding new implementations. Extend shared components where practical; document any necessary language-specific divergence in the development notes.
- Make small, logical commits with focused validation. Separate independent changes into reviewable commits; do not accumulate unrelated work into enormous diffs.
- When asked to reinstall or perform the end release procedure, rebuild and install locally on this Windows machine, preserve settings/data, push the commits and release tag to GitHub, and start the release workflow. Finish after the local installation; do not wait for GitHub builds or macOS installers.
- Use one release version per finished batch. Tag only after validation and the local Windows build/install succeed; intermediate iterations are commits, not releases.
- Keep NLP imports lazy and model/data setup explicit. Runtime Turkish lookup must work offline.
- Keep validation efficient: use small fixtures and run `python -m unittest discover -s tests` once with the project environment. Avoid computer-use sessions, repeated live checks, heavy model tests and benchmarks unless requested or needed to diagnose a specific failure. Leave broad hands-on acceptance to the user; run actual-model Turkish smoke checks only when needed for an analysis change.
- Keep documentation slim: update the existing user guide/development notes, avoid repeated status summaries, and add no agent worklogs or extra status documents. Do not edit README unless requested or required by agreed release scope.
- Keep downloaded data, model weights, generated packs, and virtual environments out of Git. Preserve existing user changes.
