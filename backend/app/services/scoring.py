from dataclasses import dataclass
from typing import Literal

Lean = Literal["bullish", "neutral", "bearish"]

@dataclass(frozen=True)
class Signal:
    source: str
    lean: Lean
    weight: float = 1.0
    stale: bool = False
    fired: bool = True

# Exact formula:
# active sources are fresh sources that actually produced a signal. Neutral signals vote
# toward coverage but contribute zero to the signed agreement. Stale sources are excluded.
# agreement = abs(sum(signed weighted leans)) / number of active fired sources
# coverage = number of active fired sources / 3
# money_match = round(100 * min(1, agreement) * coverage)
# Therefore one maximally directional source caps at 33, two at 67, three can reach 100.
def money_match(signals: list[Signal]) -> int:
    active = [s for s in signals if s.fired and not s.stale]
    if not active:
        return 0
    signed = sum((1 if s.lean == "bullish" else -1 if s.lean == "bearish" else 0) * max(0.0, min(1.0, s.weight)) for s in active)
    agreement = min(1.0, abs(signed) / len(active))
    coverage = len(active) / 3
    return round(100 * agreement * coverage)

def direction(signals: list[Signal]) -> Lean:
    active = [s for s in signals if s.fired and not s.stale]
    total = sum((1 if s.lean == "bullish" else -1 if s.lean == "bearish" else 0) * max(0.0, min(1.0, s.weight)) for s in active)
    return "bullish" if total > 0 else "bearish" if total < 0 else "neutral"
