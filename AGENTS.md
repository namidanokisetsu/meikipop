# Development conventions

- Keep responses and code concise. Comment only non-obvious decisions.
- Continue the implementation order in `docs/TURKISH_SUPPORT_PLAN.md`; preserve Japanese behavior.
- Keep NLP imports lazy and model/data setup explicit. Runtime Turkish lookup must work offline.
- Use small fixtures and focused regression checks. Run `python -m unittest discover -s tests` with the project environment; run the actual-model Turkish smoke script when changing analysis.
- Update the existing Turkish plan/setup docs when needed. Do not edit README unless requested or required by agreed release scope. Do not add agent worklogs or extra status documents.
- Keep downloaded data, model weights, generated packs, and virtual environments out of Git. Preserve existing user changes.
