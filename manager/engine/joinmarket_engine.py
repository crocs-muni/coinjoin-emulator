from manager.engine.engine_base import EngineBase
from manager.wasabi_clients.joinmarket_clients.joinmarket_client_base import JoinMarketClientServer
from time import sleep, time
SCENARIO = {
    "name": "default",
    "default_version": "joinmarket",
    "rounds": 0,  # the number of coinjoins after which the simulation stops (0 for no limit)
    "blocks": 0,  # the number of mined blocks after which the simulation stops (0 for no limit)
    "wallets": [],
}
import sys



class JoinmarketEngine(EngineBase):

    def __init__(self, args, driver):
        super().__init__(args, driver, "/home/joinmarket")

    def default_scenario(self):
        return SCENARIO

    def prepare_images(self):
        print("Preparing images")
        self.prepare_image("btc-node")
        self.prepare_image("joinmarket-client-server")
        self.prepare_image("irc-server")


    def start_engine_infrastructure(self):
        self.node.create_wallet("jm_wallet")
        print("- created jm_wallet in BitcoinCore")

        self.start_irc_server()
        print("- started irc-server")


    def start_irc_server(self):
        # TODO: When the container fails to start, the exception is not thrown and it is not recognized.
        name = "irc-server"

        try:
            ip, manager_ports = self.driver.run(
                name,
                f"{self.args.image_prefix}irc-server",
                env={},  # Add any necessary environment variables
                ports={6667: 6667},
                cpu=1.0,
                memory=2048,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start IRC server")


    def start_distributor(self):
        name = "joinmarket-distributor"
        port = 28183  # Use a specific port for the distributor
        try:
            ip, manager_ports = self.driver.run(
                name,
                "joinmarket-client-server:latest",
                env={},  # Add any necessary environment variables
                ports={28183: port},
                cpu=1.0,
                memory=2048,
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            raise Exception("Could not start distributor")

        self.distributor = self.init_joinmarket_clientserver(name=name, port=port)

        start = time()
        if not self.distributor.wait_wallet(timeout=15):
            print(f"- could not start {name} (application timeout)")
            raise Exception("Could not start distributor")
        print(f"- started distributor")


    def init_joinmarket_clientserver(self, name, port, host="localhost", type="maker"):
        return JoinMarketClientServer(name=name, port=port, type=type)


    def start_client(self, idx: int, wallet=None):
        name = f"jcs-{idx:03}"
        port = 28184 + idx
        try:
            ip, manager_ports = self.driver.run(
                name,
                "joinmarket-client-server:latest",
                env={},
                ports={28183: port},
                cpu=(0.1),
                memory=(768),
            )
        except Exception as e:
            print(f"- could not start {name} ({e})")
            return None

        print(f"driver starting {name}")

        client = JoinMarketClientServer.from_wallet(name, port, wallet)
        return client

    def stop_client(self, idx: int):
        name = f"jcs-{idx:03}"
        self.driver.stop(name)

    def store_engine_logs(self, data_path):
        # TODO: store irc logs.
        pass


    def update_coinjoins_joinmarket(self):
        for client in self.clients:
            delta = client.update(self.current_block, self.current_round)
            # Apply any change in round count; alternatively, have the client trigger an event.
            self.current_round += delta


    def run_engine(self):
        self.update_invoice_payments()
        initial_block = self.node.get_block_count()
        for i in range(5):
            # Takers need 3 confirmations of transactions for the sourcing commitments
            self.node.mine_block()

        print(f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60))

        while ( self.scenario["rounds"] == 0 or self.current_round < self.scenario["rounds"] ) and (
                self.scenario["blocks"] == 0 or self.current_block < self.scenario["blocks"]):
            for _ in range(3):
                try:
                    self.current_block = self.node.get_block_count() - initial_block
                    break
                except Exception as e:
                    print(f"- could not get blocks".ljust(60), end="\r")
                    print(f"Block exception: {e}", file=sys.stderr)

            self.update_invoice_payments()
            self.update_coinjoins_joinmarket()

            print(
                f"- coinjoin rounds: {self.current_round} (block {self.current_block})".ljust(60),
                end="\r",
            )
            sleep(1)

        print()
        print(f"- limit reached")
        sleep(60)
        self.node.mine_block()
