import os
from traceback import print_exception

from manager.engine.engine_base import EngineBase
from manager.engine.configuration import ScenarioConfig, WalletConfig, WasabiConfig
from manager.wasabi_backend_protocol import WasabiBackendProtocol
from manager.wasabi_coordinator_protocol import WasabiCoordinatorProtocol
from manager.wasabi_backend_factory import (
    detect_backend_architecture,
    create_backend,
    create_coordinator,
    get_backend_version,
    get_backend_image_names,
    BackendArchitecture,
)
from manager.wasabi_clients import WasabiClient
from time import sleep, time
import sys
import random
import json
import tempfile
import multiprocessing
import multiprocessing.pool


class WasabiEngine(EngineBase):
    def __init__(self, args, driver):
        self.coordinator: WasabiCoordinatorProtocol | None = None
        self.backend: WasabiBackendProtocol | None = None
        self.backend_architecture: BackendArchitecture | None = None
        self.round_ids: set[str] = set()
        super().__init__(args, driver, "/home/wasabi/.walletwasabi/client/")

    def default_scenario(self) -> ScenarioConfig:
        return ScenarioConfig(
            name="default",
            rounds=10,  # the number of coinjoins after which the simulation stops (0 for no limit)
            blocks=0,  # the number of mined blocks after which the simulation stops (0 for no limit)
            default_version="2.6.0",
            wallets=[
                WalletConfig(funds=[200000, 50000], wasabi=WasabiConfig(anon_score_target=7)),
                WalletConfig(funds=[3000000], wasabi=WasabiConfig(redcoin_isolation=True)),
                WalletConfig(funds=[1000000, 500000], wasabi=WasabiConfig(skip_rounds=[0, 1, 2])),
                WalletConfig(funds=[3000000, 15000]),
                WalletConfig(funds=[1000000, 500000]),
                WalletConfig(funds=[3000000, 600000]),
            ],
        )

    def determine_backend_architecture(self) -> BackendArchitecture:
        """Determine which backend architecture to use based on scenario versions."""
        return detect_backend_architecture(self.versions)

    def prepare_images(self):
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_client_images()

        self.backend_architecture = self.determine_backend_architecture()
        for image_name in get_backend_image_names(self.backend_architecture):
            base, version = image_name.split(":")
            path = f"./containers/{base}/{version}"
            self.prepare_image(image_name, path)

    def prepare_client_images(self):
        for version in self.versions:
            name = f"wasabi-client:{version}"
            path = f"./containers/wasabi-clients/{version}"
            self.prepare_image(name, path)

    def start_engine_infrastructure(self):
        if self.backend_architecture is None:
            self.backend_architecture = self.determine_backend_architecture()

        self.start_wasabi_backend()

        if self.backend_architecture == BackendArchitecture.SPLIT:
            self.start_wasabi_coordinator()

    def start_wasabi_backend(self):
        """Start the Wasabi backend with the appropriate version."""
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.backend_architecture is None:
            self.backend_architecture = self.determine_backend_architecture()

        version = get_backend_version(self.backend_architecture)

        wasabi_backend_ip, wasabi_backend_ports = self.driver.run(
            "wasabi-backend",
            f"{self.args.image_prefix}wasabi-backend:{version}",
            ports={37127: 37127},
            env={
                "WASABI_BIND": "http://0.0.0.0:37127",
                "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
            },
            cpu=8.0,
            memory=8192,
        )
        sleep(1)

        config_path = f"./containers/wasabi-backend/{version}/WabiSabiConfig.json"
        with open(config_path, "r") as config_file:
            backend_config = json.load(config_file)
        backend_config.update(self.scenario.backend or {})

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            scenario_file = tmp_file.name
            tmp_file.write(json.dumps(backend_config, indent=2).encode())

        try:
            self.driver.upload(
                "wasabi-backend",
                scenario_file,
                "/home/wasabi/.walletwasabi/backend/WabiSabiConfig.json",
            )
        except Exception as e:
            print_exception(e)
            raise

        self.backend = create_backend(
            self.backend_architecture,
            host=wasabi_backend_ip if self.args.proxy else self.args.control_ip,
            port=37127 if self.args.proxy else wasabi_backend_ports[37127],
            internal_ip=wasabi_backend_ip,
            proxy=self.args.proxy,
        )
        self.backend.wait_ready()
        print(f"- started wasabi-backend ({self.backend_architecture.value} architecture)")

    def start_wasabi_coordinator(self):
        """Start the Wasabi coordinator (only for split architecture)."""
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.backend_architecture is None:
            self.backend_architecture = self.determine_backend_architecture()
        version = get_backend_version(self.backend_architecture)
        wasabi_coordinator_ip, wasabi_coordinator_ports = self.driver.run(
            "wasabi-coordinator",
            f"{self.args.image_prefix}wasabi-coordinator:{version}",
            ports={37128: 37128},
            env={
                "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
                "WASABI_BIND": "http://0.0.0.0:37128",
            },
            cpu=4.0,
            memory=4096,
        )
        sleep(1)

        # v2.6.0 coordinator reads its WabiSabi settings from Config.json (not WabiSabiConfig.json).
        # Source template is Config.json; still substitute ADDR_BTC_NODE so the RPC endpoint is valid.
        config_path = f"./containers/wasabi-coordinator/{version}/Config.json"
        with open(config_path, "r") as config_file:
            raw = config_file.read()
        raw = raw.replace(
            "${ADDR_BTC_NODE}",
            self.args.btc_node_ip or self.node.internal_ip or "btc-node",
        )
        coordinator_config = json.loads(raw)
        coordinator_config.update(self.scenario.backend or {})

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            scenario_file = tmp_file.name
            tmp_file.write(json.dumps(coordinator_config, indent=2).encode())

        try:
            self.driver.upload(
                "wasabi-coordinator",
                scenario_file,
                "/home/wasabi/.walletwasabi/coordinator/Config.json",
            )
        except Exception as e:
            print_exception(e)
            raise

        self.coordinator = create_coordinator(
            host=wasabi_coordinator_ip if self.args.proxy else self.args.control_ip,
            port=37128 if self.args.proxy else wasabi_coordinator_ports[37128],
            internal_ip=wasabi_coordinator_ip,
            proxy=self.args.proxy,
        )
        self.coordinator.wait_ready()
        print("- started wasabi-coordinator")

    def start_distributor(self):
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.backend is None:
            raise RuntimeError("Wasabi backend is not initialized")

        backend_address = self.backend.internal_ip

        distributor_version = self.scenario.distributor_version or self.scenario.default_version
        wasabi_client_distributor_ip, wasabi_client_distributor_ports = self.driver.run(
            "wasabi-client-distributor",
            f"{self.args.image_prefix}wasabi-client:{distributor_version}",
            env={
                "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
                "ADDR_WASABI_BACKEND": self.args.wasabi_backend_ip or backend_address,
            },
            ports={37128: 37131},
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
        if not self.distributor.wait_wallet(timeout=360):
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

    def start_client(self, idx: int, wallet: WalletConfig | None = None):
        if wallet is None:
            raise ValueError("wallet parameter is required")
        version = wallet.version or self.scenario.default_version

        wasabi_config = wallet.wasabi
        anon_score_target = (
            wasabi_config.anon_score_target if wasabi_config else self.scenario.default_anon_score_target
        )
        redcoin_isolation = (
            wasabi_config.redcoin_isolation if wasabi_config else self.scenario.default_redcoin_isolation
        )

        if anon_score_target is not None and version < "2.0.3":
            anon_score_target = None
            print(
                f"Anon Score Target is ignored for wallet {idx} as it is curently supported only for version 2.0.3 and newer"
            )

        if redcoin_isolation is not None and version < "2.0.3":
            redcoin_isolation = None
            print(
                f"Redcoin isolation is ignored for wallet {idx} as it is curently supported only for version 2.0.3 and newer"
            )

        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        if self.backend is None:
            raise RuntimeError("Wasabi backend is not initialized")

        backend_address = self.backend.internal_ip

        sleep(random.random() * 3)
        name = f"wasabi-client-{idx:03}"
        client_env = {
            "ADDR_BTC_NODE": self.args.btc_node_ip or self.node.internal_ip,
            "ADDR_WASABI_BACKEND": self.args.wasabi_backend_ip or backend_address,
            "WASABI_ANON_SCORE_TARGET": (str(anon_score_target) if anon_score_target else None),
            "WASABI_REDCOIN_ISOLATION": (str(redcoin_isolation) if redcoin_isolation else None),
        }

        if self.backend_architecture == BackendArchitecture.SPLIT and self.coordinator is not None:
            client_env["ADDR_WASABI_COORDINATOR"] = self.coordinator.internal_ip

        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}wasabi-client:{version}",
                env=client_env,
                ports={37128: 37132 + idx},
                cpu=(0.3 if version < "2.0.4" else 0.1),
                memory=(1024 if version < "2.0.4" else 768),
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            return None

        delay = (wallet.delay_blocks or 0, wallet.delay_rounds or 0)
        stop = (wallet.stop_blocks or 0, wallet.stop_rounds or 0)
        client = self.init_wasabi_client(
            version,
            ip if self.args.proxy else self.args.control_ip,
            37128 if self.args.proxy else manager_ports[37128],
            f"wasabi-client-{idx:03}",
            delay,
            stop,
        )

        start = time()
        if not client.wait_wallet(timeout=120):
            print(f"- could not start {name} (application timeout {time() - start} seconds)")
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

        if self.backend_architecture == BackendArchitecture.SPLIT:
            try:
                self.driver.download(
                    "wasabi-coordinator",
                    "/home/wasabi/.walletwasabi/coordinator/",
                    os.path.join(data_path, "wasabi-coordinator"),
                )
                print(f"- stored coordinator logs")
            except:
                print(f"- could not store coordinator logs")

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
            if self.current_block < client.delay[0]:
                return False
            if self.current_round < client.delay[1]:
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
        if self.node is None:
            raise RuntimeError("Bitcoin node is not initialized")
        initial_block = self.node.get_block_count()
        while (self.scenario.rounds == 0 or self.current_round <= self.scenario.rounds) and (
            self.scenario.blocks == 0 or self.current_block < self.scenario.blocks
        ):
            for _ in range(3):
                try:
                    self.current_round = self._get_current_round()
                    break
                except Exception as e:
                    print(f"- could not get rounds".ljust(60), end="\r")
                    print(f"Round exception: {e}", file=sys.stderr)

            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block  # type: ignore
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

    def _get_current_round(self) -> int:
        if self.backend_architecture == BackendArchitecture.SPLIT and self.coordinator is not None:
            resp = self.coordinator._get_status()
            if resp is None:
                raise RuntimeError("Could not get coordinator status")
            for round_state in resp["RoundStates"]:
                if round_state["Phase"] == "TransactionSigning":
                    self.round_ids.add(round_state["RoundId"])
            return len(self.round_ids)

        else:
            # In legacy versions, rounds are tracked by the backend
            return sum(
                1
                for _ in self.driver.peek(
                    "wasabi-backend",
                    "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt",
                ).split("\n")[:-1]
            )

