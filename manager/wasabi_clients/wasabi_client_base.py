import json
import random
import requests
from time import sleep, time

WALLET_NAME = "wallet"


class WasabiClientBase:
    def __init__(
        self,
        host="localhost",
        port=37128,
        name="wasabi-client",
        proxy="",
        version="2.0.4",
        delay=(0, 0),
        stop=(0, 0),
    ):
        self.host = host
        self.port = port
        self.name = name
        self.proxy = proxy
        self.version = version
        self.delay = delay
        self.stop = stop

    def _rpc(self, request, wallet=True, timeout=5, repeat=1):
        request["jsonrpc"] = "2.0"
        request["id"] = "1"

        if self.version < "2.0.4":
            wallet = False

        for _ in range(repeat):
            try:
                response = requests.post(
                    f"http://{self.host}:{self.port}/{WALLET_NAME if wallet else ''}",
                    data=json.dumps(request),
                    proxies=dict(http=self.proxy),
                    timeout=timeout,
                )
            except requests.exceptions.Timeout:
                continue
            if "error" in response.json():
                raise Exception(response.json()["error"])
            if "result" in response.json():
                return response.json()["result"]
            return None
        return "timeout"

    def get_status(self):
        request = {
            "method": "getstatus",
        }
        return self._rpc(request, wallet=False)

    def _create_wallet(self):
        request = {
            "method": "createwallet",
            "params": [WALLET_NAME, ""],
        }
        return self._rpc(request)

    def get_new_address(self):
        request = {
            "method": "getnewaddress",
            "params": ["label"],
        }
        return self._rpc(request)["address"]

    def get_balance(self, timeout=None):
        request = {
            "method": "getwalletinfo",
        }
        return self._rpc(request, timeout=timeout)["balance"]

    def wait_wallet(self, timeout=None):
        start = time()
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except:
                pass

            try:
                self.get_balance(timeout=5)
                return True
            except:
                pass

            sleep(0.1)
        return False

    def _list_unspent_coins(self):
        request = {
            "method": "listunspentcoins",
        }
        return self._rpc(request)

    def send(self, invoices):
        unspent_coins = self._list_unspent_coins()
        random.shuffle(unspent_coins)

        cost = sum(map(lambda x: x[1], invoices))
        coins = []
        for coin in unspent_coins:
            coins.append({"transactionid": coin["txid"], "index": coin["index"]})
            cost -= coin["amount"]
            if cost < 0:
                break
        else:
            raise Exception("Not enough BTC")

        payments = list(map(lambda x: {"sendto": x[0], "amount": x[1]}, invoices))

        request = {
            "method": "send",
            "params": {
                "payments": payments,
                "coins": coins,
                "feeTarget": 2,
                "password": "",
            },
        }
        return self._rpc(request, timeout=None)

    def start_coinjoin(self):
        request = {
            "method": "startcoinjoin",
            "params": ["", "True", "True"],
        }
        return self._rpc(request, timeout=None)

    def stop_coinjoin(self):
        request = {
            "method": "stopcoinjoin",
        }
        return self._rpc(request, "wallet")

    def list_coins(self):
        request = {
            "method": "listcoins",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def list_unspent_coins(self):
        request = {
            "method": "listunspentcoins",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def list_keys(self):
        request = {
            "method": "listkeys",
        }
        return self._rpc(request, timeout=10, repeat=3)

    def wait_ready(self):
        while True:
            try:
                self.get_status()
                break
            except:
                pass
            sleep(0.1)
