"""Tardos probabilistic fingerprinting codes, implemented from scratch.

Submodules: ``params`` (code length), ``code`` (generation), ``accuse`` (scores and
threshold), ``spending`` (budget per repeated trace and per stage), ``staged`` (side-informed
later stages that look for further colluders), ``detection`` (proven bound on the
probability that a coalition escapes), ``attacks`` (collusion strategies), ``simulate``
(Monte Carlo evaluation).
"""

from tapak.tardos.params import TardosParams

__all__ = ["TardosParams"]
