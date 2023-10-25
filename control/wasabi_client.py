import json
import requests
from time import sleep

URL = "http://localhost:37128"


def _rpc(request, wallet=None):
    request["jsonrpc"] = "2.0"
    request["id"] = "1"
    response = requests.post(
        URL + ("/" + wallet if wallet else ""), data=json.dumps(request)
    )
    if "error" in response.json():
        raise Exception(response.json()["error"])
    if "result" in response.json():
        return response.json()["result"]
    return None


def create_wallet(wallet_name):
    request = {
        "method": "createwallet",
        "params": [wallet_name, ""],
    }
    try:
        return _rpc(request)
    except:
        return None


def get_new_address(wallet_name):
    request = {
        "method": "getnewaddress",
        "params": ["label"],
    }
    return _rpc(request, wallet_name)["address"]


def get_balance(wallet_name):
    request = {
        "method": "getwalletinfo",
    }
    return _rpc(request, wallet_name)["balance"]


def get_coins(wallet_name):
    request = {
        "method": "listcoins",
    }
    return _rpc(request, wallet_name)


def wait_wallet(wallet_name):
    while True:
        sleep(0.1)
        try:
            get_balance(wallet_name)
            break
        except:
            pass


def _list_unspent_coins(wallet_name):
    request = {
        "method": "listunspentcoins",
    }
    return _rpc(request, wallet_name)


def send(wallet_name, invoices):
    coins = _list_unspent_coins(wallet_name)
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
    return _rpc(request, wallet_name)


def start_coinjoin(wallet_name):
    request = {
        "method": "startcoinjoin",
        "params": ["", "True", "True"],
    }
    return _rpc(request, wallet_name)


def stop_coinjoin(wallet_name):
    request = {
        "method": "stopcoinjoin",
    }
    return _rpc(request, wallet_name)
