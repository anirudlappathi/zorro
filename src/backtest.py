import pandas as pd
from backtesting import Backtest, Strategy
import talib
import datetime
import json
import pprint

import multiprocessing as mp
mp.set_start_method('fork')

def ema(series, period):
    return talib.EMA(series, timeperiod=period)

def rsi(series, period=14):
    return talib.RSI(series, timeperiod=period)

def adx(high, low, close, period=14):
    return talib.ADX(high, low, close, timeperiod=period)

def ao(high, low):
    median_price = (high + low) / 2
    ao_short = talib.SMA(median_price, timeperiod=5)
    ao_long  = talib.SMA(median_price, timeperiod=34)
    return ao_short - ao_long

def bbands(close, period=5, nbdev=2):
    upper, middle, lower = talib.BBANDS(close, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev)
    return upper, middle, lower

def atr(high, low, close, period=14):
    return talib.ATR(high, low, close, timeperiod=period)


class CryptoBacktest(Strategy):
    """
    Example strategy with sl and tp as hyper-parameters.
    You can run optimize() to find the best combination.
    """

    # -- Declare these as *class attributes* to allow optimization --
    sl = 0.02   # default stop-loss ratio
    tp = 0.01   # default take-profit ratio

    def init(self):
        close = self.data.Close
        high  = self.data.High
        low   = self.data.Low

        self.ema5    = self.I(ema, close, 5)
        self.ema21   = self.I(ema, close, 21)
        self.ema50   = self.I(ema, close, 50)
        self.ema200  = self.I(ema, close, 200)
        self.adx_arr = self.I(adx, high, low, close, 14)
        self.ao_arr  = self.I(ao, high, low)
        self.b_upper, self.b_mid, self.b_lower = self.I(bbands, close, 5, 2)
        self.atr_arr = self.I(atr, high, low, close, 14)

    def find_position(self):
        ema5    = self.ema5[-1]
        ema21   = self.ema21[-1]
        ema50   = self.ema50[-1]
        ema200  = self.ema200[-1]
        adx_val = self.adx_arr[-1]
        ao_val  = self.ao_arr[-1]
        upper   = self.b_upper[-1]
        lower   = self.b_lower[-1]
        close   = self.data.Close[-1]
        atr_val = self.atr_arr[-1]
        atr_val10 = self.atr_arr[-10]

        def should_long():
            bb_percent = (close - lower) / (upper - lower) if upper != lower else 0
            if (
                ema50 <= ema200
                or ema5 <= ema21
                or bb_percent < 0.75
                or (adx_val is None or adx_val < 15)
                or (ao_val is None or ao_val < 0.25)
                or (atr_val <= atr_val10)
            ):
                return False
            return True

        def should_short():
            bb_percent = (close - lower) / (upper - lower) if upper != lower else 1
            if (
                ema50 >= ema200
                or ema5 >= ema21
                or bb_percent > 0.25
                or (adx_val is None or adx_val < 15)
                or (ao_val is None or ao_val > -0.25)
                or (atr_val <= atr_val10)
            ):
                return False
            return True

        long_trade = should_long()
        short_trade = should_short()
        return long_trade, short_trade

    def next(self):
        long_trade, short_trade = self.find_position()
        close = self.data.Close[-1]

        if long_trade:
            sl_price = (1 - self.sl) * close
            tp_price = (1 + self.tp) * close
            self.buy(sl=sl_price, tp=tp_price)

        # if short_trade:
        #     sl_price = (1 + self.sl) * close
        #     tp_price = (1 - self.tp) * close
        #     self.sell(sl=sl_price, tp=tp_price)


def save_stats(name, csv_file, df, stats, sl = None, tp = None):
    clean_stats = dict(stats)

    clean_stats.pop('_equity_curve', None)
    clean_stats.pop('_trades', None)
    clean_stats.pop('_strategy', None)

    for k, v in clean_stats.items():
        if isinstance(v, (pd.Timestamp, pd.Timedelta)):
            clean_stats[k] = str(v)

    start_date = df.index.min()
    end_date   = df.index.max()
    stats_dict = dict(clean_stats)
    now_str = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

    stats_dict['Take Price'] = str(tp)
    stats_dict['Stop Loss'] = str(sl)
    stats_dict['StartDate'] = str(start_date)
    stats_dict['EndDate']   = str(end_date)

    with open(f'saved_states/{name}-{now_str}-{str(start_date)}-{str(end_date)}-{csv_file.split("/")[-1]}.json', 'w') as f:
        json.dump(stats_dict, f, indent=4)

if __name__ == '__main__':
    csv_file = 'backtesting_data/ETH_1min_recent.csv'
    df = pd.read_csv(csv_file, parse_dates=['Date'], index_col='Date')

    bt = Backtest(
        df,
        CryptoBacktest,
        cash=1000000,
        exclusive_orders=True,
    )

    # stats = bt.run()
    # pprint.pprint(stats)
    # save_stats("backtest-summary", csv_file, df, stats)
    # bt.plot()

    optimized_stats = bt.optimize(
        sl=[0.005, 0.01, 0.02, 0.03],
        tp=[0.005, 0.01, 0.02, 0.03],
        maximize='Sharpe Ratio',
    )
    pprint.pprint(optimized_stats)
    print(optimized_stats._strategy.sl, optimized_stats._strategy.tp)
    save_stats("optimization",csv_file, df, optimized_stats, sl=optimized_stats._strategy.sl, tp=optimized_stats._strategy.tp)
