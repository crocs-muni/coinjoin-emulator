import btc_node
import wasabi_client
from time import sleep
import random
import docker
import os
import shutil
import datetime

BTC = 100_000_000


def fund_distributor(btc_amount):
    wasabi_client.create_wallet("distributor")
    wasabi_client.wait_wallet("distributor")
    btc_node.fund_address(wasabi_client.get_new_address("distributor"), btc_amount)
    btc_node.mine_block()
    while wasabi_client.get_balance("distributor") < btc_amount * BTC:
        sleep(0.1)


def fund_wallets(invoices):
    for wallet, _ in invoices:
        print(f"- creating wallet {wallet}")
        wasabi_client.create_wallet(wallet)
        wasabi_client.wait_wallet(wallet)

    addressed_invoices = [
        (wasabi_client.get_new_address(wallet), amount) for wallet, amount in invoices
    ]

    print("- creating wallet-funding transaction")
    wasabi_client.send("distributor", addressed_invoices)
    btc_node.mine_block()

    for wallet, target_value in invoices:
        while wasabi_client.get_balance(wallet) < target_value:
            sleep(0.1)


def main():
    docker_client = docker.from_env()

    print("Building Docker images")
    docker_client.images.build(path="../btc-node", tag="btc-node", rm=True)
    print("- btc-node image built")
    docker_client.images.build(path="../wasabi-backend", tag="wasabi-backend", rm=True)
    print("- wasabi-backend image built")
    docker_client.images.build(path="../wasabi-client", tag="wasabi-client", rm=True)
    print("- wasabi-client image built")

    print("Setting up CoinJoin network")
    old_networks = docker_client.networks.list("coinjoin")
    if old_networks:
        for old_network in old_networks:
            print(f"- removing old CoinJoin network {old_network.id[:12]!r}")
            old_network.remove()

    docker_network = docker_client.networks.create("coinjoin", driver="bridge")
    print(f"- created new CoinJoin network {docker_network.id[:12]!r}")

    print("Starting infrastructure")
    btc_node_container = docker_client.containers.run(
        "btc-node",
        detach=True,
        auto_remove=True,
        name="btc-node",
        hostname="btc-node",
        ports={"18443": "18443"},
        network=docker_network.id,
    )
    sleep(10)  # TODO perform health check instead
    print("- started btc-node")

    if os.path.exists("../mounts/backend/"):
        shutil.rmtree("../mounts/backend/")
    os.mkdir("../mounts/backend/")
    shutil.copyfile("../wasabi-backend/Config.json", "../mounts/backend/Config.json")
    shutil.copyfile(
        "../wasabi-backend/WabiSabiConfig.json",
        "../mounts/backend/WabiSabiConfig.json",
    )
    wasabi_backend_container = docker_client.containers.run(
        "wasabi-backend",
        detach=True,
        auto_remove=True,
        name="wasabi-backend",
        hostname="wasabi-backend",
        ports={"37127": "37127"},
        environment=["WASABI_BIND=http://0.0.0.0:37127"],
        volumes=[
            f"{os.path.abspath('../mounts/backend/')}:/home/wasabi/.walletwasabi/backend/"
        ],
        network=docker_network.id,
    )
    sleep(10)  # TODO perform health check instead
    print("- started wasabi-backend")

    wasabi_client_container = docker_client.containers.run(
        "wasabi-client",
        detach=True,
        auto_remove=True,
        name="wasabi-client",
        hostname="wasabi-client",
        ports={"37128": "37128"},
        network=docker_network.id,
    )
    sleep(10)  # TODO perform health check instead
    print("- started wasabi-client")

    wallets = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    print("Funding distributor")
    fund_distributor(30)
    print("- funded")
    print("Funding wallets")
    invoices = list(
        zip(
            wallets,
            [int(random.random() * BTC * 0.001 + BTC) for _ in range(26)],
        )
    )
    fund_wallets(invoices)
    print("- funded")
    sleep(10)

    print("Starting coinjoins")
    for wallet in wallets:
        wasabi_client.start_coinjoin(wallet)
    print("- started")

    while True:
        with open("../mounts/backend/WabiSabi/CoinJoinIdStore.txt") as f:
            num_lines = sum(1 for _ in f)
        print(f"- number of coinjoins: {num_lines:<10}", end="\r")
        sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("KeyboardInterrupt received")
    finally:
        print("Storing logs")
        if not os.path.exists("../logs/"):
            os.mkdir("../logs/")
        shutil.copytree(
            "../mounts/backend/",
            f"../logs/{datetime.datetime.now().isoformat(timespec='seconds')}/",
        )

        print("Stopping infrastructure")
        docker_client = docker.from_env()
        try:
            docker_client.containers.get("btc-node").stop()
        except docker.errors.NotFound:
            pass
        try:
            docker_client.containers.get("wasabi-backend").stop()
        except docker.errors.NotFound:
            pass
        try:
            docker_client.containers.get("wasabi-client").stop()
        except docker.errors.NotFound:
            pass
