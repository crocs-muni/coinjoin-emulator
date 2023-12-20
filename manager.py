from manager.btc_node import BtcNode
from manager.wasabi_client import WasabiClient
from manager.wasabi_backend import WasabiBackend
from time import sleep, time
import os
import datetime
import json
import argparse
from io import BytesIO
import shutil
import tempfile


BTC = 100_000_000
SCENARIO = {
    "name": "default",
    "rounds": 10,
    "wallets": [
        {"funds": [200000, 50000]},
        {"funds": [3000000]},
        {"funds": [1000000, 500000]},
        {"funds": [1000000, 500000]},
        {"funds": [1000000, 500000]},
        {"funds": [3000000, 15000]},
        {"funds": [1000000, 500000]},
        {"funds": [1000000, 500000]},
        {"funds": [3000000, 600000]},
        {"funds": [1000000, 500000]},
    ],
}

args = None
driver = None
node = None
coordinator = None
distributor = None
clients = []


def build_images():
    print("Building Docker images")
    driver.build("btc-node", "./btc-node")
    print("- btc-node image built")
    driver.build("wasabi-backend", "./wasabi-backend")
    print("- wasabi-backend image built")
    driver.build("wasabi-client", "./wasabi-client")
    print("- wasabi-client image built")


def start_infrastructure():
    print("Starting infrastructure")
    driver.run("btc-node", "btc-node", ports={"18443": "18443", "18444": "18444"})
    global node
    node = BtcNode("btc-node")
    node.wait_ready()
    print("- started btc-node")

    driver.run(
        "wasabi-backend",
        "wasabi-backend",
        ports={"37127": "37127"},
        env={
            "WASABI_BIND": "http://0.0.0.0:37127",
            "ADDR_BTC_NODE": args.addr_btc_node,
        },
    )
    with open("./wasabi-backend/WabiSabiConfig.json", "r") as config_file:
        backend_config = json.load(config_file)
    backend_config.update(SCENARIO.get("backend", {}))

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        scenario_file = tmp_file.name
        tmp_file.write(json.dumps(backend_config, indent=2).encode())

    driver.upload(
        "wasabi-backend",
        scenario_file,
        "/home/wasabi/.walletwasabi/backend/WabiSabiConfig.json",
    )

    global coordinator
    coordinator = WasabiBackend("wasabi-backend", 37127)
    coordinator.wait_ready()
    print("- started wasabi-backend")

    driver.run(
        "wasabi-client-distributor",
        "wasabi-client",
        env={
            "ADDR_BTC_NODE": args.addr_btc_node,
            "ADDR_WASABI_BACKEND": args.addr_wasabi_backend,
        },
        ports={"37128": "37128"},
    )
    global distributor
    distributor = WasabiClient("wasabi-client-distributor", 37128)
    distributor.wait_wallet()
    print("- started distributor")


def fund_distributor(btc_amount):
    print("Funding distributor")
    node.fund_address(distributor.get_new_address(), btc_amount)
    while (balance := distributor.get_balance()) < btc_amount * BTC:
        sleep(0.1)
    print(f"- funded (current balance {balance / BTC:.8f} BTC)")


def start_clients(wallets):
    print("Starting clients")
    new_idxs = []
    for wallet in wallets:
        idx = len(clients)
        driver.run(
            f"wasabi-client-{idx:03}",
            "wasabi-client",
            env={
                "ADDR_BTC_NODE": args.addr_btc_node,
                "ADDR_WASABI_BACKEND": args.addr_wasabi_backend,
            },
            ports={"37128": 37129 + idx},
        )
        client = WasabiClient(
            f"wasabi-client-{idx:03}", 37129 + idx, wallet.get("delay", 0)
        )
        clients.append(client)
        new_idxs.append(idx)

    for idx in new_idxs:
        client = clients[idx]
        client.wait_wallet()
        print(f"- started {client.name}")
    return new_idxs


def batched(data, batch_size=1):
    length = len(data)
    for ndx in range(0, length, batch_size):
        yield data[ndx : min(ndx + batch_size, length)]


def fund_clients(invoices):
    print("Funding clients")
    addressed_invoices = []
    for batch in batched(invoices, 50):
        for client, values in batch:
            for value in values:
                addressed_invoices.append((client.get_new_address(), value))
        distributor.send(addressed_invoices)
        print("- created wallet-funding transaction")
    for client, values in invoices:
        while client.get_balance() < sum(values):
            sleep(0.1)
    print("- funded")


def start_coinjoins(delay=0):
    for client in clients:
        if client.delay <= delay and not client.active:
            client.start_coinjoin()
            print(f"- started mixing {client.name} (delay {delay})")


