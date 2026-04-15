#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         FORMAGOLD QUANT BACKTESTER — v0.1                   ║
║         Forma Corporations | VAULT Intelligence Project      ║
║  Strategy : EMA 50/200 Trend + Breakout + ATR SL/TP         ║
║  Guards   : Session Gate | Daily DD | Max Trades/Day         ║
║  Symbol   : XAUUSD (Gold)                                   ║
║  Data     : yfinance (free) OR MT5 CSV export               ║
╚══════════════════════════════════════════════════════════════╝
"""

import backtrader as bt
import backtrader.analyzers as btanalyzers
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import os
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════
# PARAMETERS — mirrors MT5 EA v0.1 exactly
# ═══════════════════════════════════════════════════════════════
DEFAULT_PARAMS = {
    'ema_fast': 50, 'ema_slow': 200,
    'bo_period': 20,
    'atr_period': 14, 'sl_mult': 1.5, 'tp_mult': 3.2,
    'risk_pct': 1.0,
    'max_dd_pct': 3.0, 'max_trades_day': 3,
    'london_open': 7, 'london_close': 16,
    'ny_open': 13,    'ny_close': 22,
}


# ═══════════════════════════════════════════════════════════════
# STRATEGY
# ═══════════════════════════════════════════════════════════════
class FormaGoldStrategy(bt.Strategy):
    params = dict(
        ema_fast=50, ema_slow=200, bo_period=20,
        atr_period=14, sl_mult=1.5, tp_mult=2.5, risk_pct=1.0,
        max_dd_pct=3.0, max_trades_day=3,
        london_open=7, london_close=16, ny_open=13, ny_close=22,
        verbose=False,
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.p.ema_fast)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.p.ema_slow)
        self.atr      = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.highest  = bt.indicators.Highest(self.data.high, period=self.p.bo_period)
        self.lowest   = bt.indicators.Lowest(self.data.low,  period=self.p.bo_period)
        self.brk      = None
        self.current_day = None
        self.day_start_equity = self.broker.getvalue()
        self.trades_today = 0
        self.halted_today = False
        self.equity_curve = []
        self.bar_dates    = []
        self.trade_log    = []
        self.trades_count = 0

    def log(self, txt):
        if self.p.verbose:
            print(f'{self.datas[0].datetime.datetime(0)} | {txt}')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trades_count += 1
        pnl = round(trade.pnlcomm, 2)
        self.trade_log.append({
            'date': self.datas[0].datetime.date(0),
            'side': 'LONG' if trade.long else 'SHORT',
            'pnl': pnl,
            'pnl_pct': round(pnl / max(self.day_start_equity, 1) * 100, 3),
            'bars_held': trade.barlen,
            'equity_after': round(self.broker.getvalue(), 2),
        })

    def is_in_session(self):
        h = self.datas[0].datetime.datetime(0).hour
        return (self.p.london_open <= h < self.p.london_close or
                self.p.ny_open     <= h < self.p.ny_close)

    def daily_reset(self):
        today = self.datas[0].datetime.date(0)
        if today != self.current_day:
            self.current_day      = today
            self.day_start_equity = self.broker.getvalue()
            self.trades_today     = 0
            self.halted_today     = False

    def calc_size(self, sl_pts):
        if sl_pts <= 0:
            return 0.0
        risk_amt = self.broker.getvalue() * self.p.risk_pct / 100.0
        return max(0.01, round(risk_amt / sl_pts, 2))

    def next(self):
        self.equity_curve.append(self.broker.getvalue())
        self.bar_dates.append(self.datas[0].datetime.datetime(0))
        self.daily_reset()

        # Clear settled bracket
        if self.brk:
            if all(o.status in [o.Completed, o.Canceled, o.Expired, o.Rejected]
                   for o in self.brk):
                self.brk = None
            return

        if self.position:
            return

        equity = self.broker.getvalue()
        dd_pct = (self.day_start_equity - equity) / max(self.day_start_equity, 1) * 100
        if dd_pct >= self.p.max_dd_pct:
            self.halted_today = True
            return

        if self.trades_today >= self.p.max_trades_day:
            return

        if not self.is_in_session():
            return

        ema50  = self.ema_fast[0]
        ema200 = self.ema_slow[0]
        atr    = self.atr[0]
        close  = self.data.close[0]

        if atr <= 0:
            return

        bull = ema50 > ema200
        bear = ema50 < ema200

        if bull and close > self.highest[-1]:
            sl   = close - atr * self.p.sl_mult
            tp   = close + atr * self.p.tp_mult
            size = self.calc_size(close - sl)
            if size > 0:
                self.brk = self.buy_bracket(
                    size=size, exectype=bt.Order.Market,
                    stopprice=sl, limitprice=tp)
                self.trades_today += 1
                self.log(f'LONG  sz={size:.2f} sl={sl:.2f} tp={tp:.2f}')

        elif bear and close < self.lowest[-1]:
            sl   = close + atr * self.p.sl_mult
            tp   = close - atr * self.p.tp_mult
            size = self.calc_size(sl - close)
            if size > 0:
                self.brk = self.sell_bracket(
                    size=size, exectype=bt.Order.Market,
                    stopprice=sl, limitprice=tp)
                self.trades_today += 1
                self.log(f'SHORT sz={size:.2f} sl={sl:.2f} tp={tp:.2f}')


# ═══════════════════════════════════════════════════════════════
# DATA LOADERS
# ═══════════════════════════════════════════════════════════════

def load_from_yfinance(start='2023-01-01', end='2024-12-31', interval='1h'):
    try:
        import yfinance as yf
        print(f'\n  Fetching XAUUSD {interval} | {start} to {end}')
        df = yf.download('GC=F', start=start, end=end,
                         interval=interval, auto_adjust=True, progress=False)
        if df.empty:
            df = yf.download('XAUUSD=X', start=start, end=end,
                             interval=interval, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(None)
        print(f'  {len(df):,} bars loaded')
        return df
    except ImportError:
        raise ImportError('Run: pip install yfinance')


def load_from_csv(filepath):
    """Load from MT5 CSV export. Chart -> File -> Save As -> CSV"""
    print(f'\n  Loading: {filepath}')
    df = pd.read_csv(filepath, parse_dates=True)
    for col in ['time', 'datetime', 'date', 'Date', 'Time']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
            df = df.set_index(col)
            break
    else:
        df.index = pd.to_datetime(df.index)
    df.columns = [c.strip().capitalize() for c in df.columns]
    df = df.rename(columns={'Tick_volume': 'Volume', 'Tickvolume': 'Volume'})
    if 'Volume' not in df.columns:
        df['Volume'] = 0
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
    print(f'  {len(df):,} bars loaded')
    return df


def generate_synthetic_data(n_bars=6000, start_price=2000.0, seed=42):
    """Synthetic XAUUSD H1. FOR TESTING ONLY — not for live decisions."""
    print(f'\n  Generating synthetic XAUUSD H1 ({n_bars:,} bars)...')
    rng    = np.random.default_rng(seed)
    rets   = rng.normal(0.00015, 0.0038, n_bars)
    closes = start_price * np.exp(np.cumsum(rets))
    spread = closes * rng.uniform(0.003, 0.009, n_bars)
    highs  = closes + spread * rng.uniform(0.4, 0.75, n_bars)
    lows   = closes - spread * rng.uniform(0.4, 0.75, n_bars)
    opens  = np.roll(closes, 1); opens[0] = start_price
    dates  = pd.date_range('2023-01-02 08:00', periods=n_bars, freq='h')
    dates  = dates[dates.weekday < 5]
    n      = min(len(dates), n_bars)
    df     = pd.DataFrame({
        'Open': opens[:n], 'High': highs[:n],
        'Low': lows[:n],   'Close': closes[:n],
        'Volume': rng.integers(500, 5000, n),
    }, index=dates[:n])
    print(f'  {len(df):,} bars | ${df.Close.min():.0f} to ${df.Close.max():.0f}')
    return df


# ═══════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════

def compute_stats(strategy, cerebro, initial_cash):
    equity = np.array(strategy.equity_curve)
    trades = strategy.trade_log
    n      = len(trades)
    final  = cerebro.broker.getvalue()
    total_return = (final - initial_cash) / initial_cash * 100

    if len(equity) > 1:
        peak   = np.maximum.accumulate(equity)
        max_dd = ((peak - equity) / peak * 100).max()
        ret    = np.diff(equity) / equity[:-1]
        sharpe = (ret.mean() / ret.std() * np.sqrt(252 * 24)) if ret.std() > 0 else 0.0
    else:
        max_dd = sharpe = 0.0

    if n > 0:
        pnls   = [t['pnl'] for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate      = len(wins) / n * 100
        avg_win       = float(np.mean(wins))   if wins   else 0.0
        avg_loss      = float(np.mean(losses)) if losses else 0.0
        rr_ratio      = abs(avg_win / avg_loss) if avg_loss else 0.0
        profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float('inf')
        expectancy    = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)
        max_consec = consec = 0
        for p in pnls:
            consec = (consec + 1) if p <= 0 else 0
            max_consec = max(max_consec, consec)
        avg_bars = float(np.mean([t['bars_held'] for t in trades]))
    else:
        win_rate = avg_win = avg_loss = rr_ratio = profit_factor = expectancy = avg_bars = 0.0
        max_consec = 0

    if   win_rate >= 55 and rr_ratio >= 1.5 and max_dd < 10 and profit_factor >= 1.5:
        grade = 'A — GO LIVE (Demo first)'
    elif win_rate >= 50 and rr_ratio >= 1.2 and max_dd < 15:
        grade = 'B — TUNE THEN GO'
    elif win_rate >= 45 and max_dd < 20:
        grade = 'C — NEEDS TUNING'
    else:
        grade = 'D — DO NOT TRADE'

    return {
        'initial_cash': initial_cash,
        'final_equity': round(final, 2),
        'total_return': round(total_return, 2),
        'max_dd': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'n_trades': n,
        'win_rate': round(win_rate, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'rr_ratio': round(rr_ratio, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999.0,
        'expectancy': round(expectancy, 2),
        'max_consec_loss': max_consec,
        'avg_bars_held': round(avg_bars, 1),
        'grade': grade,
        'equity_curve': equity.tolist(),
        'trade_log': trades,
        'bar_dates': strategy.bar_dates,
    }


def print_report(s):
    w = 58
    print('\n' + '=' * w)
    print('  FORMAGOLD QUANT REPORT — v0.1'.center(w))
    print('=' * w)
    print(f'  {"Initial Capital":<24} $ {s["initial_cash"]:>12,.2f}')
    print(f'  {"Final Equity":<24} $ {s["final_equity"]:>12,.2f}')
    print(f'  {"Total Return":<24}   {s["total_return"]:>+12.2f}%')
    print(f'  {"Max Drawdown":<24}   {s["max_dd"]:>12.2f}%')
    print(f'  {"Sharpe Ratio":<24}   {s["sharpe"]:>12.2f}')
    print('-' * w)
    print(f'  {"Total Trades":<24}   {s["n_trades"]:>12}')
    print(f'  {"Win Rate":<24}   {s["win_rate"]:>12.1f}%')
    print(f'  {"Avg Win":<24} $ {s["avg_win"]:>12,.2f}')
    print(f'  {"Avg Loss":<24} $ {s["avg_loss"]:>12,.2f}')
    print(f'  {"Risk/Reward Ratio":<24}   {s["rr_ratio"]:>12.2f}')
    print(f'  {"Profit Factor":<24}   {s["profit_factor"]:>12.2f}')
    print(f'  {"Expectancy/Trade":<24} $ {s["expectancy"]:>12,.2f}')
    print(f'  {"Max Consec Losses":<24}   {s["max_consec_loss"]:>12}')
    print(f'  {"Avg Bars Held":<24}   {s["avg_bars_held"]:>12.1f}')
    print('=' * w)
    print(f'  GRADE: {s["grade"]}')
    print('=' * w)


# ═══════════════════════════════════════════════════════════════
# CHART
# ═══════════════════════════════════════════════════════════════

def plot_results(stats, output_path='formagold_backtest_v01.png'):
    equity = stats['equity_curve']
    trades = stats['trade_log']
    bg, panel = '#0b0d1e', '#0f1325'
    gold, green, red = '#f0a830', '#00d496', '#ff3a50'
    gray, text_c = '#6070a0', '#b8c0e0'

    fig = plt.figure(figsize=(15, 10), facecolor=bg)
    fig.suptitle('FormaGold QUANT  |  v0.1  |  XAUUSD  |  Forma Corporations',
                 color=gold, fontsize=12, fontweight='bold', y=0.98)
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.50, wspace=0.32,
                           top=0.93, bottom=0.07, left=0.07, right=0.97)

    def sty(ax, t=''):
        ax.set_facecolor(panel)
        ax.tick_params(colors=gray, labelsize=7.5)
        for sp in ax.spines.values():
            sp.set_edgecolor('#1a2040'); sp.set_linewidth(0.5)
        ax.grid(True, color='#161c38', linewidth=0.4)
        if t: ax.set_title(t, color=text_c, fontsize=8.5, pad=4, loc='left')

    eq   = np.array(equity)
    peak = np.maximum.accumulate(eq)
    x    = np.arange(len(eq))

    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(x, eq, color=gold, lw=1.1, zorder=3, label='Equity')
    ax1.fill_between(x, eq, peak, alpha=0.25, color=red, zorder=2, label='Drawdown')
    ax1.fill_between(x, stats['initial_cash'], eq,
                     where=(eq >= stats['initial_cash']), alpha=0.10, color=green, zorder=1)
    ax1.axhline(stats['initial_cash'], color=gray, lw=0.7, ls='--', alpha=0.5)
    ax1.set_ylabel('Equity ($)', fontsize=7.5, color=gray)
    ax1.legend(fontsize=7, labelcolor=text_c, facecolor=panel, edgecolor='#1e2440',
               framealpha=0.8, loc='upper left')
    sty(ax1, 'Equity Curve  |  Drawdown Zones')

    ax2 = fig.add_subplot(gs[1, 0])
    if trades:
        pnls = [t['pnl'] for t in trades]
        ax2.bar(range(len(pnls)), pnls,
                color=[green if p > 0 else red for p in pnls], width=0.75, alpha=0.85)
        ax2.axhline(0, color=gray, lw=0.6)
        ax2.set_xlabel('Trade #', fontsize=7); ax2.set_ylabel('P&L ($)', fontsize=7)
    sty(ax2, 'Per-Trade P&L')

    ax3 = fig.add_subplot(gs[1, 1])
    if trades:
        cum = np.cumsum([t['pnl'] for t in trades])
        c   = green if cum[-1] > 0 else red
        ax3.plot(cum, color=c, lw=1.3)
        ax3.fill_between(range(len(cum)), cum, 0, alpha=0.18, color=c)
        ax3.axhline(0, color=gray, lw=0.6)
        ax3.set_xlabel('Trade #', fontsize=7)
    sty(ax3, 'Cumulative P&L')

    ax4 = fig.add_subplot(gs[1, 2])
    if trades:
        wins  = [t['pnl'] for t in trades if t['pnl'] > 0]
        losses= [t['pnl'] for t in trades if t['pnl'] <= 0]
        if wins:   ax4.hist(wins,   bins=12, color=green, alpha=0.75, label='Wins')
        if losses: ax4.hist(losses, bins=12, color=red,   alpha=0.75, label='Losses')
        ax4.axvline(0, color=gray, lw=0.7)
        ax4.legend(fontsize=7, labelcolor=text_c, facecolor=panel, edgecolor='#1e2440')
        ax4.set_xlabel('P&L ($)', fontsize=7)
    sty(ax4, 'P&L Distribution')

    ax5 = fig.add_subplot(gs[2, :])
    ax5.axis('off'); ax5.set_facecolor(panel)
    rows = [
        ['Total Return', f'{stats["total_return"]:+.2f}%',
         'Win Rate',     f'{stats["win_rate"]:.1f}%',
         'Sharpe Ratio', f'{stats["sharpe"]:.2f}'],
        ['Max Drawdown', f'{stats["max_dd"]:.2f}%',
         'Avg Win',      f'${stats["avg_win"]:,.2f}',
         'Avg Loss',     f'${stats["avg_loss"]:,.2f}'],
        ['Risk/Reward',  f'{stats["rr_ratio"]:.2f}',
         'Profit Factor',f'{stats["profit_factor"]:.2f}',
         'Expectancy',   f'${stats["expectancy"]:,.2f}'],
        ['Total Trades', str(stats['n_trades']),
         'Max Consec L', str(stats['max_consec_loss']),
         'Grade',        stats['grade']],
    ]
    tbl = ax5.table(cellText=rows,
                    colLabels=['Metric','Value','Metric','Value','Metric','Value'],
                    cellLoc='center', loc='center', bbox=[0, 0, 1, 1])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor('#1e2440')
        if r == 0:
            cell.set_facecolor('#131830'); cell.set_text_props(color=gold, fontweight='bold')
        elif c % 2 == 0:
            cell.set_facecolor('#0e1228'); cell.set_text_props(color=gray)
        else:
            cell.set_facecolor(panel); cell.set_text_props(color=text_c)
    sty(ax5)

    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=bg, edgecolor='none')
    print(f'\n  Chart saved: {output_path}')
    plt.close()


# ═══════════════════════════════════════════════════════════════
# OPTIMIZER
# ═══════════════════════════════════════════════════════════════

def optimize(df, initial_cash=10000.0, commission=0.0002):
    from itertools import product as ip
    grid = {
        'ema_fast': [50], 'ema_slow': [200],
        'bo_period': [15, 20, 25],
        'sl_mult': [1.2, 1.5, 1.8],
        'tp_mult': [2.0, 2.5, 3.0],
        'risk_pct': [0.5, 1.0],
    }
    keys   = list(grid.keys())
    combos = list(ip(*grid.values()))
    print(f'\n  Optimizing {len(combos)} combinations...')
    results = []
    for i, combo in enumerate(combos):
        p = dict(zip(keys, combo))
        cb = bt.Cerebro(stdstats=False)
        cb.adddata(bt.feeds.PandasData(dataname=df))
        cb.addstrategy(FormaGoldStrategy, verbose=False, **p)
        cb.broker.setcash(initial_cash)
        cb.broker.setcommission(commission=commission)
        try:
            r = cb.run()[0]
            s = compute_stats(r, cb, initial_cash)
            results.append({**p,
                'return_pct': s['total_return'], 'win_rate': s['win_rate'],
                'rr_ratio': s['rr_ratio'],       'profit_factor': s['profit_factor'],
                'max_dd': s['max_dd'],            'n_trades': s['n_trades'],
                'sharpe': s['sharpe'],            'grade': s['grade']})
        except Exception:
            pass
        if (i + 1) % 9 == 0:
            print(f'  {i+1}/{len(combos)}...')
    df_r = pd.DataFrame(results).sort_values('profit_factor', ascending=False)
    print('\n  Top 5:')
    print(df_r.head(5)[['bo_period','sl_mult','tp_mult','risk_pct',
                         'win_rate','rr_ratio','profit_factor','max_dd','grade']].to_string(index=False))
    return df_r


# ═══════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════

def run_backtest(
    csv_path=None, use_synthetic=False,
    yf_start='2023-01-01', yf_end='2026-04-01', yf_interval='1h',
    initial_cash=10_000.0, commission=0.0002,
    verbose=False, run_optimize=False,
    output_chart='formagold_backtest_v01.png',
):
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║  FORMAGOLD QUANT BACKTESTER v0.1 | Forma Corporations       ║')
    print('╚══════════════════════════════════════════════════════════════╝')

    if csv_path:
        df = load_from_csv(csv_path)
    elif use_synthetic:
        df = generate_synthetic_data()
    else:
        df = load_from_yfinance(yf_start, yf_end, yf_interval)

    print(f'\n  Range  : {df.index[0]}  to  {df.index[-1]}')
    print(f'  Bars   : {len(df):,}')
    print(f'  Capital: ${initial_cash:,.2f}  |  Commission: {commission*100:.3f}%')

    feed    = bt.feeds.PandasData(dataname=df)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(feed)
    cerebro.addstrategy(FormaGoldStrategy, verbose=verbose)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    print('\n  Running backtest...\n')
    strat = cerebro.run()[0]

    stats = compute_stats(strat, cerebro, initial_cash)
    print_report(stats)
    if stats['equity_curve']:
        plot_results(stats, output_path=output_chart)
    if stats['trade_log']:
        log_path = output_chart.replace('.png', '_trades.csv')
        pd.DataFrame(stats['trade_log']).to_csv(log_path, index=False)
        print(f'  Trades : {log_path}')
    if run_optimize:
        opt = optimize(df, initial_cash, commission)
        opt.to_csv('formagold_optimize.csv', index=False)
        print('  Optimizer: formagold_optimize.csv')
    return stats


# ═══════════════════════════════════════════════════════════════
# ENTRY — configure here
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    run_backtest(
        # DATA — choose one:
        use_synthetic=False,            # Quick test  (no internet needed)
        # csv_path = 'XAUUSD_H1.csv', # MT5 export  (most accurate)
        yf_start = '2022-01-01',     # yfinance    (free, needs internet)
        yf_end   = '2024-12-31',
        yf_interval = '1h',

        initial_cash=10_000.0,
        commission=0.0002,
        verbose=False,
        run_optimize=False,
        output_chart='formagold_backtest_v01.png',
    )
