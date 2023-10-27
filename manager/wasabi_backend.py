import json
import requests
from time import sleep

WALLET_NAME = "wallet"


class WasabiBackend:
    def __init__(self, name="wasabi-backend", port=37127):
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

    def _get_status(self):
        response = requests.get(
            f"http://localhost:{self.port}/api/v4/btc/Blockchain/status"
        )
        return response.json()

    def wait_ready(self):
        while True:
            try:
                self._get_status()
                break
            except:
                pass
            sleep(0.1)
