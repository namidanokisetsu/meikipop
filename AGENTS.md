# Development conventions

- Keep responses and code concise. Comment only non-obvious decisions.
- Continue the implementation order in `docs/TURKISH_SUPPORT_PLAN.md`; preserve Japanese behavior.
- Inspect and reuse existing Meikipop components, UI conventions, and pipeline logic before adding new implementations. Extend shared components where practical; document any necessary language-specific divergence in the existing plan.
- Make small, logical commits with focused validation. Separate independent changes into reviewable commits; do not accumulate unrelated work into enormous diffs.
- Keep NLP imports lazy and model/data setup explicit. Runtime Turkish lookup must work offline.
- Use small fixtures and focused regression checks. Run `python -m unittest discover -s tests` with the project environment; run the actual-model Turkish smoke script when changing analysis.
- Update the existing Turkish plan/setup docs when needed. Do not edit README unless requested or required by agreed release scope. Do not add agent worklogs or extra status documents.
- Keep downloaded data, model weights, generated packs, and virtual environments out of Git. Preserve existing user changes.
