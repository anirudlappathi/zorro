from typing import Dict, List
from functools import wraps
import concurrent.futures
import threading
import uuid
import time 
import os 

from api.robinhood_api_trading import RobinhoodCryptoAPI
from src.datacollection import DataCollection

import pandas as pd
import concurrent

from src.log import log
l = log(__file__)

class RobinCrypto:

  def __init__(self, 
               ticker_data_folderpath: str =None, 
               max_risk: float=None):
    if ticker_data_folderpath is None:
      import yaml
      with open("data-collection-config.yaml") as stream:
        try:
            datacollection_config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
      if "ticker_data_folderpath" not in datacollection_config or datacollection_config["ticker_data_folderpath"] is None:
        raise ValueError('"ticker_data_folderpath" is not in the data-collection-config.yaml file. Please enter a valid folderpath or enter an argument for this value.')
      if "max_risk" not in datacollection_config or datacollection_config["max_risk"] is None:
        raise ValueError('"max_risk" is not in the data-collection-config.yaml file. Please enter a valid total risk percentage or enter an argument for this value.')
      self.ticker_data_folderpath = datacollection_config["ticker_data_folderpath"]
      self.max_risk = datacollection_config["max_risk"]
    else:
      self.ticker_data_folderpath = ticker_data_folderpath
      self.max_risk: float = max_risk

    if not os.path.exists(ticker_data_folderpath):
      raise ValueError(f"Folderpath {ticker_data_folderpath} does not exist. Please enter a valid path containing your collected data.")
    if max_risk != 1 and (not isinstance(max_risk, float) or max_risk <= 0):
      raise ValueError("max_risk must be a float of the maximum percent of your buying power you are willing to risk in a single trade.")
    
    self.ct = RobinhoodCryptoAPI()
    self.data = DataCollection(ticker_data_folderpath)
    self.__stop_event = threading.Event()
    self.__ticker_analysis_executor = concurrent.futures.ThreadPoolExecutor()
  
  def get_df(self, ticker: str, max=None) -> pd.DataFrame:
    return self.data.get_ticker_df(ticker, max=max)

  def run():
    def decorator(func):
      @wraps(func)
      def wrapper(self, tickers: List[str]):
        self.__validate_tickers(tickers)
        def __run_ticker(ticker: str, func):
          self.data._add_ticker(ticker)
          self.data._try_load_inmemory_ohcl(ticker)
          signal = self.data.get_candle_signal(ticker)
          while True:
            signal.wait()
            func(self, ticker)
            signal.clear()

        threads = []
        for ticker in tickers:
          ticker_t = threading.Thread(target=__run_ticker, args=(ticker, func))
          threads.append(ticker_t)
          ticker_t.start()

      return wrapper
    return decorator

  def long(self, 
           ticker: str,
           single_position=True,
           risk_amount=None,
           risk_percentage=None,
           stop_loss_percent=None, 
           take_price_percent=None) -> threading.Event():
      if risk_amount is not None and risk_percentage is not None:
        raise ValueError("Must only use either risk_amount or risk_percentage. Cannot utilize both parameters at once.")
      if risk_amount is None and risk_percentage is None:
        raise ValueError("Must specify either the numerical amount of currency you are risking (risk_amount) or a percentage of your buying power that you are risking (risk_percentage).")
      if risk_amount and risk_amount >= self.max_risk:
        l.warn(f"VOIDING LONG CALL [{ticker}][risk_amount: {risk_amount}] because risk amount is greater than max_risk")
        return
      if stop_loss_percent < 0 or take_price_percent < 0:
        self.in_position[ticker] = False      
        l.warn(f"VOIDING LONG CALL [{ticker}] Stop loss and take price percentages must be greater than 0. Cancelling from long position")
        return

      account_data: Dict[str] = self.ct.get_account()
      buying_power: float = float(account_data["buying_power"])

      if risk_percentage and risk_percentage >= self.max_risk:
        l.warn(f"VOIDING LONG CALL [{ticker}][risk_percentage: {risk_percentage}] because risk amount ({risk_percentage}) is greater than max_risk")
        return
      
      if risk_amount:
        risk_percentage = risk_amount / buying_power

      sold_event = threading.Event()

      threading.Thread(target=self.__long_position, args=(ticker, risk_percentage, stop_loss_percent, take_price_percent, account_data, sold_event)).start()

      return sold_event


  def __long_position(self, 
                      ticker: str, 
                      risk_percentage: float, 
                      stop_loss_percent: float, 
                      take_price_percent: float,
                      account_data: Dict,
                      sold_event: threading.Event) -> None:
    
    close = self.data.get_price_estimate(ticker)
    stop_loss = None
    take_price = None
    if stop_loss_percent:
      stop_loss: float = close * (1 - stop_loss_percent)
    if take_price_percent:
      take_price: float = close * (1 + take_price_percent)

    buying_power = float(account_data["buying_power"])
    quote_amount = buying_power * risk_percentage
    asset_amount = round(quote_amount / close, 6)

    client_order_id = str(uuid.uuid4())
    order_response = self.ct.place_order(
      client_order_id=client_order_id,
      side="buy",
      order_type="market",
      symbol=ticker,
      order_config={
        "asset_quantity": asset_amount
      }
    )

    retry_time = 10
    while retry_time >= 0:
      if order_response and "id" in order_response:
        self.__wait_order_fill(ticker, order_response["id"])
        break
      retry_time -= 1
      time.sleep(2)

    l.info(f"[{ticker}] LONG POSITION FILLED [CLOSE: {close}][SL:{stop_loss}][TP:{take_price}][QUOTE_AMT: {quote_amount}][ASSET_AMT: {asset_amount}]")

    if not stop_loss_percent and not take_price_percent:
      sold_event.set()
      return

    if take_price and not stop_loss:
      tp_client_order_id = str(uuid.uuid4())
      self.ct.place_order(
        client_order_id=tp_client_order_id,
        side="sell",
        order_type="limit",
        symbol=ticker,
        order_config={
          "asset_quantity": asset_amount,
          "stop_price": f"{take_price:.2f}",
          "time_in_force": "gtc"
        },
      )
      sold_event.set()
      return
  
    sl_client_order_id = str(uuid.uuid4())
    self.ct.place_order(
      client_order_id=sl_client_order_id,
      side="sell",
      order_type="stop_loss",
      symbol=ticker,
      order_config={
        "asset_quantity": asset_amount,
        "stop_price": f"{stop_loss:.2f}",
        "time_in_force": "gtc"
      },
    )

    __ticker_signal = self.data.get_candle_signal(ticker)

    while not self.__stop_event.is_set():
      curr_est_price = self.data.get_price_estimate(ticker)

      stop_loss_status = self.ct.get_order(sl_client_order_id)
      if stop_loss_status.get("status") == "filled":
        l.info(f"[{ticker}]: Stop-loss executed for {client_order_id} at {curr_est_price}. {stop_loss} lost on trade.")
        break

      if curr_est_price and curr_est_price >= take_price:
        l.info(f"[{ticker}]: Take-price executed for {client_order_id} at {curr_est_price}. {take_price} lost on trade.")

        tp_client_order_id = str(uuid.uuid4())
        take_price_response = self.ct.place_order(
          client_order_id=tp_client_order_id,
          side="sell",
          order_type="market",
          symbol=ticker,
          order_config={
            "asset_quantity": asset_amount
          }
        )

        retry_time = 10
        while retry_time >= 0:
          if order_response and "id" in order_response:
            self.__wait_order_fill(ticker, order_response["id"])
            break
          retry_time -= 1
          time.sleep(2)

        self.__wait_order_fill(ticker, take_price_response["id"])
        break

      __ticker_signal.wait()
      time.sleep(0.01)
      __ticker_signal.clear()
      sold_event.set()

    # self.in_position[ticker] = False

  def __wait_order_fill(self, ticker: str, order_id: str, error_retry=3):
    while True:
      order_status = self.ct.get_order(order_id)
      if "error" in order_status:
        if error_retry == 0:
          l.warn("Long position order request did not go through. Voiding long call and continuing.")
          self.in_position[ticker] = False
          return
        error_retry -= 1
        time.sleep(1)
        continue
      if order_status["state"] == "cancelled" or order_status["state"] == "failed":
        l.warn("Long call was either cancelled or failed. Voiding long call and continuing.")
        self.in_position[ticker] = False
        return
      if order_status["state"] == "filled":
        return
      l.info(f"{order_id}: Waiting to fill. State is {order_status["state"]}")
      time.sleep(1)

  def __validate_tickers(self, tickers: List[str]):
    # making sure the user is running the tickers in their datafolder
    for ticker in tickers:
      ticker_filename = self.data._get_filepath(ticker)
      ticker_filepath = os.path.join(self.ticker_data_folderpath, ticker_filename)
      if not os.path.exists(ticker_filepath):
        raise ValueError(f"""[{ticker}] is not having it's data collected currently. 
                         Follow the instructions in DATACOLLECTION.md to learn how
                         to begin collecting data for a ticker.""")

    # checking the tickers exist on robinhood
    resp = self.ct.get_best_bid_ask(*tickers)  
    if not resp:
      raise ConnectionError("Robinhood Crypto API is not connecting")
    if "errors" in resp:
      raise ValueError(resp["errors"][0]["detail"])
  
  def stop(self):
    self.__stop_event.set()
    self.__ticker_analysis_executor.shutdown(wait=True)

if __name__ == "__main__":

  ct = RobinCrypto(
    ticker_data_folderpath="/Users/anirud/Downloads/projects/crypto-trading-bot/data", 
    max_risk=0.5
    # tickers=["BTC-USD", "ETH-USD", "DOGE-USD", "XRP-USD"],
  )
  ct.run()
