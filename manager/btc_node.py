import requests
import json
from time import sleep

URL = "http://localhost:18443"
WALLET = "wallet"


class BtcNode:
    def __init__(self, name="btc-node"):
        self.name = name

    def _rpc(self, request, wallet=None):
        request["jsonrpc"] = "2.0"
        request["id"] = "1"
        response = requests.post(
            URL + ("/wallet/" + WALLET if wallet else ""),
            data=json.dumps(request),
            auth=("user", "password"),
        )
        if response.json()["error"] is not None:
            raise Exception(response.json()["error"])
        return response.json()["result"]

    def get_block_count(self):
        request = {
            "method": "getblockcount",
            "params": [],
        }
        return self._rpc(request)

    def get_block_hash(self, height):
        request = {
            "method": "getblockhash",
            "params": [height],
        }
        return self._rpc(request)

    def get_block_info(self, block_hash):
        request = {
            "method": "getblock",
            "params": [block_hash, 2],
        }
        return self._rpc(request)

    def mine_block(self, count=1):
        initial_block_count = self.get_block_count()

        request = {
            "method": "getnewaddress",
            "params": [],
        }
        address = self._rpc(request, WALLET)

        request = {
            "method": "generatetoaddress",
            "params": [count, address],
        }
        self._rpc(request)

        return self.get_block_count() - initial_block_count == count

    def fund_address(self, address, amount):
        request = {
            "method": "sendtoaddress",
            "params": [address, amount],
        }
        self._rpc(request, WALLET)

    def wait_ready(self):
        while True:
            try:
                block_count = self.get_block_count()
                if block_count > 100:
                    break
            except Exception:
                pass
            sleep(0.1)
