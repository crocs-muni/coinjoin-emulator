import requests
import json

URL = "http://localhost:18443"
WALLET = "wallet"


def _rpc(request, wallet=None):
    request["jsonrpc"] = "2.0"
    request["id"] = "1"
    response = requests.post(
        URL + ("/wallet/" + wallet if wallet else ""),
        data=json.dumps(request),
        auth=("user", "password"),
    )
    return response.json()["result"]


def get_block_count():
    request = {
        "method": "getblockcount",
        "params": [],
    }
    return _rpc(request)


def mine_block(count=1):
    initial_block_count = get_block_count()

    request = {
        "method": "getnewaddress",
        "params": [],
    }
    address = _rpc(request, WALLET)

    request = {
        "method": "generatetoaddress",
        "params": [count, address],
    }
    _rpc(request)

    return get_block_count() - initial_block_count == count


def fund_address(address, amount):
    request = {
        "method": "sendtoaddress",
        "params": [address, amount],
    }
    _rpc(request, WALLET)
