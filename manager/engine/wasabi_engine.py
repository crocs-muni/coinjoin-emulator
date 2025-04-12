import os

from manager.engine.engine_base import EngineBase
from manager.wasabi_backend import WasabiBackend
from manager.wasabi_clients import WasabiClient
from time import sleep, time
import sys
import random
import json
import tempfile
import multiprocessing
import multiprocessing.pool

SCENARIO = {
    "name": "default",
    "rounds": 10,  # the number of coinjoins after which the simulation stops (0 for no limit)
    "blocks": 0,  # the number of mined blocks after which the simulation stops (0 for no limit)
    "default_version": "2.0.4",
    "wallets": [
        {"funds": [200000, 50000], "anon_score_target": 7},
        {"funds": [3000000], "redcoin_isolation": True},
        {"funds": [1000000, 500000], "skip_rounds": [0, 1, 2]},
        {"funds": [3000000, 15000]},
        {"funds": [1000000, 500000]},
        {"funds": [3000000, 600000]},
    ],
}

class WasabiEngine(EngineBase):
    def __init__(self, args, driver):
        self.coordinator = None
        super().__init__(args, driver, "/home/wasabi/.walletwasabi/backend/")

    def default_scenario(self):
        return SCENARIO

    def prepare_images(self):
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_client_images()
        self.prepare_image("wasabi-backend")

    def prepare_client_images(self):
        for version in self.versions:
            major_version = version[0]
            name = f"wasabi-client:{version}"
            path = f"./containers/wasabi-clients/v{major_version}/{version}"
            self.prepare_image(name, path) 


    def start_engine_infrastructure(self):
        self.start_wasabi_backend()


    def start_wasabi_backend(self):
        wasabi_backend_ip, wasabi_backend_ports = self.driver.run(
            "wasabi-backend",
            f"{self.args.image_prefix}wasabi-backend",
            ports={37127: 37127},
            env={
                "WASABI_BIND": "http://0.0.0.0:37127",
                "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
            },
            cpu=8.0,
            memory=8192,
        )
        sleep(1)
        with open("./containers/wasabi-backend/WabiSabiConfig.json", "r") as config_file:
            backend_config = json.load(config_file)
        backend_config.update(SCENARIO.get("backend", {}))

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            scenario_file = tmp_file.name
            tmp_file.write(json.dumps(backend_config, indent=2).encode())

        self.driver.upload(
            "wasabi-backend",
            scenario_file,
            "/home/wasabi/.walletwasabi/backend/WabiSabiConfig.json",
        )

        self.coordinator = WasabiBackend(
            host=wasabi_backend_ip if self.args.proxy else self.args.control_ip,
            port=37127 if self.args.proxy else wasabi_backend_ports[37127],
            internal_ip=wasabi_backend_ip,
            proxy=self.args.proxy,
        )
        self.coordinator.wait_ready()
        print("- started wasabi-backend")


    def start_distributor(self):
        distributor_version = self.scenario.get(
            "distributor_version", self.scenario["default_version"]
        )
        wasabi_client_distributor_ip, wasabi_client_distributor_ports = self.driver.run(
            "wasabi-client-distributor",
            f"{self.args.image_prefix}wasabi-client:{distributor_version}",
            env={
                "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
                "ADDR_WASABI_BACKEND": self.args.wasabi_backend_ip or self.coordinator.internal_ip,
            },
            ports={37128: 37128},
            cpu=1.0,
            memory=2048,
        )

        self.distributor = self.init_wasabi_client(
            distributor_version,
            wasabi_client_distributor_ip if self.args.proxy else self.args.control_ip,
            port=37128 if self.args.proxy else wasabi_client_distributor_ports[37128],
            name="wasabi-client-distributor",
            delay=(0, 0),
            stop=(0, 0),
        )
        if not self.distributor.wait_wallet(timeout=60):
            print(f"- could not start distributor (application timeout)")
            raise Exception("Could not start distributor")
        print("- started distributor")

    def init_wasabi_client(self, version, ip, port, name, delay, stop):
        return WasabiClient(version)(
            host=ip,
            port=port,
            name=name,
            proxy=self.args.proxy,
            version=version,
            delay=delay,
            stop=stop,
        )

    def start_client(self, idx, wallet):
        version = wallet.get("version", self.scenario["default_version"])

        if "anon_score_target" in wallet:
            anon_score_target = wallet["anon_score_target"]
        else:
            anon_score_target = self.scenario.get("default_anon_score_target", None)

        if anon_score_target is not None and version < "2.0.3":
            anon_score_target = None
            print(
                f"Anon Score Target is ignored for wallet {idx} as it is curently supported only for version 2.0.3 and newer"
            )

        if "redcoin_isolation" in wallet:
            redcoin_isolation = wallet["redcoin_isolation"]
        else:
            redcoin_isolation = self.scenario.get("default_redcoin_isolation", None)

        if redcoin_isolation is not None and version < "2.0.3":
            redcoin_isolation = None
            print(
                f"Redcoin isolation is ignored for wallet {idx} as it is curently supported only for version 2.0.3 and newer"
            )

        sleep(random.random() * 3)
        name = f"wasabi-client-{idx:03}"
        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}wasabi-client:{version}",
                env={
                    "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
                    "ADDR_WASABI_BACKEND": self.args.wasabi_backend_ip
                                           or self.coordinator.internal_ip,
                    "WASABI_ANON_SCORE_TARGET": (
                        str(anon_score_target) if anon_score_target else None
                    ),
                    "WASABI_REDCOIN_ISOLATION": (
                        str(redcoin_isolation) if redcoin_isolation else None
                    ),
                },
                ports={37128: 37129 + idx},
                cpu=(0.3 if version < "2.0.4" else 0.1),
                memory=(1024 if version < "2.0.4" else 768),
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            return None

        delay = (wallet.get("delay_blocks", 0), wallet.get("delay_rounds", 0))
        stop = (wallet.get("stop_blocks", 0), wallet.get("stop_rounds", 0))
        client = self.init_wasabi_client(
            version,
            ip if self.args.proxy else self.args.control_ip,
            37128 if self.args.proxy else manager_ports[37128],
            f"wasabi-client-{idx:03}",
            delay,
            stop,
        )

        start = time()
        if not client.wait_wallet(timeout=60):
            print(
                f"- could not start {name} (application timeout {time() - start} seconds)"
            )
            return None
        print(f"- started {client.name} (wait took {time() - start} seconds)")
        return client

    def stop_client(self, idx: int):
        self.driver.stop(f"wasabi-client-{idx:03}")

    def store_engine_logs(self, data_path):
        try:
            self.driver.download(
                "wasabi-backend",
                "/home/wasabi/.walletwasabi/backend/",
                os.path.join(data_path, "wasabi-backend"),
            )

            print(f"- stored backend logs")
        except:
            print(f"- could not store backend logs")

    def start_coinjoin(self, client):
        sleep(random.random() / 10)
        client.start_coinjoin()

    def stop_coinjoin(self, client):
        sleep(random.random() / 10)
        client.stop_coinjoin()

    def update_coinjoins(self):
        def start_condition(client):
            if client.stop[0] > 0 and self.current_block >= client.stop[0]:
                return False
            if client.stop[1] > 0 and self.current_round >= client.stop[1]:
                return False
            if self.current_block < client.next_coinjoin_allowed[0]:
                return False
            if self.current_round < client.next_coinjoin_allowed[1]:
                return False
            return True

        start, stop = [], []
        for client in self.clients:
            if start_condition(client):
                start.append(client)
            else:
                stop.append(client)

        with multiprocessing.pool.ThreadPool() as pool:
            pool.starmap(self.start_coinjoin, ((client,) for client in start))

        with multiprocessing.pool.ThreadPool() as pool:
            pool.starmap(self.stop_coinjoin, ((client,) for client in stop))

    def run_engine(self):
        print("Running simulation")
        initial_block = self.node.get_block_count()
        while (self.scenario["rounds"] == 0 or self.current_round < self.scenario["rounds"]) and (
                self.scenario["blocks"] == 0 or self.current_block < self.scenario["blocks"]
        ):
            for _ in range(3):
                try:
                    self.current_round = sum(
                        1
                        for _ in self.driver.peek(
                            "wasabi-backend",
                            "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt",
                        ).split("\n")[:-1]
                    )
                    break
                except Exception as e:
                    print(f"- could not get rounds".ljust(60), end="\r")
                    print(f"Round exception: {e}", file=sys.stderr)

            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block
                    break
                except Exception as e:
                    print(f"- could not get blocks".ljust(60), end="\r")
                    print(f"Block exception: {e}", file=sys.stderr)

            self.update_invoice_payments()
            self.update_coinjoins()
            print(
                f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                end="\r",
            )
            sleep(1)
        print()
        print(f"- limit reached")
