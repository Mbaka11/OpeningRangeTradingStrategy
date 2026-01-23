from typing import TypedDict, List, Optional, Dict, Any


class Candle(TypedDict):
    time_ny: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    complete: bool


class StrategyParams(TypedDict):
    entry_time: str
    exit_time: str
    top_pct: float
    bot_pct: float
    sl_points: float
    tp_points: float


class EntryBounds(TypedDict):
    top_cut: float
    bottom_cut: float


class SessionSetup(TypedDict):
    date: str
    instrument: str
    strategy_params: StrategyParams
    or_high: float
    or_low: float
    or_range: float
    or_completeness: str
    or_candles: List[Candle]


class SignalDecision(TypedDict):
    signal_type: str
    signal_reason: str
    entry_price: Optional[float]
    entry_bounds: EntryBounds
    timestamp: str


class PreTradeChecks(TypedDict):
    spread: float
    volatility_atr_14: float
    timestamp: str


class TradeResult(TypedDict):
    side: str
    pnl_points: Optional[float]
    pnl_usd: Optional[float]
    exit_reason: str
    mfe_points: float
    mae_points: float
    trade_path_candles: List[Candle]


class DailyLog(TypedDict):
    session_setup: SessionSetup
    pre_trade_checks: Optional[PreTradeChecks]
    signal_decision: Optional[SignalDecision]
    trade_result: Optional[TradeResult]
