"""AI analysis provider abstraction + shadow-mode integration.

Phase 1 deployment runs these providers in *shadow mode*: outputs are logged
to ``ai_analysis_log`` but not blended into the recommendation composite.
Phase 2+ may disable shadow mode once a legal-review gate is set, at which
point the AI score blends via :mod:`backend.app.intelligence.synthesizer` with
a hard-capped weight (``MAX_AI_WEIGHT = 0.30``).
"""
