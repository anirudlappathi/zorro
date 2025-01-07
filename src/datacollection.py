import concurrent.futures
import time
import os
import threading
import concurrent
import asyncio

from typing import Dict, List, Optional
import pandas as pd
import aiofiles

from api.robinhood_api_trading import RobinhoodCryptoAPI

from src.log import log
l = log(__file__)


class DataCollection:
  """
    Collects ticker data every k seconds and stores it in a csv file given by the user. 
    Also allows an interface that gives a threading.Event() signal that signals when new data came in

    Attributes:
      folderpath (str): The path to the folder where the files will be created.
      tickers (List[str]): A list of strings containing tickers whose data will be collected.

    Usage:
      Run this class using the run() function to have the program collecting data.
  """
  def __init__(self, 
               folderpath: str,
               tickers=None, 
               interpolate_missing_data=True):
    if not tickers:
      tickers = []
    if not isinstance(tickers, list):
      raise ValueError('Tickers should be a list of string. EG: ["BTC-USD", "ETH-USD"]')
    if len(tickers) > 10:
      raise ValueError("Cannot track more than 5 tickers at a time due to API limitations.")
    
    if folderpath[-1] != "/":
      folderpath += "/"

    self.now = None
    self.tickers: List[str] = tickers
    self.folderpath: str = folderpath
    self.interpolate_missing_data: bool = interpolate_missing_data

    self.__robinhood_api = RobinhoodCryptoAPI()
    self.__inmemory_ohlc: Dict[str, Optional[pd.Dataframe]] = {}
    if self.interpolate_missing_data:
      self.__backup_price: Dict[str, float] = { ticker: -1 for ticker in self.tickers }
    self.__current_price: Dict[str, float] = { ticker: -1 for ticker in self.tickers }
    self.__minute_ohlc_data = {
      ticker: {
        "Open": None,
        "High": float("-inf"),
        "Low": float("inf"),
        "Close": None,
      } for ticker in self.tickers
    }

    self.__ticker_signals: Dict[threading.Event] = {ticker: threading.Event() for ticker in self.tickers}
    self.__is_ticker_running = {ticker: False for ticker in self.tickers}
    self.__is_ticker_signal_active = {ticker: False for ticker in self.tickers}
    self.__ticker_threads: List = []
    self.__stop_event: threading.Event = threading.Event()
    self.__candle_finalizer_executor = concurrent.futures.ThreadPoolExecutor()

  def run(self):
    if self.tickers == []:
      raise RuntimeError("Cannot use run() if no tickers are set. Use set_tickers() or initialize the class with tickers to use the run() function.")

    for ticker in self.tickers:
      self._try_load_inmemory_ohcl(ticker)

    threading.Thread(target=self.__run_collect_minute_data).start()

    self.__ticker_threads = []
    for ticker in self.tickers:
      if ticker not in self.__is_ticker_running:
        self._add_ticker(ticker)
      if not self.__is_ticker_running[ticker]:
        self.__ticker_threads.append(self.__candle_finalizer_executor.submit(self.__run_finalize_minute_data, ticker))
  
    try:
      concurrent.futures.wait(self.__ticker_threads)
    except KeyboardInterrupt:
      self.stop()

  def __run_finalize_minute_data(self, ticker: str):
    last_minute = None
    last_time = None

    while not self.__stop_event.is_set():
      self.now = time.localtime()
      current_minute = self.now.tm_min

      if last_minute is not None and current_minute != last_minute:
        asyncio.run(self.__finalize_ohlc(ticker, last_time))

      last_minute = current_minute
      last_time = self.now

      time.sleep(0.1)

  def __run_collect_minute_data(self):
    while not self.__stop_event.is_set():
      self.__collect_minute_data()
      time.sleep(2)

  def __collect_minute_data(self):
    # TODO: Potentially get a better estimate with estimate_price api endpoint
    resp = self.__robinhood_api.get_best_bid_ask(*self.tickers)

    if not resp or not resp["results"]:
      l.warn(f"Robinhood API is not responding at this time")
      return

    for resp_data in resp["results"]:
      ticker = resp_data["symbol"]
      current_price = float(resp_data["price"])
      if self.__minute_ohlc_data[ticker]["Open"] is None:
        self.__minute_ohlc_data[ticker]["Open"] = current_price

      if current_price > self.__minute_ohlc_data[ticker]["High"]:
        self.__minute_ohlc_data[ticker]["High"] = current_price

      if current_price < self.__minute_ohlc_data[ticker]["Low"]:
        self.__minute_ohlc_data[ticker]["Low"] = current_price
        
      self.__minute_ohlc_data[ticker]["Close"] = current_price
      self.__current_price[ticker] = current_price

  async def __finalize_ohlc(self, ticker: str, now: str):
    timestamp = self.get_timestamp(now)

    curr_minute_ohlc = self.__minute_ohlc_data[ticker]
    open_, high_, low_, close_ = curr_minute_ohlc["Open"], curr_minute_ohlc["High"], curr_minute_ohlc["Low"], curr_minute_ohlc["Close"]

    if open_ is None:
      if not self.interpolate_missing_data:
        self.__reset_minute_ohlc_data(ticker)
      l.warn(f"[{ticker}] data was not collected over the minute. Utilizing backup data")
      backup_minute_ohlc = self.__backup_price[ticker]
      open_, high_, low_, close_ = backup_minute_ohlc["Open"], backup_minute_ohlc["High"], backup_minute_ohlc["Low"], backup_minute_ohlc["Close"]

    self.__add_inmemory_ohlc(ticker, timestamp, open_, high_, low_, close_)

    filepath = self._get_filepath(ticker)
    if not os.path.exists(filepath):
      async with aiofiles.open(filepath, "w") as file:
        await file.write("Timestamp,Open,High,Low,Close\n")

    async with aiofiles.open(filepath, "a") as file:
      await file.write(f"{timestamp},{open_},{high_},{low_},{close_}\n")

    self.__reset_minute_ohlc_data(ticker)
    self.__ticker_signals[ticker].set()

  def _try_load_inmemory_ohcl(self, ticker) -> int:
    if ticker in self.__inmemory_ohlc:
      return -1
    filepath: str = self._get_filepath(ticker)
    if not os.path.exists(filepath):
      self.__inmemory_ohlc[ticker] = pd.DataFrame(columns=["Timestamp", "Open", "High", "Low", "Close"])
      with open(filepath, "w") as file:
        file.write("Timestamp,Open,High,Low,Close\n")
      l.info(f"Loaded 0 lines of previous contiguous {ticker} data (UNCOLLECTED DATA)")
      return 0
    
    with open(filepath, "r") as file:
      prev_k_contiguous_lines = file.readlines()

    curr_minute = self.__get_curr_time_data()
    i = 1
    while i < len(prev_k_contiguous_lines) + 1:
      old_timestamp = prev_k_contiguous_lines[-i].split(",")[0]
      old_timestamp_split = old_timestamp.split(":")
      if len(old_timestamp_split) < 2:
        l.info(f"Loaded {i - 1} lines of previous contiguous {ticker} OHLC data")
        break
      old_minute = float(old_timestamp.split(":")[-2])
      if (old_minute + i) % 60 != curr_minute:
        l.info(f"Loaded {i - 1} lines of previous contiguous {ticker} OHLC data")
        break
      i += 1
    
    if i == 1:
      self.__inmemory_ohlc[ticker] = pd.DataFrame(columns=["Timestamp", "Open", "High", "Low", "Close"])
    else:
      self.__inmemory_ohlc[ticker] = pd.DataFrame(
          [[v if i == 0 else float(v) for i, v in enumerate(line.strip().split(","))] for line in prev_k_contiguous_lines[-i + 1:]],
          columns=["Timestamp", "Open", "High", "Low", "Close"]
      )
    return i-1

  def __get_curr_time_data(self) -> float:
      curr_time = pd.Timestamp.now()
      curr_time = ":".join(str(curr_time).split(".")[:-1])
      curr_minute = float(curr_time.split(":")[-2])
      return curr_minute

  def __add_inmemory_ohlc(self,
                          ticker: str,
                          timestamp: str,
                          open_: float,
                          high_: float,
                          low_: float,
                          close_: float):
    new_row: Dict = {
      "Timestamp": timestamp,
      "Open": open_,
      "High": high_,
      "Low": low_,
      "Close": close_,
    }

    df: pd.DataFrame = self.__inmemory_ohlc[ticker]
    if not df.empty:
      self.__inmemory_ohlc[ticker] = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    else:
      self.__inmemory_ohlc[ticker] = pd.DataFrame([new_row], columns=["Timestamp", "Open", "High", "Low", "Close"])

    if self.interpolate_missing_data:
      self.__backup_price[ticker] = new_row

  def __reset_minute_ohlc_data(self, ticker: str):
    self.__minute_ohlc_data[ticker] = {
      "Open": None,
      "High": float("-inf"),
      "Low": float("inf"),
      "Close": None,
    }

  def _get_filepath(self, ticker: str):
    return os.path.join(self.folderpath, f"{ticker}-1min-data.csv")

  def __add_last_line(self, ticker: str) -> None:
    """
    Adds the last line of a tickers csv data to its OHLC df by reading the
    last line of it's respective CSV. This is used for the background running
    data collection where it adds to the df after the signal is read that a new
    line was added.
    """
    if not os.path.exists(self._get_filepath(ticker)):
      raise FileExistsError(f"File for ticker {ticker} does not exist.")
    last_line = self.__get_last_line(ticker)
    timestamp, open_, high_, low_, close_ = last_line.split(",")
    open_, high_, low_, close_ = float(open_), float(high_), float(low_), float(close_)
    self.__add_inmemory_ohlc(ticker, timestamp, open_, high_, low_, close_)

  def __get_last_line(self, ticker: str) -> Optional[str]:
    filepath = self._get_filepath(ticker)
    with open(filepath, 'r') as file:
        file.seek(0, 2)
        if file.tell() == 0:
          l.warn(f"File for {ticker} is empty.")
          return None
        file.seek(0)
        first_line = file.readline().strip()
        if not first_line or file.readline() == '':
          l.warn(f"File for {ticker} only contains the headers. No last-line found.")
          return None
        file.seek(0)

        file.seek(0, 2)
        file_pos = file.tell()

        while file_pos > 0:
            file_pos -= 1
            file.seek(file_pos)
            char = file.read(1)

            if char == '-' and file_pos != file.tell():
                file_pos -= 7
                file.seek(file_pos)
                last_line = file.readline().strip()
                return last_line
            
        file.seek(0)
        last_line = file.readline().strip()
        return last_line

  def __get_last_timestamp(self, ticker: str) -> str:
    last_line = self.__get_last_line(ticker)
    if last_line is None:
      raise ValueError(f"No timestamp found within the {ticker} file.")
    return last_line.split(",")[0]
    
  def __minute_from_timestamp(self, timestamp: str) -> int:
    return int(timestamp.split(":")[-2])
  
  def get_price_estimate(self, ticker: str):
    # TODO: Ensure this works
    # l.warn("Cannot get active price estimate with data collection running in background. Giving candlestick close.")
    if ticker not in self.__minute_ohlc_data:
      raise ValueError("Cannot get data for ticker not in data collection.")
    if not self.__minute_ohlc_data[ticker] or self.__minute_ohlc_data[ticker] == { "Open": None, "High": float("-inf"), "Low": float("inf"), "Close": None,}:
      last_line = self.__get_last_line(ticker)
      return float(last_line.split(",")[-1])
    return self.__current_price[ticker]
  
  def get_ticker_df(self, ticker: str, max=None) -> pd.DataFrame:
    self._try_load_inmemory_ohcl(ticker)
    if ticker not in self.__inmemory_ohlc:
      # l.warn("Attempting to get OHCL data that has not been collected. Returning empty df")
      self.__inmemory_ohlc[ticker] = pd.DataFrame(columns=["Timestamp", "Open", "High", "Low", "Close"])
      
    if self.__inmemory_ohlc[ticker].empty:
      l.warn("Attempting to get OHCL data that either has no data or is not currently contiguous.")

    if max:
      return self.__inmemory_ohlc[ticker].iloc[-max:]
    return self.__inmemory_ohlc[ticker]

  def _add_ticker(self, ticker: str) -> None:
    filepath: str = self._get_filepath(ticker)
    if not os.path.exists(filepath):
      raise ValueError("Cannot use data for a tickers who's data is not being collected")
    if ticker not in self.tickers:
      self.tickers.append(ticker)
    if ticker not in self.__current_price:
      self.__current_price[ticker] = -1

    if ticker not in self.__minute_ohlc_data:
      self.__minute_ohlc_data[ticker] = {
        "Open": None,
        "High": float("-inf"),
        "Low": float("inf"),
        "Close": None,
      }
    if ticker not in self.__is_ticker_running:
      self.__is_ticker_running[ticker] = False

    if ticker not in self.__ticker_signals:
      self.__ticker_signals[ticker] = threading.Event()

    if ticker not in self.__is_ticker_signal_active:
      self.__is_ticker_signal_active[ticker] = False


  def get_candle_signal(self, ticker: str) -> threading.Event:
    if self.__can_activate_candle_signal(ticker):
      threading.Thread(target=self.__activate_candle_signal, args=(ticker,)).start()
    return self.__ticker_signals[ticker]

  def __can_activate_candle_signal(self, ticker: str) -> bool:
    if ticker not in self.__is_ticker_signal_active:
      self._add_ticker(ticker)
    if self.__is_ticker_signal_active[ticker] is True:
      # l.warn(f"Attempting to activate already active candle ticker for {ticker}")
      return False
    return True

  def __activate_candle_signal(self, ticker: str, check_interval=0.1) -> None:
    if not self.__can_activate_candle_signal(ticker):
      return
    self.__is_ticker_signal_active[ticker] = True

    last_minute = self.__minute_from_timestamp(self.__get_last_timestamp(ticker))
    while not self.__stop_event.is_set():
      curr_minute = self.__minute_from_timestamp(self.__get_last_timestamp(ticker))
      if curr_minute != last_minute:
        self.__add_last_line(ticker)
        self.__ticker_signals[ticker].set()
      last_minute = curr_minute
      time.sleep(check_interval)

    self.__is_ticker_signal_active[ticker] = False
  
  def get_timestamp(self, t="now") -> str:
    if t == "now":
      t = self.now
    return time.strftime("%Y-%m-%d %H:%M:%S", t)
  
  def stop(self):
    self.__stop_event.set()

