# zorro

A simple Python-based cryptocurrency algorithm framework. Create your own trading algorithms using the simple decorator and collect your own crypto data by simply specifying which Robinhood ticker to collect from.

#### COMPLETELY LOCAL, SIMPLE, AUDITABLE, ALL ON ROBINHOOD

_"Zorro, fictional character created in 1919 by writer Johnston McCulley. The masked, sword-wielding vigilante defends the poor and victimized against the forces of injustice, and his feats have been featured in virtually every form of media." - https://www.britannica.com/topic/Zorro-fictional-character_

## Usage/Examples

```python
from src.robincrypto import RobinCrypto as rc

class MyAlgo(rc):
  def __init__(self):
    super().__init__()

  @rc.run()
  def test_algorithm1(self, ticker: str):
    df = self.get_df(ticker, max=200)

    if df["Close"] >= df["Open"]:
      self.long(
        ticker,
        risk_percentage=0.2,
      )

if __name__ == "__main__":
  tickers = ["BTC-USD", "ETH-USD", "XRP-USD", "DOGE-USD"]

  ma = MyAlgo()
  ma.test_algorithm1(tickers)
```

## Run Locally

Clone the project

```bash
git clone https://github.com/anirudlappathi/zorro.git
```

Go to the project directory

```bash
cd zorro
```

Create a virtual environment and download the requirements from requirements.txt. You can also just install globally but I highly recommend to encapsulate the dependencies

```bash
pip install -r requirements.txt
```

Run commands.py to get a public and private key to create a Robinhood API-Key.

```bash
python3 -m src.commands
```

Go to Robinhood.com and get your crypto API-Key using the instructions on their website. Put the api-key and private key into the .env file to be used by the program.

```bash
ROBINHOOD_API_KEY=<ROBINHOOD_API_KEY>
ROBINHOOD_PRIVATE_KEY=<PRIVATE-KEY-GIVEN-FROM-COMMANDS.PY>
```

## Running the data collection suite

In the data-collection-config.yaml file, enter the required data and then run the datacollection.py file in a terminal

```bash
python3 -m src.datacollection
```

## Running your algorithm

In the testalgo.py file, there is an example template on how to create your own algorithm. There is also code to make sure only one position is entered. Create your own algorithm and then you can run the file with the proper class parameters using

```bash
python3 -m src.testalgo
```

## License and DISCLAIMER

[MIT](https://choosealicense.com/licenses/mit/)

This software is provided "as is," without any express or implied warranties of any kind, including but not limited to warranties of merchantability, fitness for a particular purpose, or non-infringement.

This library is intended for educational and informational purposes only. It is not a fully tested or production-ready solution and may contain bugs, errors, or incomplete functionality.

Use this software at your own risk.

By using this library, you acknowledge and agree that:

You are solely responsible for reviewing, auditing, and testing any code or strategies you implement with this software.
You assume full responsibility for any financial losses, errors, or damages resulting from its use.
The author(s) and contributor(s) of this software are not liable for any losses, damages, or claims arising from your use of the code.
Always thoroughly test your implementation with simulated trading or sandbox environments before deploying it in live trading.
