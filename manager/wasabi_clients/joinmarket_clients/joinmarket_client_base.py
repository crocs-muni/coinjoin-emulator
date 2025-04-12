import json
from typing import List
import requests
from time import sleep, time
from urllib3.exceptions import InsecureRequestWarning
import urllib3
from bip_utils import Bip39SeedGenerator, Bip32Slip10Secp256k1

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
        offers=None,
        tumbler_options=None,
        time_between_rounds=0,
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
        self.next_coinjoin_allowed = delay[0]
        self.time_between_rounds = time_between_rounds
        self.stop = stop
        self.token = ""
        self.refresh_token = ""
        self.offers = offers if offers else []
        self.tumbler_options = tumbler_options if tumbler_options else None
        self.coin_history = {}
        self.seedphrase = ""

    @classmethod
    def from_wallet(cls, name: str, port: int, wallet: dict):
        type_ = wallet.get("type", "maker")
        tumbler_options = wallet.get("tumbler_options", {})

        # Select the appropriate subclass based on wallet config.
        if type_ == "maker":
            from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import MakerClient
            client_cls = MakerClient
        elif type_ == "taker":
            # Distinguish between a standard taker and a tumbler taker based on tumbler_options.
            if tumbler_options:
                from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import TumblerTakerClient
                client_cls = TumblerTakerClient
            else:
                from manager.wasabi_clients.joinmarket_clients.joinmarket_clients import TakerClient
                client_cls = TakerClient
        else:
            client_cls = cls

        # Instantiate the client using the selected subclass.
        client = client_cls(
            name=name,
            port=port,
            type=type_,
            delay=(wallet.get("delay_blocks", 0), wallet.get("delay_rounds", 0)),
            stop=(wallet.get("stop_blocks", 0), wallet.get("stop_rounds", 0)),
            offers=wallet.get("offers", []),
            tumbler_options=tumbler_options,
            time_between_rounds=wallet.get("time_between_rounds", 0),
        )

        start = time()
        if not client.wait_wallet(timeout=60):
            print(
                f"- could not start {name} (application timeout {time() - start} seconds)"
            )
            return None

        print(f"- started {client.name} (wait took {time() - start} seconds)")
        return client

    def update_status(self) -> dict:
        self.update_coin_history()
        return self.session()


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

    def is_paused(self, current_block):
        # “delay[0]” means “don’t run until current_block >= delay[0]”
        return current_block < self.next_coinjoin_allowed



    def session(self):
        method = "GET"
        endpoint = "/session"
        response = self._rpc(method, endpoint)
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
        self.seedphrase = response.get("seedphrase", "")
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

            sleep(1)
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
        maxsize
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
            "minsize": str(minsize),
            "maxsize": str(maxsize)
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

    def run_schedule(self):
        """
        Create and run a schedule of transactions.
        - destination_addresses: list of str, addresses to send funds to
        - tumbler_options: optional, dict, additional tumbler configuration options
        """
        if not self.tumbler_options:
            raise Exception("No tumbler options provided")
        address_count = self.tumbler_options.get("address_count", 3)
        destination_addresses = [self.get_new_address() for _ in range(address_count)]

        method = "POST"
        endpoint = f"/wallet/{self.walletname}/taker/schedule"
        json_data = {
            "destination_addresses": destination_addresses,
            "tumbler_options": self.tumbler_options
        }

        start = time()
        while time() - start < 60:  # Using a longer timeout for the more complex tumbler operation
            try:
                response = self._rpc(method, endpoint, json_data=json_data)
                return response
            except Exception as e:
                if time() - start >= 60:
                    print("Failed to run schedule, attempt timed out.")
                sleep(1)  # Add a small delay between retries

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

    def list_transactions_maker(self):
        """List all transactions in the wallet."""
        method = "GET"
        endpoint = f"/wallet/yieldgen/report"
        response = self._rpc(method, endpoint)
        return response

    def list_unspent_coins(self):
        """List all unspent coins in the wallet."""
        try:
            response = self.list_utxos()
            coins = response.get("utxos", [])
        except Exception as e:
            print("Error fetching UTXOs:", e)
            return
        return self.transform_coins_to_wasabi(coins)


    def list_coins(self):
        """List all coins in the wallet."""
        return self.transform_coins_to_wasabi(
            list(self.coin_history.values()))

    def list_keys(self):
        """List all keys in the wallet."""
        seed_bytes = Bip39SeedGenerator(self.seedphrase).Generate()
        coins = self.list_coins()
        keys = []
        for coin in coins:
            key = {"full_key_path": coin.get("keyPath", "")}
            bip32_ctx = Bip32Slip10Secp256k1.FromSeedAndPath(seed_bytes, key["full_key_path"])
            key["pubKey"] = bip32_ctx.PublicKey().RawUncompressed().ToHex()
            key["internal"] = key["full_key_path"].split("/")[-2] == "1"
            key["address"] = coin.get("address", "")
            keys.append(key)

        return keys

    def get_offer(self, round=0):
        return self.offers[round % len(self.offers)]


    def update_coin_history(self):
        """
        Poll the current unspent coins (UTXOs) from the API and update the internal
        coin history. Expects the API to return a dict with a key "utxos" that is a list
        of coin dicts.
        """
        try:
            response = self.list_utxos()
            # Extract the list of coins from the JSON structure.
            coins = response.get("utxos", [])
        except Exception as e:
            print("Error fetching UTXOs:", e)
            return

        for coin in coins:
            key = coin.get("utxo")
            if key:
                # setdefault ensures we record a coin only once
                self.coin_history.setdefault(key, coin)


    def transform_coins_to_wasabi(self, joinmarket_coins: List):
        """
        Transform joinmarket's UTXO output to the Wasabi Wallet format.

        Expected joinmarket coin format (example):
        {
            "address": "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78",
            "path": "m/84'/1'/0'/0/0",
            "label": "",
            "value": 200000,
            "tries": 0,
            "tries_remaining": 3,
            "external": False,
            "mixdepth": 0,
            "confirmations": 1,
            "frozen": False,
            "utxo": "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5:1"
        }

        Desired Wasabi format (example):
        {
            "txid": "2585ed322655adfc4645f28196b77ad7d56ab1d389eb00a044719d42995ad4c5",
            "index": 1,
            "amount": 200000,
            "anonymityScore": 1,
            "confirmed": true,
            "confirmations": 1,
            "keyPath": "84'/1'/0'/0/0",
            "address": "bcrt1q0ldnp64tctudcfjuy89radpzecplauy7dvdf78"
        }
        """
        wasabi_coins = []
        for coin in joinmarket_coins:
            utxo_str = coin.get("utxo", "")
            if not utxo_str:
                continue
            try:
                txid, index_str = utxo_str.split(":")
                index = int(index_str)
            except Exception as e:
                print(f"Could not parse utxo '{utxo_str}': {e}")
                continue

            key_path = coin.get("path", "")
            if key_path.startswith("m/"):
                key_path = key_path[2:]

            wasabi_coin = {
                "txid": txid,
                "index": index,
                "amount": coin.get("value"),
                "confirmed": coin.get("confirmations", 0) > 0,
                "confirmations": coin.get("confirmations", 0),
                "keyPath": key_path,
                "address": coin.get("address"),
            }
            if "spentBy" in coin:
                wasabi_coin["spentBy"] = coin["spentBy"]

            wasabi_coins.append(wasabi_coin)
        return wasabi_coins
