import json

import requests
from time import sleep, time
from urllib3.exceptions import InsecureRequestWarning
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


WALLET_NAME = "wallet"
PASSWORD = "password"
WALLET_TYPE = "sw"
BTC = 100_000_000


class JoinmarketConflictException(Exception):
    def __init__(self, message, response):
        super().__init__(message)
        self.response = response



class JoinMarketClientServer:
    def __init__(
        self,
        host="localhost",
        port=28183,
        walletname=WALLET_NAME,
        name="joinmarket-client-server",
        proxy="",
        version="",
        type="maker",
        delay=(0, 0),
        stop=(0, 0),
    ):
        self.host = host
        self.port = port
        self.walletname = walletname  # Store walletname as an instance variable
        self.name = name
        self.proxy = proxy
        self.version = version
        self.type = type
        self.maker_running = False
        self.coinjoin_in_process = False
        self.coinjoin_start = 0
        self.delay = delay
        self.stop = stop
        self.token = ""
        self.refresh_token = ""

    def _rpc(self, method, endpoint, json_data=None, timeout=5, repeat=4) -> dict:
        headers = {}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        response = None
        for _ in range(repeat):
            try:
                response = requests.request(
                    method=method,
                    url=f"https://{self.host}:{self.port}/api/v1{endpoint}",
                    json=json_data or {},
                    headers=headers,
                    proxies=dict(http=self.proxy),
                    timeout=timeout,
                    verify=False,
                )
            except requests.exceptions.Timeout:
                continue
            except InsecureRequestWarning:
                continue

            if response.status_code == 401:
                self.unlock_wallet()
                headers['Authorization'] = f'Bearer {self.token}'
                continue

            if response.status_code == 409:
                raise JoinmarketConflictException(f"Error {response.status_code}: {response.text}", response)

            if response.status_code >= 400:
                try:
                    print(response.json())
                    error_message = response.json().get("message", "Unknown error")
                except json.JSONDecodeError:
                    error_message = response.text
                raise Exception(f"Error {response.status_code}: {error_message}")

            return response.json()

        if response is not None:
            return response.json()

        raise Exception("timeout")

    def get_status(self):
        method = "GET"
        endpoint = "/session"
        response = self._rpc(method, endpoint)
        self.maker_running = response.get("maker_running", False)
        self.coinjoin_in_process = response.get("coinjoin_in_process", False)
        return response

    def _create_wallet(self, walletname=None):
        """Create a new wallet and store its name."""
        method = "POST"
        endpoint = "/wallet/create"
        self.walletname = walletname or self.walletname or WALLET_NAME
        data = {
            "walletname": self.walletname,
            "password": PASSWORD,
            "wallettype": WALLET_TYPE
        }
        response = self._rpc(method, endpoint, json_data=data)
        self.token = response.get("token", "")
        self.refresh_token = response.get("refresh_token", "")
        return response

    def unlock_wallet(self, password=None):
        """Unlock an existing wallet using the stored walletname."""
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/unlock"
        json_data = {"password": password or PASSWORD}
        response = self._rpc(method, endpoint, json_data=json_data)
        self.token = response.get("token", "")
        self.refresh_token = response.get("refresh_token", "")
        return response


    def wait_wallet(self, timeout=None):
        start = time()
        while timeout is None or time() - start < timeout:
            try:
                self._create_wallet()
            except Exception as e:
                pass

            try:
                self.get_balance()
                return True
            except Exception as e:
                pass

            sleep(0.1)
        return False


    def display_wallet(self):
        """Get detailed breakdown of wallet contents by account."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/display"
        response = self._rpc(method, endpoint)
        return response

    def get_balance(self):
        """Retrieve the available balance of the wallet.
        Returns: str: The available balance as a string in BTC (e.g., '0.00000000').
        Raises: Exception: If the balance information cannot be retrieved.
        """
        response = self.display_wallet()
        try:
            available_balance = response['walletinfo']['available_balance']
            return int(float(available_balance) * BTC)
        except KeyError as e:
            raise Exception(f"Could not retrieve available balance: {e}")

    def get_yieldgen_report(self):
        """Get the latest report on yield-generating activity."""
        method = "GET"
        endpoint = "/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response

    def get_new_address(self, mixdepth=0):
        """Get a fresh address in the given account for depositing funds."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/address/new/{mixdepth}"
        response = self._rpc(method, endpoint)
        return response['address']

    def get_new_timelock_address(self, lockdate):
        """Get a fresh timelock address for depositing funds to create a fidelity bond."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/address/timelock/new/{lockdate}"
        response = self._rpc(method, endpoint)
        return response

    def list_utxos(self):
        """List details of all UTXOs currently in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
        response = self._rpc(method, endpoint)
        return response

    def start_maker(
        self,
        txfee,
        cjfee_a,
        cjfee_r,
        ordertype,
        minsize,
    ):
        """
        Start the yield generator service with the specified configuration.
        - txfee: str or int, e.g., "0" (absolute fee in satoshis)
        - cjfee_a: str or int, e.g., "5000" (absolute coinjoin fee in satoshis)
        - cjfee_r: str or float, e.g., "0.00004" (relative coinjoin fee as a fraction)
        - ordertype: str, e.g., "reloffer" or "absoffer"
        - minsize: str or int, minimum coinjoin size in satoshis. Should be higher then 27300sats
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/maker/start"
        json_data = {
            "txfee": str(txfee),
            "cjfee_a": str(cjfee_a),
            "cjfee_r": str(cjfee_r),
            "ordertype": ordertype,
            "minsize": str(minsize)
        }

        try:
            response = self._rpc(method, endpoint, json_data=json_data)
        except JoinmarketConflictException as e:
            print("Could not start maker without confirmed balance")
            response = e.response

        return response

    def stop_maker(self):
        """Stop the yield generator service."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/maker/stop"
        # When stopping not running maker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

    def start_coinjoin(
        self,
        mixdepth,
        amount_sats,
        counterparties,
        destination,
        txfee=None
    ):
        """
        Initiate a coinjoin as taker.
        - mixdepth: int, the mixdepth to spend from
        - amount_sats: int, amount in satoshis to coinjoin
        - counterparties: int, number of counterparties to coinjoin with
        - destination: str, address to send the coinjoined funds to
        - txfee: optional, int, Bitcoin miner fee to use for transaction
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/coinjoin"
        json_data = {
            "mixdepth": mixdepth,
            "amount_sats": amount_sats,
            "counterparties": counterparties,
            "destination": destination
        }
        if txfee is not None:
            json_data["txfee"] = txfee
        response = self._rpc(method, endpoint, json_data=json_data)
        return response

    def run_schedule(self, destination_addresses, tumbler_options=None):
        """
        Create and run a schedule of transactions.
        - destination_addresses: list of str, addresses to send funds to
        - tumbler_options: optional, dict, additional tumbler configuration options
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data = {
            "destination_addresses": destination_addresses,
        }
        if tumbler_options:
            json_data["tumbler_options"] = tumbler_options
        response = self._rpc(method, endpoint, json_data=json_data)
        return response

    def get_schedule(self):
        """Get the schedule that is currently running."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        response = self._rpc(method, endpoint)
        return response

    def stop_coinjoin(self):
        """Stop a running coinjoin attempt."""
        if self.type == "taker" and self.coinjoin_in_process:
            return self.stop_taker()
        elif self.type == "maker" and self.maker_running:
            return self.stop_maker()
        else:
            print("No coinjoin in process")
            return True

    def stop_taker(self):
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/taker/stop"
        # When stopping not running taker, returns 401 response
        response = self._rpc(method, endpoint)
        return response

    def send(self, addressed_fundings):
        try:
            for address, amount in addressed_fundings:
                self.simple_send(destination_address=address, amount_sats=amount)
                print(f"- sent {amount} sats to {address}")
                sleep(5)  # The btc node needs time to process the transaction
        except Exception as e:
            print(f"- error during fund distribution: {e}")
            raise e


    def simple_send(self, destination_address, amount_sats, mixdepth=0, txfee=5000):
        """
        Send funds to a single address without coinjoin.
        - destination_address: str, address to send funds to
        - amount_sats: int, amount in satoshis to send
        - mixdepth: int, the mixdepth to spend from
        - txfee: int, miner fee in satoshis
        """
        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/direct-send"
        json_data = {
            "destination": destination_address,
            "amount_sats": amount_sats,
            "txfee": txfee,
            "mixdepth": mixdepth,
        }
        start = time()
        while time() - start < 30:
            try:
                response = self._rpc(method, endpoint, json_data=json_data)
                return response
            except Exception as e:
                print(e)
                sleep(2)

        print("Failed to send funds, attempt timed out.")

        return False

    def list_unspent_coins(self):
        """List all unspent coins in the wallet."""
        method = "GET"
        endpoint = f"/wallet/{self.walletname}/utxos"
        response = self._rpc(method, endpoint)
        return response

    def list_transactions_maker(self):
        """List all transactions in the wallet."""
        method = "GET"
        endpoint = f"/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response


    def list_coins(self):
        """List all coins in the wallet."""
        return "This method is not available in joinmarket"
        # method = "GET"
        # endpoint = f"/wallet/{self.walletname}/coins"
        # response = self._rpc(method, endpoint)
        # return response

    def list_keys(self):
        """List all keys in the wallet."""
        return "This method is not available in joinmarket"
        # method = "GET"
        # endpoint = f"/wallet/{self.walletname}/keys"
        # response = self._rpc(method, endpoint)
        # return response

    def get_history(self):
        return "This method is not available in joinmarket"
