# Development conventions

- Keep responses and code concise. Comment only non-obvious decisions.
- Keep UI copy compact: no instructional clutter, implementation diagnostics, redundant labels, or em dashes. Prefer obvious controls with short tooltips.
- Prioritize transferable input features for Japanese; reuse its existing lookup and rendering. Keep Turkish-specific behavior and settings separate; do not redesign Japanese UI without an explicit request.
- Continue the implementation order in `docs/TURKISH_SUPPORT_PLAN.md`; preserve Japanese behavior.
- Inspect and reuse existing Meikipop components, UI conventions, and pipeline logic before adding new implementations. Extend shared components where practical; document any necessary language-specific divergence in the existing plan.
- Make small, logical commits with focused validation. Separate independent changes into reviewable commits; do not accumulate unrelated work into enormous diffs.
- Keep NLP imports lazy and model/data setup explicit. Runtime Turkish lookup must work offline.
- Keep validation efficient: use small fixtures and run `python -m unittest discover -s tests` once with the project environment. Avoid computer-use sessions, repeated live checks, heavy model tests and benchmarks unless requested or needed to diagnose a specific failure. Leave broad hands-on acceptance to the user; run actual-model Turkish smoke checks only when needed for an analysis change.
- Keep documentation slim: update the existing plan/setup docs, avoid repeated status summaries, and add no agent worklogs or extra status documents. Do not edit README unless requested or required by agreed release scope.
- Keep downloaded data, model weights, generated packs, and virtual environments out of Git. Preserve existing user changes.
