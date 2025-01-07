from typing import List
from src.robincrypto import RobinCrypto as rc
from src.log import log
import talib
l = log(__file__)

class TestAlgorithm(rc):

  def __init__(self):
    super().__init__(
      ticker_data_folderpath="/Users/anirud/Downloads/projects/crypto-trading-bot/data",
      max_risk=1.0,
    )

  def __ao(self, high, low):
    median_price = (high + low) / 2
    ao_short = talib.SMA(median_price, timeperiod=5)
    ao_long = talib.SMA(median_price, timeperiod=34)
    return ao_short - ao_long

  @rc.run()
  def algo1(self, ticker: str):
    df = self.get_df(ticker, max=50)

    if df is None or len(df) < 10:
      return

    
    close: float = df["Close"]
    high_: float = df["High"]
    low_: float = df["Low"]

    
    atr_arr = talib.ATR(high_, low_, close, timeperiod=14)
    atr_val = atr_arr.iloc[-1]
    atr_val10 = atr_arr.iloc[-10]
    ema5_val = talib.EMA(close, timeperiod=5).iloc[-1]
    ema21_val = talib.EMA(close, timeperiod=21).iloc[-1]
    ema50_val = talib.EMA(close, timeperiod=50).iloc[-1]
    ema200_val = talib.EMA(close, timeperiod=200).iloc[-1]
    adx_val = talib.ADX(high_, low_, close, timeperiod=14).iloc[-1]
    ao_val = self.__ao(high_, low_).iloc[-1]
    close_val   = close.iloc[-1]
    b_upper, _, b_lower = talib.BBANDS(close, timeperiod=5, nbdevup=2, nbdevdn=2)
    upper_val   = b_upper.iloc[-1]
    lower_val   = b_lower.iloc[-1]

    bb_percent = 0
    if (upper_val - lower_val) != 0:
      bb_percent = (close_val - lower_val) / (upper_val - lower_val)
    if (ema50_val <= ema200_val or
        ema5_val <= ema21_val or
        bb_percent < 0.75 or
        (adx_val is None or adx_val < 15) or
        (ao_val is None or ao_val < 0.25) or
        (atr_val <= atr_val10)):
      return
    
    l.info(f"[{ticker}] LONG POSITION")
    self.long(ticker, risk_percentage=0.2, stop_loss_percent=0.02, take_price_percent=0.01)
    
if __name__ == "__main__":
  ta = TestAlgorithm()
  ta.algo1(["BTC-USD", "ETH-USD", "XRP-USD", "DOGE-USD"])