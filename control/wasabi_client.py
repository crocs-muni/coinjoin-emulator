import json
import requests
from time import sleep

WALLET_NAME = "wallet"


class WasabiClient:
    def __init__(self, name="wasabi-client", port=37128):
        self.name = name
        self.port = port

    def _rpc(self, request):
        request["jsonrpc"] = "2.0"
        request["id"] = "1"
        response = requests.post(
            f"http://localhost:{self.port}/{WALLET_NAME}",
            data=json.dumps(request),
        )
        if "error" in response.json():
            raise Exception(response.json()["error"])
        if "result" in response.json():
            return response.json()["result"]
        return None

    def create_wallet(self):
        request = {
            "method": "createwallet",
            "params": [WALLET_NAME, ""],
        }
        try:
            return self._rpc(request)
        except:
            return None

    def get_new_address(self):
        request = {
            "method": "getnewaddress",
            "params": ["label"],
        }
        return self._rpc(request)["address"]

    def get_balance(self):
        request = {
            "method": "getwalletinfo",
        }
        return self._rpc(request)["balance"]

    def get_coins(self):
        request = {
            "method": "listcoins",
        }
        return self._rpc(request)

    def wait_wallet(self):
        while True:
            sleep(0.1)
            try:
                self.get_balance()
                break
            except:
                pass

    def _list_unspent_coins(self):
        request = {
            "method": "listunspentcoins",
        }
        return self._rpc(request)

    def send(self, invoices):
        coins = self._list_unspent_coins()
        coins = map(lambda x: {"transactionid": x["txid"], "index": x["index"]}, coins)
        payments = map(lambda x: {"sendto": x[0], "amount": x[1]}, invoices)

        request = {
            "method": "send",
            "params": {
                "payments": list(payments),
                "coins": list(coins),
                "feeTarget": 2,
                "password": "",
            },
        }
        return self._rpc(request)

    def start_coinjoin(self):
        request = {
            "method": "startcoinjoin",
            "params": ["", "True", "True"],
        }
        return self._rpc(request)

    def stop_coinjoin(self):
        request = {
            "method": "stopcoinjoin",
        }
        return self._rpc(request, "wallet")
