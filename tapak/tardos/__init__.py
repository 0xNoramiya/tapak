"""Tardos probabilistic fingerprinting codes, implemented from scratch.

Submodules: ``params`` (code length), ``code`` (generation), ``accuse`` (scores and
threshold), ``attacks`` (collusion strategies), ``simulate`` (Monte Carlo evaluation).
"""

from tapak.tardos.params import TardosParams

__all__ = ["TardosParams"]
