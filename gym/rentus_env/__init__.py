"""Rentus Operator gym: per-rollout sandbox sessions, scripted counterparts and the scorer.

Pure Python (3.12+), no NeMo Gym import here, so the same code backs the local eval loop and
the NeMo Gym resources server in gym/resources_servers/rentus/.
"""
from .session import RolloutSession
from .verify import verify, CHECK_TYPES

__all__ = ["RolloutSession", "verify", "CHECK_TYPES"]
