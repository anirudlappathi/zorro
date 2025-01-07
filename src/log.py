import pprint
import threading
from datetime import datetime
from dotenv import load_dotenv
import os

class log:
  _print_lock = threading.Lock()

  def __init__(self, filename: str):
    if not filename.endswith(".py"):
      raise ValueError("Filename must be a .py file")

    load_dotenv()
    self.is_debug_on = bool(os.getenv("DEBUG"))
    self.is_warn_on = bool(os.getenv("WARN"))
    self.is_info_on = bool(os.getenv("INFO"))
    self.filename = os.path.basename(filename)

  def __datetime_filename(self):
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + " " + self.filename

  def info(self, *args, end="\n", sep=None):
    if self.is_debug_on:
      with self._print_lock:
        print(f"\033[94m[{self.__datetime_filename()} INFO]\033[00m ", *args, end=end, sep=sep)

  def warn(self, *args, end="\n", sep=None):
    if self.is_debug_on:
      with self._print_lock:
        print(f"\033[91m[{self.__datetime_filename()} WARNING]\033[00m ", *args, end=end, sep=sep)

  def print(self, *args, end="\n", sep=None):
    if self.is_debug_on:
      with self._print_lock:
        print(f"[{self.__datetime_filename()}] ", *args, end=end, sep=sep)

  def pprint(self, arg, indent=1, width=80):
    if self.is_debug_on:
      with self._print_lock:
        print(f"[{self.__datetime_filename()}] ")
        pprint.pprint(arg, indent=indent, width=width)

if __name__ == "__main__":
  log.print_red("test")