if __name__ == "__main__":
  import yaml

  datacollection_config_path = os.path.join(__file__, "data-collection-config.yaml")
  with open("data-collection-config.yaml") as stream:
    try:
        datacollection_config = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        print(exc)

  if "ticker_data_folderpath" not in datacollection_config or datacollection_config["ticker_data_folderpath"] is None:
    raise ValueError('"ticker_data_folderpath" is not in the data-collection-config.yaml file. Please enter a valid folderpath.')
  if "max_risk" not in datacollection_config or datacollection_config["max_risk"] is None:
    raise ValueError('"max_risk" is not in the data-collection-config.yaml file. Please enter a valid total risk percentage.')
  if "tickers" not in datacollection_config or datacollection_config["tickers"] is None:
    raise ValueError('"tickers" is not in the data-collection-config.yaml file. Please enter a valid list of tickers.')
  if "interpolate_missing_data" not in datacollection_config or datacollection_config["interpolate_missing_data"] is None:
    raise ValueError('"interpolate_missing_data" is not in the data-collection-config.yaml file. Please enter true or false for interpolate_missing_data.')

  cd = DataCollection(
    folderpath=datacollection_config["ticker_data_folderpath"],
    tickers=list(datacollection_config["tickers"]),
    interpolate_missing_data=bool(datacollection_config["interpolate_missing_data"]),
  )
  cd.run()
