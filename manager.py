from manager.btc_node import BtcNode
from manager.wasabi_client import WasabiClient
from manager.wasabi_backend import WasabiBackend
from time import sleep, time
import docker
import podman
import os
import datetime
import json
import argparse
from io import BytesIO
import tarfile
import multiprocessing
import shutil


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
podman_client = None
docker_client = None
docker_network = None
node = None
coordinator = None
distributor = None
clients = []


def build_images():
    print("Building Docker images")
    docker_client.images.build(path="./btc-node", tag="btc-node", rm=True)
    print("- btc-node image built")
    docker_client.images.build(path="./wasabi-backend", tag="wasabi-backend", rm=True)
    print("- wasabi-backend image built")
    docker_client.images.build(path="./wasabi-client", tag="wasabi-client", rm=True)
    print("- wasabi-client image built")


def start_infrastructure():
    print("Starting infrastructure")
    if args.podman:
        print("- skipping network creation")
    else:
        old_networks = docker_client.networks.list("coinjoin")
        if old_networks:
            print("- detected existing coinjoin network")
            for old_network in old_networks:
                old_network.remove()
                print(f"- removed coinjoin network")
        global docker_network
        docker_network = docker_client.networks.create("coinjoin", driver="bridge")
        print(f"- created coinjoin network")

    (podman_client if args.podman else docker_client).containers.run(
        "btc-node",
        detach=True,
        auto_remove=True,
        name="btc-node",
        hostname="btc-node",
        ports={"18443": "18443", "18444": "18444"},
        **({} if args.podman else {"network": docker_network.id}),
    )
    global node
    node = BtcNode("btc-node")
    node.wait_ready()
    print("- started btc-node")

    (podman_client if args.podman else docker_client).containers.run(
        "wasabi-backend",
        detach=True,
        auto_remove=True,
        name="wasabi-backend",
        hostname="wasabi-backend",
        ports={"37127": "37127"},
        environment={
            "WASABI_BIND": "http://0.0.0.0:37127",
            "ADDR_BTC_NODE": args.addr_btc_node,
        },
        **({} if args.podman else {"network": docker_network.id}),
    )
    fo = BytesIO()
    with tarfile.open(fileobj=fo, mode="w") as tar:
        info = tarfile.TarInfo("WabiSabiConfig.json")
        with open("./wasabi-backend/WabiSabiConfig.json", "r") as config_file:
            backend_config = json.load(config_file)
        backend_config.update(SCENARIO.get("backend", {}))
        scenario_file = BytesIO()
        scenario_bytes = json.dumps(backend_config, indent=2).encode()
        scenario_file.write(scenario_bytes)
        scenario_file.seek(0)
        info.size = len(scenario_bytes)
        info.uid = 1000
        info.gid = 1000
        info.mtime = int(time())
        tar.addfile(info, scenario_file)
    fo.seek(0)
    docker_client.containers.get("wasabi-backend").put_archive(
        "/home/wasabi/.walletwasabi/backend/", fo
    )

    global coordinator
    coordinator = WasabiBackend("wasabi-backend", 37127)
    coordinator.wait_ready()
    print("- started wasabi-backend")

    (podman_client if args.podman else docker_client).containers.run(
        "wasabi-client",
        detach=True,
        auto_remove=True,
        name=f"wasabi-client-distributor",
        hostname=f"wasabi-client-distributor",
        environment={
            "ADDR_BTC_NODE": args.addr_btc_node,
            "ADDR_WASABI_BACKEND": args.addr_wasabi_backend,
        },
        ports={"37128": "37128"},
        **({} if args.podman else {"network": docker_network.id}),
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
        (podman_client if args.podman else docker_client).containers.run(
            "wasabi-client",
            detach=True,
            auto_remove=True,
            name=f"wasabi-client-{idx}",
            hostname=f"wasabi-client-{idx}",
            environment={
                "ADDR_BTC_NODE": args.addr_btc_node,
                "ADDR_WASABI_BACKEND": args.addr_wasabi_backend,
            },
            ports={"37128": 37129 + idx},
            **({} if args.podman else {"network": docker_network.id}),
        )
        client = WasabiClient(
            f"wasabi-client-{idx}", 37129 + idx, wallet.get("delay", 0)
        )
        clients.append(client)
        new_idxs.append(idx)

    for idx in new_idxs:
        client = clients[idx]
        client.wait_wallet()
        print(f"- started {client.name}")
    return new_idxs


def fund_clients(invoices):
    print("Funding clients")
    addressed_invoices = []
    for client, values in invoices:
        for value in values:
            addressed_invoices.append((client.get_new_address(), value))
    distributor.send(addressed_invoices)
    print("- created wallet-funding transaction")
    for client, values in invoices:
        while client.get_balance() < sum(values):
            sleep(0.1)
    print("- funded")


def start_coinjoins(round=0):
    for client in clients:
        if client.delay <= round and not client.active:
            client.start_coinjoin()
            print(f"- started mixing {client.name} (round {round})")


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
        stream, _ = docker_client.containers.get("wasabi-backend").get_archive(
            "/home/wasabi/.walletwasabi/backend/"
        )

        fo = BytesIO()
        for d in stream:
            fo.write(d)
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            tar.extractall(os.path.join(data_path, "wasabi-backend"))

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
            stream, _ = docker_client.containers.get(client.name).get_archive(
                "/home/wasabi/.walletwasabi/client/"
            )

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(client_path)

            print(f"- stored {client.name} logs")
        except:
            print(f"- could not store {client.name} logs")

    shutil.make_archive(experiment_path, "zip", experiment_path)
    print("- zip archive created")


def stop_container(container_name):
    try:
        (podman_client if args.podman else docker_client).containers.get(
            container_name
        ).stop()
        print(f"- stopped {container_name}")
    except docker.errors.NotFound:
        pass


def stop_clients():
    print("Stopping clients")
    with multiprocessing.Pool() as pool:
        pool.map(
            stop_container,
            map(lambda x: x.name, clients),
        )


def stop_infrastructure():
    print("Stopping infrastructure")
    stop_container(node.name)
    stop_container(coordinator.name)
    stop_container(distributor.name)

    if not args.podman:
        old_networks = docker_client.networks.list("coinjoin")
        if old_networks:
            for old_network in old_networks:
                old_network.remove()
                print(f"- removed coinjoin network")


def main():
    print(f"Starting scenario {SCENARIO['name']}")
    build_images()
    start_infrastructure()
    fund_distributor(49)
    start_clients(SCENARIO["wallets"])
    invoices = [
        (client, wallet.get("funds", []))
        for client, wallet in zip(clients, SCENARIO["wallets"])
    ]
    fund_clients(invoices)
    start_coinjoins()

    print("Running")
    rounds = 0
    while SCENARIO["rounds"] == 0 or rounds < SCENARIO["rounds"]:
        stream, _ = docker_client.containers.get("wasabi-backend").get_archive(
            "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt"
        )

        fo = BytesIO()
        for d in stream:
            fo.write(d)
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            rounds = sum(
                1
                for _ in tar.extractfile("CoinJoinIdStore.txt")
                .read()
                .decode()
                .split("\n")[:-1]
            )
        start_coinjoins(rounds)
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
        "--podman",
        action="store_true",
        help="run in podman-compatible mode (requires the host IP to be set with --addr-*)",
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

    if args.cleanup_only:
        docker_client = docker.from_env()
        containers = docker_client.containers.list()
        for container in containers:
            if containers[0].attrs["Config"]["Image"] in (
                "btc-node",
                "wasabi-backend",
                "wasabi-client",
            ):
                container.stop()
                print(container.name, "container stopped")
        networks = docker_client.networks.list("coinjoin")
        if networks:
            for network in networks:
                network.remove()
                print(network.name, "network removed")
        exit(0)

    if args.scenario:
        with open(args.scenario) as f:
            SCENARIO.update(json.load(f))

    docker_client = docker.from_env()
    if args.podman:
        podman_client = podman.PodmanClient()
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("KeyboardInterrupt received")
    finally:
        store_logs()
        stop_clients()
        stop_infrastructure()
