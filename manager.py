from manager.btc_node import BtcNode
from manager.wasabi_client import WasabiClient
from manager.wasabi_backend import WasabiBackend
from time import sleep
import os
import datetime
import json
import argparse
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


def prepare_image(name):
    prefixed_name = args.image_prefix + name
    if driver.has_image(prefixed_name):
        if args.force_rebuild:
            if args.image_prefix:
                driver.pull(prefixed_name)
                print(f"- image pulled {prefixed_name}")
            else:
                driver.build(name, f"./{name}")
                print(f"- image rebuilt {prefixed_name}")
        else:
            print(f"- image reused {prefixed_name}")
    elif args.image_prefix:
        driver.pull(prefixed_name)
        print(f"- image pulled {prefixed_name}")
    else:
        driver.build(name, f"./{name}")
        print(f"- image built {prefixed_name}")


def prepare_images():
    prepare_image("btc-node")
    prepare_image("wasabi-backend")
    prepare_image("wasabi-client")


def start_infrastructure():
    print("Starting infrastructure")
    btc_node_ip, btc_node_ports = driver.run(
        "btc-node",
        f"{args.image_prefix}btc-node",
        ports={"18443": "18443", "18444": "18444"},
    )
    global node
    node = BtcNode(
        host="localhost",
        port=btc_node_ports["18443"],
        internal_ip=btc_node_ip,
    )
    node.wait_ready()
    print("- started btc-node")

    wasabi_backend_ip, wasabi_backend_ports = driver.run(
        "wasabi-backend",
        f"{args.image_prefix}wasabi-backend",
        ports={"37127": "37127"},
        env={
            "WASABI_BIND": "http://0.0.0.0:37127",
            "ADDR_BTC_NODE": args.addr_btc_node or node.internal_ip,
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
    coordinator = WasabiBackend(
        host="localhost",
        port=wasabi_backend_ports["37127"],
        internal_ip=wasabi_backend_ip,
    )
    coordinator.wait_ready()
    print("- started wasabi-backend")

    _, wasabi_client_distributor_ports = driver.run(
        "wasabi-client-distributor",
        f"{args.image_prefix}wasabi-client",
        env={
            "ADDR_BTC_NODE": args.addr_btc_node or node.internal_ip,
            "ADDR_WASABI_BACKEND": args.addr_wasabi_backend or coordinator.internal_ip,
        },
        ports={"37128": "37128"},
        skip_ip=True,
    )
    global distributor
    distributor = WasabiClient(
        "localhost",
        wasabi_client_distributor_ports["37128"],
        "wasabi-client-distributor",
    )
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
        _, manager_ports = driver.run(
            f"wasabi-client-{idx:03}",
            f"{args.image_prefix}wasabi-client",
            env={
                "ADDR_BTC_NODE": args.addr_btc_node or node.internal_ip,
                "ADDR_WASABI_BACKEND": args.addr_wasabi_backend
                or coordinator.internal_ip,
            },
            ports={"37128": str(37129 + idx)},
        )
        client = WasabiClient(
            "localhost",
            manager_ports["37128"],
            f"wasabi-client-{idx:03}",
            wallet.get("delay", 0),
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


def main():
    print(f"Starting scenario {SCENARIO['name']}")
    prepare_images()
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
    parser.add_argument("command", type=str, choices=["build", "clean", "run"])
    parser.add_argument("--image-prefix", type=str, default="", help="image prefix")
    parser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    parser.add_argument("--scenario", type=str, help="scenario specification")
    parser.add_argument(
        "--driver",
        type=str,
        choices=["docker", "podman"],
        default="docker",
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

    match args.command:
        case "build":
            prepare_images()
            exit(0)
        case "clean":
            driver.cleanup(args.image_prefix)
            exit(0)
        case "run":
            pass
        case _:
            print("Unknown command")
            exit(1)

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
        driver.cleanup(args.image_prefix)
