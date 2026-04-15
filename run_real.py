import backtrader as bt
import pandas as pd
from formagold_quant_v01 import (
    FormaGoldStrategy, load_from_yfinance,
    compute_stats, print_report, plot_results
)
print("Loading real Gold daily data...")
df = load_from_yfinance('2023-01-01', '2026-04-01', '1d')
cerebro = bt.Cerebro(stdstats=False)
cerebro.adddata(bt.feeds.PandasData(dataname=df))
cerebro.addstrategy(
    FormaGoldStrategy,
    ema_fast=50,
    ema_slow=200,
    bo_period=20,
    atr_period=14,
    sl_mult=1.5,
    tp_mult=3.2,
    risk_pct=1.0,
    max_dd_pct=3.0,
    max_trades_day=3,
    london_open=0,
    london_close=24,
    ny_open=0,
    ny_close=24,
)
cerebro.broker.setcash(10000.0)
cerebro.broker.setcommission(commission=0.0002)
print("Running on REAL Gold data...\n")
strat = cerebro.run()[0]
stats = compute_stats(strat, cerebro, 10000.0)
print_report(stats)
plot_results(stats, 'formagold_real_v01.png')
if stats['trade_log']:
    pd.DataFrame(stats['trade_log']).to_csv('formagold_real_trades.csv', index=False)
    print("Trades saved!")
