from manager.btc_node import BtcNode
from manager.wasabi_client import WasabiClient
from manager.wasabi_backend import WasabiBackend
from time import sleep
import docker
import os
import shutil
import datetime
import json
import argparse

BTC = 100_000_000

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
    if os.path.exists("./mounts/"):
        shutil.rmtree("./mounts/")
    os.mkdir("./mounts/")
    print("- created mounts/ directory")
    global docker_network
    docker_network = docker_client.networks.create("coinjoin", driver="bridge")
    print(f"- created coinjoin network")

    docker_client.containers.run(
        "btc-node",
        detach=True,
        auto_remove=True,
        name="btc-node",
        hostname="btc-node",
        ports={"18443": "18443"},
        network=docker_network.id,
    )
    global node
    node = BtcNode("btc-node")
    node.wait_ready()
    print("- started btc-node")

    os.mkdir("./mounts/backend/")
    shutil.copyfile("./wasabi-backend/Config.json", "./mounts/backend/Config.json")
    shutil.copyfile(
        "./wasabi-backend/WabiSabiConfig.json",
        "./mounts/backend/WabiSabiConfig.json",
    )
    docker_client.containers.run(
        "wasabi-backend",
        detach=True,
        auto_remove=True,
        name="wasabi-backend",
        hostname="wasabi-backend",
        ports={"37127": "37127"},
        environment=["WASABI_BIND=http://0.0.0.0:37127"],
        volumes=[
            f"{os.path.abspath('./mounts/backend/')}:/home/wasabi/.walletwasabi/backend/"
        ],
        network=docker_network.id,
    )
    global coordinator
    coordinator = WasabiBackend("wasabi-backend", 37127)
    coordinator.wait_ready()
    print("- started wasabi-backend")

    docker_client.containers.run(
        "wasabi-client",
        detach=True,
        auto_remove=True,
        name=f"wasabi-client-distributor",
        hostname=f"wasabi-client-distributor",
        ports={"37128": "37128"},
        network=docker_network.id,
    )
    global distributor
    distributor = WasabiClient("wasabi-client-distributor", 37128)
    distributor.wait_wallet()
    print("- started distributor")


def fund_distributor(btc_amount):
    print("Funding distributor")
    node.fund_address(distributor.get_new_address(), btc_amount)
    node.mine_block()
    while (balance := distributor.get_balance()) < btc_amount * BTC:
        sleep(0.1)
    print(f"- funded (current balance {balance / BTC:.8f} BTC)")


def start_clients(num_clients):
    print("Starting clients")
    new_idxs = []
    for _ in range(num_clients):
        idx = len(clients)
        docker_client.containers.run(
            "wasabi-client",
            detach=True,
            auto_remove=True,
            name=f"wasabi-client-{idx}",
            hostname=f"wasabi-client-{idx}",
            ports={"37128": 37129 + idx},
            network=docker_network.id,
        )
        client = WasabiClient(f"wasabi-client-{idx}", 37129 + idx)
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
    node.mine_block()
    for client, values in invoices:
        while client.get_balance() < sum(values):
            sleep(0.1)
    print("- funded")


def start_coinjoins():
    print("Starting coinjoins")
    for client in clients:
        client.start_coinjoin()
        print(f"- started {client.name}")


def store_logs():
    print("Storing logs")
    time = datetime.datetime.now().isoformat(timespec="seconds")
    if not os.path.exists("./logs/"):
        os.mkdir("./logs/")
    try:
        shutil.copytree("./mounts/backend/", f"./logs/{time}/wasabi-backend/")
        print("- stored backend logs")
    except FileNotFoundError:
        print("- could not find backend logs")

    for client in clients:
        os.mkdir(f"./logs/{time}/{client.name}/")
        with open(f"./logs/{time}/{client.name}/coins.json", "w") as f:
            json.dump(client.list_coins(), f, indent=2)
            print(f"- stored {client.name} coins")


def stop_clients():
    print("Stopping clients")
    for client in clients:
        try:
            docker_client.containers.get(client.name).stop()
            print(f"- stopped {client.name}")
        except docker.errors.NotFound:
            pass


def stop_infrastructure():
    print("Stopping infrastructure")
    try:
        docker_client.containers.get(node.name).stop()
        print("- stopped btc-node")
    except docker.errors.NotFound:
        pass
    try:
        docker_client.containers.get(coordinator.name).stop()
        print("- stopped wasabi-backend")
    except docker.errors.NotFound:
        pass
    try:
        docker_client.containers.get(distributor.name).stop()
        print("- stopped wasabi-client-distributor")
    except docker.errors.NotFound:
        pass

    old_networks = docker_client.networks.list("coinjoin")
    if old_networks:
        for old_network in old_networks:
            old_network.remove()
            print(f"- removed coinjoin network")

    if os.path.exists("./mounts/"):
        shutil.rmtree("./mounts/")
        print("- removed mounts/")


def main():
    build_images()
    start_infrastructure()
    fund_distributor(30)
    start_clients(10)
    invoices = [
        (clients[0], [200000, 50000]),
        (clients[1], [3000000]),
        (clients[2], [1000000, 500000]),
        (clients[3], [1000000, 500000]),
        (clients[4], [1000000, 500000]),
        (clients[5], [3000000, 15000]),
        (clients[6], [1000000, 500000]),
        (clients[7], [1000000, 500000]),
        (clients[8], [3000000, 600000]),
        (clients[9], [1000000, 500000]),
    ]
    fund_clients(invoices)
    start_coinjoins()

    print("Running")
    while True:
        with open("./mounts/backend/WabiSabi/CoinJoinIdStore.txt") as f:
            num_lines = sum(1 for _ in f)
        print(f"- number of coinjoins: {num_lines:<10}", end="\r")
        sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    parser.add_argument(
        "--cleanup-only", action="store_true", help="remove old logs and containers"
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
        if os.path.exists("./mounts/"):
            shutil.rmtree("./mounts/")
        print("mounts/ directory removed")
        exit(0)

    docker_client = docker.from_env()
    try:
        main()
    except KeyboardInterrupt:
        print("KeyboardInterrupt received")
    finally:
        store_logs()
        stop_clients()
        stop_infrastructure()
