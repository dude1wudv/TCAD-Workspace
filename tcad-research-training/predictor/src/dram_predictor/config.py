"""Frozen, bounded training configurations. Importing this module does not train."""
from dataclasses import asdict, dataclass, replace
from itertools import product
import random


@dataclass(frozen=True)
class Config:
    r_hidden: tuple[int, ...] = (64, 64)
    f_hidden: tuple[int, ...] = (32, 32)
    mode: str = "hybrid"
    residual_bins: int = 4
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    residual_penalty: float = 1e-3
    max_epochs: int = 300
    patience: int = 30
    r_batch_groups: int = 64
    f_batch_conditions: int = 32
    seed: int = 1729
    split_seed: int = 20261116
    threads: int = 1
    stopping_fraction: float = .2

    def __post_init__(self):
        if self.mode not in {"hybrid", "plain", "mechanism_only"}:
            raise ValueError("Unknown R mode")
        if (not self.r_hidden or not self.f_hidden or
                any(x < 1 for x in self.r_hidden + self.f_hidden)):
            raise ValueError("Network widths must be positive")
        if any(x < 1 for x in (self.max_epochs, self.patience, self.r_batch_groups,
                              self.f_batch_conditions, self.threads)):
            raise ValueError("Epochs, patience, batches and threads must be positive")
        if self.threads != 1:
            raise ValueError("Initial training allocation is one thread, one process")
        if not 0 < self.stopping_fraction < .5:
            raise ValueError("Stopping fraction must be between zero and one half")
        if self.learning_rate <= 0 or self.weight_decay < 0 or self.residual_penalty < 0:
            raise ValueError("Invalid optimizer/regularization configuration")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, values):
        values = dict(values)
        for key in ("r_hidden", "f_hidden"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)


def search_space(base: Config = Config()) -> list[Config]:
    """One prescribed default plus eleven deterministic draws, NOT a full grid."""
    candidates = list(product(((32, 32), (64, 64), (64, 64, 32)),
                              ((16, 16), (32, 32)), (3e-4, 1e-3),
                              (1e-5, 1e-4, 1e-3), (0., 1e-3, 1e-2)))
    default = ((64, 64), (32, 32), 1e-3, 1e-4, 1e-3)
    candidates.remove(default)
    random.Random(base.split_seed).shuffle(candidates)
    return [replace(base, r_hidden=r, f_hidden=f, learning_rate=lr,
                    weight_decay=wd, residual_penalty=reg, seed=1729)
            for r, f, lr, wd, reg in [default] + candidates[:11]]
