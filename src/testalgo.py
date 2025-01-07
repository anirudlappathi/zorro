from typing import List
from src.robincrypto import RobinCrypto as rc
from src.log import log
import threading
import talib
from typing import Dict, Optional
l = log(__file__)

tickers = ["BTC-USD", "ETH-USD", "XRP-USD", "DOGE-USD"]
class TestAlgorithm(rc):

  def __init__(self):
    super().__init__()

    self.in_position: Dict[Optional[threading.Event]] = {ticker: None for ticker in tickers}

  def __ao(self, high, low):
    median_price = (high + low) / 2
    ao_short = talib.SMA(median_price, timeperiod=5)
    ao_long = talib.SMA(median_price, timeperiod=34)
    return ao_short - ao_long

  @rc.run()
  def algo1(self, ticker: str):
    df = self.get_df(ticker, max=250)

    if df["Close"] >= df["Open"]:
      if self.in_position[ticker].is_set():
        self.in_position[ticker] = None
      if self.in_position[ticker] is None:
        l.info(f"[{ticker}] LONG POSITION")
        sold = self.long(ticker, risk_percentage=0.2, stop_loss_percent=0.02, take_price_percent=0.01)
        self.in_position[ticker] = sold
    
if __name__ == "__main__":
  ta = TestAlgorithm()
  ta.algo1(tickers)