def stop_coinjoins():
    print("Stopping coinjoins")
    for client in clients:
        client.stop_coinjoin()
        print(f"- stopped mixing {client.name}")


def store_logs():
    print("Storing logs")
    time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    experiment_path = f"./logs/{time}_{SCENARIO['name']}"
    data_path = os.path.join(experiment_path, "data")
    os.makedirs(data_path)

    with open(os.path.join(experiment_path, "scenario.json"), "w") as f:
        json.dump(SCENARIO, f, indent=2)
        print("- stored scenario")

    stored_blocks = 0
    node_path = os.path.join(data_path, "btc-node")
    os.mkdir(node_path)
    while stored_blocks < node.get_block_count():
        block_hash = node.get_block_hash(stored_blocks)
        block = node.get_block_info(block_hash)
        with open(os.path.join(node_path, f"block_{stored_blocks}.json"), "w") as f:
            json.dump(block, f, indent=2)
        stored_blocks += 1
    print(f"- stored {stored_blocks} blocks")

    try:
        driver.download(
            "wasabi-backend",
            "/home/wasabi/.walletwasabi/backend/",
            os.path.join(data_path, "wasabi_backend"),
        )

        print(f"- stored backend logs")
    except:
        print(f"- could not store backend logs")

    for client in clients:
        client_path = os.path.join(data_path, client.name)
        os.mkdir(client_path)
        with open(os.path.join(client_path, "coins.json"), "w") as f:
            json.dump(client.list_coins(), f, indent=2)
            print(f"- stored {client.name} coins")
        with open(os.path.join(client_path, "unspent_coins.json"), "w") as f:
            json.dump(client.list_unspent_coins(), f, indent=2)
            print(f"- stored {client.name} unspent coins")
        with open(os.path.join(client_path, "keys.json"), "w") as f:
            json.dump(client.list_keys(), f, indent=2)
            print(f"- stored {client.name} keys")
        try:
            driver.download(
                client.name, "/home/wasabi/.walletwasabi/client/", client_path
            )

            print(f"- stored {client.name} logs")
        except:
            print(f"- could not store {client.name} logs")

    shutil.make_archive(experiment_path, "zip", *os.path.split(experiment_path))
    print("- zip archive created")


def stop_clients():
    print("Stopping clients")
    driver.stop_many(map(lambda x: x.name, clients))


def stop_infrastructure():
    print("Stopping infrastructure")
    driver.stop(node.name)
    driver.stop(coordinator.name)
    driver.stop(distributor.name)


def main():
    print(f"Starting scenario {SCENARIO['name']}")
    build_images()
    start_infrastructure()
    fund_distributor(1000)
    start_clients(SCENARIO["wallets"])
    invoices = [
        (client, wallet.get("funds", []))
        for client, wallet in zip(clients, SCENARIO["wallets"])
    ]
    fund_clients(invoices)
    start_coinjoins()

    print("Running")
    rounds = 0
    initial_blocks = node.get_block_count()
    while SCENARIO["rounds"] == 0 or rounds < SCENARIO["rounds"]:
        rounds = sum(
            1
            for _ in driver.peek(
                "wasabi-backend",
                "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt",
            ).split("\n")[:-1]
        )
        start_coinjoins(node.get_block_count() - initial_blocks)
        print(f"- coinjoin rounds: {rounds:<10}", end="\r")
        sleep(1)
    print()
    print(f"Round limit reached")

    stop_coinjoins()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    parser.add_argument(
        "--cleanup-only", action="store_true", help="remove old logs and containers"
    )
    parser.add_argument("--scenario", type=str, help="scenario specification")
    parser.add_argument(
        "--driver", type=str, choices=["docker", "podman"], default="docker"
    )
    parser.add_argument(
        "--addr-btc-node", type=str, help="override btc-node address", default=""
    )
    parser.add_argument(
        "--addr-wasabi-backend",
        type=str,
        help="override wasabi-backend address",
        default="",
    )

    args = parser.parse_args()

    if args.driver == "docker":
        from manager.driver.docker import DockerDriver

        driver = DockerDriver()
    else:
        from manager.driver.podman import PodmanDriver

        driver = PodmanDriver()

    if args.cleanup_only:
        driver.cleanup()
        exit(0)

    if args.scenario:
        with open(args.scenario) as f:
            SCENARIO.update(json.load(f))

    try:
        main()
    except KeyboardInterrupt:
        print()
        print("KeyboardInterrupt received")
    finally:
        store_logs()
        stop_clients()
        stop_infrastructure()
        driver.cleanup()
