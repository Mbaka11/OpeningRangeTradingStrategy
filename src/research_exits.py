"""OFFLINE-only, conservative candidate exits on complete one-minute bid/ask bars.

No network, OANDA order endpoint, runtime bot import, or X posting.
All exit variants use the exact same signal and hypothetical next-bar entry
as research_backtest.run_session. Policy updates take effect only NEXT minute.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import math
from typing import Any

from src.research_backtest import (
    StrategyParams, _indexed, _minute, exit_fill, run_session,
)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"Policy {label} must be a finite number")
    return float(value)


def validate_policy(policy: dict, params: StrategyParams) -> None:
    if not isinstance(policy, dict) or not isinstance(policy.get("id"), str):
        raise ValueError("Every research policy requires a string id")
    family = policy.get("family")
    if family in ("fixed", "time", "protect", "trailing"):
        target = _number(policy.get("target_points"), "target_points")
        if target <= 0:
            raise ValueError("Target must be positive")
    elif family == "partial":
        target = _number(policy.get("remaining_target_points"), "remaining_target_points")
        first = _number(policy.get("first_target_points"), "first_target_points")
        fraction = _number(policy.get("first_exit_fraction"), "first_exit_fraction")
        stop = _number(policy.get("remaining_stop_points_from_entry"), "remaining_stop_points_from_entry")
        if not (0 < first < target and 0 < fraction < 1 and stop == -params.stop_loss_points):
            raise ValueError("Invalid partial size/levels or changed initial stop")
        if not 0 < int(params.units * fraction) < params.units:
            raise ValueError("Partial size cannot be rounded to a valid unit count")
    else:
        raise ValueError(f"Unsupported research exit family: {family}")
    if family in ("protect", "trailing"):
        activation = _number(policy.get("activation_points"), "activation_points")
        if not 0 < activation < target:
            raise ValueError("Activation must precede final target")
        if family == "protect":
            offset = _number(policy.get("new_stop_points_from_entry"), "new_stop_points_from_entry")
            if offset != 0:
                raise ValueError("Protocol requires gross entry-price stop after activation")
        else:
            if _number(policy.get("trailing_distance_points"), "trailing_distance_points") <= 0:
                raise ValueError("Trailing distance must be positive")
    if family == "time":
        if not isinstance(policy.get("exit_ny"), str):
            raise ValueError("Time exit requires an NY HH:MM string")
        # StrategyParams also checks the time ordering and the noon cap.
        replace(params, exit_time=policy["exit_ny"])


def run_policy_session(day: str, candles: list[dict], params: StrategyParams, policy: dict) -> dict:
    """One policy on one NY date; stateful within a trade, but no external writes.

    Same-bar stop takes precedence over target/activation; stop-market gaps
    fill at the worse bar open. First partial TP does not permit a runner TP
    *in the same candle*. Protective/trailing amendments activate next minute.
    Any OHLC ordering ambiguity is flagged for separate sensitivity analysis.
    """
    validate_policy(policy, params)
    family = policy["family"]
    if family == "fixed":
        result = run_session(day, candles, replace(params, take_profit_points=policy["target_points"]))
    elif family == "time":
        result = run_session(day, candles, replace(params, take_profit_points=policy["target_points"],
                                                    exit_time=policy["exit_ny"]))
    else:
        # run_session makes the baseline signal/eligibility/entry. Dynamic
        # rules reuse it, not the realized baseline EXIT; no future prices in
        # the signal or amendments on the triggering bar.
        result = run_session(day, candles, params)
    result = {**result, "policy_id": policy["id"]}
    if result["status"] != "trade":
        return result
    if family in ("fixed", "time"):
        result["legs"] = [{"units": params.units, "exit_price": result["exit_price"],
                           "reason": result["exit_reason"], "minute": result["exit_minute"]}]
        result["amendments"] = 0
        return result

    bars = _indexed(candles, date.fromisoformat(day))
    entry = result["entry_price"]
    entry_minute = _minute(date.fromisoformat(day), params.entry_time) + timedelta(minutes=1)
    hard_exit = _minute(date.fromisoformat(day), params.exit_time)
    direction = 1 if result["side"] == "long" else -1
    quote = "bid" if direction > 0 else "ask"
    final_target = _number(policy.get("remaining_target_points" if family == "partial" else "target_points"), "target")
    target = entry + direction * final_target
    stop = entry - direction * params.stop_loss_points
    remaining = params.units
    first_units = int(params.units * policy["first_exit_fraction"]) if family == "partial" else 0
    first_target = entry + direction * policy["first_target_points"] if family == "partial" else None
    activation = entry + direction * policy["activation_points"] if family in ("protect", "trailing") else None
    active = False
    amendments = 0
    ambiguous: set[str] = set()
    gap_through_stop = False
    legs: list[dict] = []

    def close(units: int, level: float, reason: str, minute, bar: dict | None) -> None:
        nonlocal remaining, gap_through_stop
        if reason == "time":
            price = level - direction * params.exit_slippage_points
            gap = False
        else:
            price, gap = exit_fill(level, float(bar["o"]), direction,
                                   params.exit_slippage_points, is_stop=reason == "sl")
        gap_through_stop |= gap
        legs.append({"units": units, "exit_price": round(price, 6),
                     "reason": reason, "minute": minute.isoformat()})
        remaining -= units

    t = entry_minute
    while t < hard_exit and remaining:
        bar = bars[t][quote]
        hi, lo = float(bar["h"]), float(bar["l"])
        touched_stop = lo <= stop if direction > 0 else hi >= stop
        touched_target = hi >= target if direction > 0 else lo <= target
        touched_activation = (hi >= activation if direction > 0 else lo <= activation) if activation is not None else False
        touched_first = (hi >= first_target if direction > 0 else lo <= first_target) if first_target is not None else False
        if touched_stop:
            if touched_target or (not active and (touched_activation or touched_first)):
                ambiguous.add("stop_and_favorable_touch_same_bar")
            close(remaining, stop, "sl", t, bar)
            break
        if family == "partial" and not active and touched_first:
            close(first_units, first_target, "tp_partial", t, bar)
            active = True
            if touched_target:
                ambiguous.add("runner_target_inside_first_partial_bar_deferred")
            t += timedelta(minutes=1)
            continue
        # The full-size TP is already attached for protect/trail. The partial
        # runner TP is available only after the first partial bar has finished.
        if touched_target and (family != "partial" or active):
            close(remaining, target, "tp", t, bar)
            break
        if family == "protect" and not active and touched_activation:
            active = True
            if (lo <= entry if direction > 0 else hi >= entry):
                ambiguous.add("entry_stop_would_touch_activation_bar_before_amendment")
            stop = max(stop, entry) if direction > 0 else min(stop, entry)
            amendments += 1  # applied only for next bar; no same-bar rescue
        elif family == "trailing" and (active or touched_activation):
            active = True
            distance = policy["trailing_distance_points"]
            suggested = (hi - distance) if direction > 0 else (lo + distance)
            improved = suggested > stop if direction > 0 else suggested < stop
            if improved:
                if (lo <= suggested if direction > 0 else hi >= suggested):
                    ambiguous.add("trail_would_touch_in_same_bar_before_amendment")
                stop = suggested
                amendments += 1  # next minute only
        t += timedelta(minutes=1)
    if remaining:
        close(remaining, float(bars[hard_exit][quote]["o"]), "time", hard_exit, None)
    gross_usd = sum(direction * (leg["exit_price"] - entry) * leg["units"] for leg in legs)
    result.update({"exit_price": round(sum(leg["exit_price"] * leg["units"] for leg in legs) / params.units, 6),
                   "exit_minute": legs[-1]["minute"],
                   "exit_reason": " + ".join(leg["reason"] for leg in legs),
                   "legs": legs, "amendments": amendments,
                   "ambiguous_same_bar": bool(ambiguous), "ambiguity_reasons": sorted(ambiguous),
                   "gap_through_stop": gap_through_stop,
                   "gross_points": round(gross_usd / params.units, 6),
                   "gross_usd": round(gross_usd, 6),
                   "net_usd": round(gross_usd - (1 + len(legs)) * params.commission_per_side_usd, 6)})
    return result
