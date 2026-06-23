"""Campaign configuration: the objective, the verification price, budgets, target."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ObjectiveSpec:
    """What the designer is trying to do, and under what budget/price.

    - target: short description of the design target (screened by safety.policy).
    - objective: the property being optimized (e.g. "thermostability").
    - lam: verification price λ in net = benefit − λ·assays.
    - rounds / candidates_per_round: DBTL loop budget.
    - assay_budget: max verify_assay actions allowed across the campaign.
    - allowlist: explicit allow tags; if set, the target must match one.
    """
    target: str
    objective: str = "stability"
    lam: float = 0.5
    rounds: int = 3
    candidates_per_round: int = 8
    assay_budget: int = 12
    seed: int = 0
    allowlist: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ObjectiveSpec":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_yaml(cls, path: str) -> "ObjectiveSpec":
        try:
            import yaml  # optional dependency
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("from_yaml requires pyyaml: pip install 'bio_sfm_designer[yaml]'") from exc
        with open(path) as fh:
            return cls.from_dict(yaml.safe_load(fh) or {})
