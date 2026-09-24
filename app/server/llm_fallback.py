"""App-side Tier-2 LLM fallback.

Delegates to the shared engine implementation (``rca_engine.llm_fallback``) so the App,
CLI and Genie Code skill behave identically: the same residual-selection gate (residual +
code-generated ``transpilation`` findings), the join-context reconstruction of the migrated
derivation, and the query-gated promotion (a verdict is promoted ONLY if the model's
confirming query matches). Kept as a thin re-export so existing
``from .llm_fallback import run_llm_fallback`` imports keep working.
"""

from __future__ import annotations

from rca_engine.llm_fallback import run_llm_fallback  # noqa: F401
