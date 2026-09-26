"""Offline-only, explicitly parameterized OR baseline on complete OANDA M1 MBA.

No network access, broker orders, X posting, or modification of live config.
This is a research approximation: fills at next-bar bid/ask open, not a tick replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, time
import math
from zoneinfo import ZoneInfo

from src.research_parity import parse_time

NY = ZoneInfo("America/New_York")


def _clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


@dataclass(frozen=True)
class StrategyParams:
    or_start: str = "09:30"
    or_end: str = "10:00"  # inclusive
    entry_time: str = "10:22"  # wait for this candle to finish
    exit_time: str = "12:00"  # exit at the bid/ask OPEN of this candle
    top_pct: float = 0.35
    bottom_pct: float = 0.35
    stop_loss_points: float = 25.0
    take_profit_points: float = 75.0
    units: int = 80
    entry_slippage_points: float = 0.0
    exit_slippage_points: float = 0.0
    commission_per_side_usd: float = 0.0

    def __post_init__(self) -> None:
        if not (_clock(self.or_start) < _clock(self.or_end) < _clock(self.entry_time) < _clock(self.exit_time) <= time(12)):
            raise ValueError("Expected OR start < inclusive OR end < entry candle < hard exit <= noon")
        if not isinstance(self.units, int) or isinstance(self.units, bool):
            raise ValueError("Position units must be an integer")
        numbers = (self.top_pct, self.bottom_pct, self.stop_loss_points, self.take_profit_points,
                   self.entry_slippage_points, self.exit_slippage_points, self.commission_per_side_usd)
        if not all(math.isfinite(float(x)) for x in numbers):
            raise ValueError("Non-finite research parameter")
        if min(self.top_pct, self.bottom_pct) < 0 or self.top_pct + self.bottom_pct >= 1:
            raise ValueError("Overlapping or negative zones")
        if self.stop_loss_points <= 0 or self.take_profit_points <= 0 or self.units <= 0:
            raise ValueError("Stop, target and size must be positive")
        if min(self.entry_slippage_points, self.exit_slippage_points, self.commission_per_side_usd) < 0:
            raise ValueError("Execution penalties cannot be negative")


def _indexed(candles: list[dict], day: date) -> dict[datetime, dict]:
    """Date-keyed candles; duplicates/missing/non-complete bars are rejected."""
    result: dict[datetime, dict] = {}
    for candle in candles:
        ts = parse_time(candle["time"]).astimezone(NY)
        if ts.date() == day:
            if ts in result:
                raise ValueError("Duplicate minute timestamp")
            result[ts] = candle
    return result


def _minute(day: date, clock: str) -> datetime:
    return datetime.combine(day, _clock(clock), tzinfo=NY)


def _required_bars(bars: dict[datetime, dict], day: date, params: StrategyParams) -> str | None:
    # Common eligibility for every candidate on a given session: full OR-to-noon
    # coverage, even on a day where this particular rule closes early.
    t = _minute(day, params.or_start)
    end = _minute(day, "12:00")
    while t <= end:
        bar = bars.get(t)
        if not bar or bar.get("complete") is not True:
            return "missing_or_incomplete_minute"
        if not all(isinstance(bar.get(component), dict) and all(key in bar[component] for key in "ohlc")
                   for component in ("mid", "bid", "ask")):
            return "missing_bid_ask_or_mid_ohlc"
        t += timedelta(minutes=1)
    return None


def signal_for_session(bars: dict[datetime, dict], day: date, params: StrategyParams) -> dict:
    """Exactly the baseline zone test on completed MID OR and entry candles."""
    start = _minute(day, params.or_start)
    end = _minute(day, params.or_end)
    or_bars = [bars[t] for t in (start + timedelta(minutes=i) for i in range((end - start).seconds // 60 + 1))]
    or_high = max(float(x["mid"]["h"]) for x in or_bars)
    or_low = min(float(x["mid"]["l"]) for x in or_bars)
    if or_high <= or_low:
        return {"side": None, "reason": "zero_opening_range"}
    entry_signal = float(bars[_minute(day, params.entry_time)]["mid"]["c"])
    width = or_high - or_low
    top_cut = or_high - params.top_pct * width
    bottom_cut = or_low + params.bottom_pct * width
    side = "long" if entry_signal >= top_cut else "short" if entry_signal <= bottom_cut else None
    return {"side": side, "reason": side or "middle_zone", "signal_price": entry_signal,
            "or_high": or_high, "or_low": or_low, "top_cut": top_cut, "bottom_cut": bottom_cut}


def exit_fill(level: float, quote_open: float, direction: int, slippage: float, *, is_stop: bool) -> tuple[float, bool]:
    """Stop-market gaps fill at the worse open; limit targets never receive price improvement."""
    gap = is_stop and direction * (quote_open - level) < 0
    actual = quote_open if gap else level
    return actual - direction * slippage, gap


def run_session(day: str, candles: list[dict], params: StrategyParams) -> dict:
    """Research a single day; never treat missing quotes as a flat/no-trade day.

    Data must contain complete M1 mid/bid/ask for 09:30–12:00 NY. First possible
    order is at the next minute OPEN after the completed entry candle. Attached
    SL/TP levels are relative to that filled price; long exits at bid, short at
    ask; simultaneous intraminute hits assume the stop first and are flagged.
    """
    trade_date = date.fromisoformat(day)
    if trade_date.weekday() >= 5:
        return {"day_ny": day, "status": "excluded", "reason": "weekend"}
    try:
        bars = _indexed(candles, trade_date)
    except (KeyError, ValueError):
        return {"day_ny": day, "status": "excluded", "reason": "invalid_or_duplicate_timestamp"}
    missing = _required_bars(bars, trade_date, params)
    if missing:
        return {"day_ny": day, "status": "excluded", "reason": missing}
    sig = signal_for_session(bars, trade_date, params)
    if sig["side"] is None:
        return {"day_ny": day, "status": "no_trade" if sig["reason"] == "middle_zone" else "excluded",
                "reason": sig["reason"], "signal": sig}
    side = sig["side"]
    direction = 1 if side == "long" else -1
    quote = "ask" if side == "long" else "bid"
    entry_minute = _minute(trade_date, params.entry_time) + timedelta(minutes=1)
    if entry_minute >= _minute(trade_date, params.exit_time):
        return {"day_ny": day, "status": "excluded", "reason": "entry_at_hard_exit"}
    entry = float(bars[entry_minute][quote]["o"]) + direction * params.entry_slippage_points
    sl = entry - direction * params.stop_loss_points
    tp = entry + direction * params.take_profit_points
    t = entry_minute
    hard_exit = _minute(trade_date, params.exit_time)
    ambiguous = False
    gap_through_stop = False
    while t < hard_exit:
        exit_bar = bars[t]["bid" if side == "long" else "ask"]
        high, low = float(exit_bar["h"]), float(exit_bar["l"])
        touched_sl = low <= sl if side == "long" else high >= sl
        touched_tp = high >= tp if side == "long" else low <= tp
        if touched_sl or touched_tp:
            ambiguous = touched_sl and touched_tp
            reason = "sl" if touched_sl else "tp"  # adverse same-minute tie
            exit_price, gap_through_stop = exit_fill(sl if touched_sl else tp,
                                                     float(exit_bar["o"]), direction,
                                                     params.exit_slippage_points, is_stop=touched_sl)
            exit_minute = t
            break
        t += timedelta(minutes=1)
    else:
        reason = "time"
        exit_minute = hard_exit
        exit_price = float(bars[hard_exit]["bid" if side == "long" else "ask"]["o"]) - direction * params.exit_slippage_points
    gross_points = direction * (exit_price - entry)
    gross_usd = gross_points * params.units
    net_usd = gross_usd - 2 * params.commission_per_side_usd
    return {"day_ny": day, "status": "trade", "signal": sig, "side": side,
            "entry_minute": entry_minute.isoformat(), "entry_price": round(entry, 6),
            "sl_price": round(sl, 6), "tp_price": round(tp, 6),
            "exit_minute": exit_minute.isoformat(), "exit_price": round(exit_price, 6),
            "exit_reason": reason, "ambiguous_same_bar": ambiguous,
            "gap_through_stop": gap_through_stop,
            "gross_points": round(gross_points, 6), "gross_usd": round(gross_usd, 6),
            "net_usd": round(net_usd, 6)}
