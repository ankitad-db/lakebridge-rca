"""Pluggable per-dialect knowledge base of source<->Databricks differences."""

from rca_engine.knowledge.base import KnowledgeBase, load_kb

__all__ = ["KnowledgeBase", "load_kb"]
