from manager.btc_node import BtcNode
from manager import utils
from manager.engine.configuration import ScenarioConfig, WalletConfig, FundConfig
from time import sleep
import random
import os
import json
import multiprocessing
import multiprocessing.pool
import math
import shutil
import datetime

DISTRIBUTOR_UTXOS = 10
BATCH_SIZE = 20
BTC = 100_000_000


class EngineBase:
    def __init__(self, args, driver, log_src_path):
        self.args = args
        self.driver = driver
        self.log_src_path = log_src_path
        self.scenario: ScenarioConfig = self.default_scenario()
        self.versions = set()
        self.node: BtcNode | None = None
        self.distributor = None
        self.clients = []
        self.invoices = {}
        self.current_block = 0
        self.current_round = 0

    def default_scenario(self) -> ScenarioConfig:
        raise NotImplementedError

    def load_scenario(self):
        if self.args.command == "run" and self.args.scenario:
            self.scenario = ScenarioConfig.from_json_config(self.args.scenario)

        self.versions.add(self.scenario.default_version)
        if self.scenario.distributor_version is not None:
            self.versions.add(self.scenario.distributor_version)
        for wallet in self.scenario.wallets:
            if wallet.version is not None:
                self.versions.add(wallet.version)

    def prepare_images(self):
        raise NotImplementedError

    def prepare_image(self, name: str, path=None):
        prefixed_name = self.args.image_prefix + name
        if self.driver.has_image(prefixed_name):
            if self.args.force_rebuild:
                if self.args.image_prefix:
                    self.driver.pull(prefixed_name)
                    print(f"- image pulled {prefixed_name}")
                else:
                    self.driver.build(name, f"./containers/{name}" if path is None else path)
                    print(f"- image rebuilt {prefixed_name}")
            else:
                print(f"- image reused {prefixed_name}")
        elif self.args.image_prefix:
            self.driver.pull(prefixed_name)
            print(f"- image pulled {prefixed_name}")
        else:
            self.driver.build(name, f"./containers/{name}" if path is None else path)
            print(f"- image built {prefixed_name}")

    def start_infrastructure(self):
        print("Starting infrastructure")
        self.start_btc_node()
        self.start_engine_infrastructure()
        self.start_distributor()

    def start_btc_node(self):
        btc_node_ip, btc_node_ports = self.driver.run(
            "btc-node",
            f"{self.args.image_prefix}btc-node",
            ports={18443: 18443, 18444: 18444},
            cpu=4.0,
            memory=8192,
        )

        self.node = BtcNode(
            host=btc_node_ip if self.args.proxy else self.args.control_ip,
            port=18443 if self.args.proxy else btc_node_ports[18443],
            internal_ip=btc_node_ip,
            proxy=self.args.proxy,
        )
        self.node.wait_ready()
        print("- started btc-node")

    def start_engine_infrastructure(self):
        raise NotImplementedError

    def start_distributor(self):
        raise NotImplementedError

    def init_client(self):
        raise NotImplementedError

    def start_client(self, idx: int, wallet=None):
        raise NotImplementedError

    def stop_client(self, idx: int):
        raise NotImplementedError

    def start_clients(self, wallets):
        print("Starting clients")
        with multiprocessing.pool.ThreadPool() as pool:
            new_clients = pool.starmap(self.start_client, enumerate(wallets, start=len(self.clients)))

            for _ in range(3):
                restart_idx = list(
                    map(
                        lambda x: x[0],
                        filter(
                            lambda x: x[1] is None,
                            enumerate(new_clients, start=len(self.clients)),
                        ),
                    )
                )

                if not restart_idx:
                    break
                print(f"- failed to start {len(restart_idx)} clients; retrying ...")
                for idx in restart_idx:
                    self.stop_client(idx)
                sleep(60)
                restarted_clients = pool.starmap(
                    self.start_client,
                    ((idx, wallets[idx - len(self.clients)]) for idx in restart_idx),
                )
                for idx, client in enumerate(restarted_clients):
                    if client is not None:
                        new_clients[restart_idx[idx]] = client
            else:
                new_clients = list(filter(lambda x: x is not None, new_clients))
                print(f"- failed to start {len(wallets) - len(new_clients)} clients; continuing ...")
        self.clients.extend(new_clients)

    def fund_distributor(self, btc_amount):
        print("Funding distributor")
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.distributor is None:
            raise RuntimeError("Distributor is not initialized")

        for _ in range(DISTRIBUTOR_UTXOS):
            self.node.fund_address(
                self.distributor.get_new_address(),
                math.ceil(btc_amount * BTC / DISTRIBUTOR_UTXOS) // BTC,
            )

        while (balance := self.distributor.get_balance()) < btc_amount * BTC:
            sleep(1)
        print(f"- funded (current balance {balance / BTC:.8f} BTC)")

    def store_client_logs(self, client, data_path):
        sleep(random.random() * 3)
        client_path = os.path.join(data_path, client.name)
        os.mkdir(client_path)
        for label, filename, getter in (
            ("coins", "coins.json", client.list_coins),
            ("unspent coins", "unspent_coins.json", client.list_unspent_coins),
            ("keys", "keys.json", client.list_keys),
            ("history", "history.json", client.get_history),
        ):
            try:
                data = getter()
                with open(os.path.join(client_path, filename), "w") as f:
                    json.dump(data, f, indent=2)
                print(f"- stored {client.name} {label}")
            except Exception as e:
                print(f"- could not store {client.name} {label} ({e})")

        try:
            self.driver.download(client.name, self.log_src_path, client_path)

            print(f"- stored {client.name} logs")
        except:
            print(f"- could not store {client.name} logs")

    def store_logs(self):
        print("Storing logs")
        time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        experiment_path = f"./logs/{time}_{self.scenario.name}"
        data_path = os.path.join(experiment_path, "data")
        os.makedirs(data_path)

        with open(os.path.join(experiment_path, "scenario.json"), "w") as f:
            json.dump(self.scenario.to_dict(), f, indent=2)
            print("- stored scenario")

        stored_blocks = 0
        node_path = os.path.join(data_path, "btc-node")
        os.mkdir(node_path)
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        while stored_blocks < self.node.get_block_count():  # type: ignore
            block_hash = self.node.get_block_hash(stored_blocks)
            block = self.node.get_block_info(block_hash)
            with open(os.path.join(node_path, f"block_{stored_blocks}.json"), "w") as f:
                json.dump(block, f, indent=2)
            stored_blocks += 1
        print(f"- stored {stored_blocks} blocks")

        self.store_engine_logs(data_path)

        # TODO parallelize (driver cannot be simply passed to new threads)
        for client in self.clients:
            self.store_client_logs(client, data_path)

        shutil.make_archive(experiment_path, "zip", *os.path.split(experiment_path))
        print("- zip archive created")

    def store_engine_logs(self, data_path):
        raise NotImplementedError

    def stop_coinjoins(self):
        print("Stopping coinjoins")
        for client in self.clients:
            try:
                client.stop_coinjoin()
                print(f"- stopped mixing {client.name}")
            except Exception as e:
                print(f"- could not stop mixing {client.name} ({e})")

    def update_invoice_payments(self):
        due = list(filter(lambda x: x[0] <= self.current_block and x[1] <= self.current_round, self.invoices.keys()))
        for i in due:
            self.pay_invoices(self.invoices.pop(i, []))

    def prepare_invoices(self, wallets: list[WalletConfig]):
        print("Preparing invoices")
        client_invoices = [(client, wallet.funds) for client, wallet in zip(self.clients, wallets)]

        for client, funds in client_invoices:
            for fund in funds:
                block = 0
                round = 0
                if isinstance(fund, int):
                    value = fund
                elif isinstance(fund, FundConfig):
                    value = fund.value
                    block = fund.delay_blocks or 0
                    round = fund.delay_rounds or 0
                addressed_invoice = (client.get_new_address(), value)
                if (block, round) not in self.invoices:
                    self.invoices[(block, round)] = [addressed_invoice]
                else:
                    self.invoices[(block, round)].append(addressed_invoice)

        for addressed_invoices in self.invoices.values():
            random.shuffle(addressed_invoices)

        print(f"- prepared {sum(map(len, self.invoices.values()))} invoices")

    def pay_invoices(self, addressed_invoices):
        print(
            f"- paying {len(addressed_invoices)} invoices (batch size {BATCH_SIZE}, block {self.current_block}, round {self.current_round})"
        )
        try:
            for batch in utils.batched(addressed_invoices, BATCH_SIZE):
                for _ in range(3):
                    try:
                        if self.distributor is None:
                            raise RuntimeError("Distributor is not initialized")
                        result = self.distributor.send(batch)
                        if str(result) == "timeout":
                            print("- transaction timeout")
                            continue
                        break
                    except Exception as e:
                        # https://github.com/zkSNACKs/WalletWasabi/issues/12764
                        if "Bad Request" in str(e):
                            print("- transaction error (bad request)")
                        else:
                            print(f"- transaction error ({e})")
                else:
                    print("- invoice payment failed")
                    raise Exception("Invoice payment failed")

        except Exception as e:
            print("- invoice payment failed")
            pass
            sleep(360)

    def run(self):
        print(f"=== Scenario {self.scenario.name} ===")
        self.prepare_images()
        self.start_infrastructure()
        self.fund_distributor(500)
        self.start_clients(self.scenario.wallets)
        self.prepare_invoices(self.scenario.wallets)
        print("Running simulation")
        self.run_engine()

    def run_engine(self):
        raise NotImplementedError
