from manager.btc_node import BtcNode
from manager.wasabi_client import WasabiClient
from manager.wasabi_backend import WasabiBackend
from manager import utils
import manager.commands.genscen
from time import sleep, time
import sys
import random
import os
import datetime
import json
import argparse
import shutil
import tempfile
import multiprocessing
import multiprocessing.pool
import platform


BTC = 100_000_000
SCENARIO = {
    "name": "default",
    "rounds": 10,  # the number of coinjoins after which the simulation stops (0 for no limit)
    "blocks": 0,  # the number of mined blocks after which the simulation stops (0 for no limit)
    "wallets": [
        {"funds": [200000, 50000], "delay": 0},
        {"funds": [3000000], "delay": 0},
        {"funds": [1000000, 500000], "delay": 0},
        {"funds": [1000000, 500000], "delay": 0},
        {"funds": [1000000, 500000], "delay": 0},
        {"funds": [3000000, 15000], "delay": 0},
        {"funds": [1000000, 500000], "delay": 0},
        {"funds": [1000000, 500000], "delay": 0},
        {"funds": [3000000, 600000], "delay": 0},
        {"funds": [1000000, 500000], "delay": 0},
    ],
}

args = None
driver = None
node = None
coordinator = None
distributor = None
clients = []

def get_paralelism_pool():
    if platform.system() == "Windows":
        return multiprocessing.pool.ThreadPool()
    else:
        return multiprocessing.Pool()


def prepare_image(name):
    prefixed_name = args.image_prefix + name
    if driver.has_image(prefixed_name):
        if args.force_rebuild:
            if args.image_prefix:
                driver.pull(prefixed_name)
                print(f"- image pulled {prefixed_name}")
            else:
                driver.build(name, f"./containers/{name}")
                print(f"- image rebuilt {prefixed_name}")
        else:
            print(f"- image reused {prefixed_name}")
    elif args.image_prefix:
        driver.pull(prefixed_name)
        print(f"- image pulled {prefixed_name}")
    else:
        driver.build(name, f"./containers/{name}")
        print(f"- image built {prefixed_name}")


def prepare_images():
    print("Preparing images")
    prepare_image("btc-node")
    prepare_image("wasabi-backend")
    prepare_image("wasabi-client")


def start_infrastructure():
    print("Starting infrastructure")
    btc_node_ip, btc_node_ports = driver.run(
        "btc-node",
        f"{args.image_prefix}btc-node",
        ports={18443: 18443, 18444: 18444},
        cpu=4.0,
        memory=8192,
    )
    global node
    node = BtcNode(
        host=btc_node_ip if args.proxy else args.control_ip,
        port=18443 if args.proxy else btc_node_ports[18443],
        internal_ip=btc_node_ip,
        proxy=args.proxy,
    )
    node.wait_ready()
    print("- started btc-node")

    wasabi_backend_ip, wasabi_backend_ports = driver.run(
        "wasabi-backend",
        f"{args.image_prefix}wasabi-backend",
        ports={37127: 37127},
        env={
            "WASABI_BIND": "http://0.0.0.0:37127",
            "ADDR_BTC_NODE": args.btc_node_ip or node.internal_ip,
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

    driver.upload(
        "wasabi-backend",
        scenario_file,
        "/home/wasabi/.walletwasabi/backend/WabiSabiConfig.json",
    )

    global coordinator
    coordinator = WasabiBackend(
        host=wasabi_backend_ip if args.proxy else args.control_ip,
        port=37127 if args.proxy else wasabi_backend_ports[37127],
        internal_ip=wasabi_backend_ip,
        proxy=args.proxy,
    )
    coordinator.wait_ready()
    print("- started wasabi-backend")

    wasabi_client_distributor_ip, wasabi_client_distributor_ports = driver.run(
        "wasabi-client-distributor",
        f"{args.image_prefix}wasabi-client",
        env={
            "ADDR_BTC_NODE": args.btc_node_ip or node.internal_ip,
            "ADDR_WASABI_BACKEND": args.wasabi_backend_ip or coordinator.internal_ip,
        },
        ports={37128: 37128},
        cpu=1.0,
        memory=2048,
    )
    global distributor
    distributor = WasabiClient(
        host=wasabi_client_distributor_ip if args.proxy else args.control_ip,
        port=37128 if args.proxy else wasabi_client_distributor_ports[37128],
        name="wasabi-client-distributor",
        proxy=args.proxy,
    )
    if not distributor.wait_wallet(timeout=60):
        print(f"- could not start distributor (application timeout)")
        raise Exception("Could not start distributor")
    print("- started distributor")


def fund_distributor(btc_amount):
    print("Funding distributor")
    for _ in range(4):
        node.fund_address(distributor.get_new_address(), btc_amount / 4)
    while (balance := distributor.get_balance()) < btc_amount * BTC:
        sleep(1)
    print(f"- funded (current balance {balance / BTC:.8f} BTC)")


def start_client(idx, wallet):
    sleep(random.random() * 3)
    name = f"wasabi-client-{idx:03}"
    try:
        ip, manager_ports = driver.run(
            name,
            f"{args.image_prefix}wasabi-client",
            env={
                "ADDR_BTC_NODE": args.btc_node_ip or node.internal_ip,
                "ADDR_WASABI_BACKEND": args.wasabi_backend_ip
                or coordinator.internal_ip,
            },
            ports={37128: 37129 + idx},
        )
    except Exception as e:
        print(f"- could not start {name} ({e})")
        return None

    client = WasabiClient(
        host=ip if args.proxy else args.control_ip,
        port=37128 if args.proxy else manager_ports[37128],
        name=f"wasabi-client-{idx:03}",
        delay=wallet.get("delay", 0),
        proxy=args.proxy,
    )
    start = time()
    if not client.wait_wallet(timeout=60):
        print(
            f"- could not start {name} (application timeout {time() - start} seconds)"
        )
        return None
    print(f"- started {client.name} (wait took {time() - start} seconds)")
    return client


def start_clients(wallets):
    print("Starting clients")
    with get_paralelism_pool() as pool:
        new_clients = pool.starmap(start_client, enumerate(wallets, start=len(clients)))

        for _ in range(3):
            restart_idx = list(
                map(
                    lambda x: x[0],
                    filter(
                        lambda x: x[1] is None,
                        enumerate(new_clients, start=len(clients)),
                    ),
                )
            )

            if not restart_idx:
                break
            print(f"- failed to start {len(restart_idx)} clients; retrying ...")
            for idx in restart_idx:
                driver.stop(f"wasabi-client-{idx:03}")
            sleep(60)
            restarted_clients = pool.starmap(
                start_client,
                ((idx, wallets[idx - len(clients)]) for idx in restart_idx),
            )
            for idx, client in enumerate(restarted_clients):
                if client is not None:
                    new_clients[restart_idx[idx]] = client
        else:
            new_clients = list(filter(lambda x: x is not None, new_clients))
            print(
                f"- failed to start {len(wallets) - len(new_clients)} clients; continuing ..."
            )
    clients.extend(new_clients)


def wait_funds(client, funds):
    sleep(random.random())
    start = time()
    balance = 0.0
    while (balance + 0.001) < sum(funds):
        balance = client.get_balance(timeout=5)
        if balance == "timeout":
            balance = 0.0
        sleep(1)

        if start - time() > 90:
            print(
                f"- funding timeout {client.name} (current balance {balance / BTC:.8f} BTC)"
            )
            return
    print(f"- funded {client.name} (current balance {balance / BTC:.8f} BTC)")


def fund_clients(invoices):
    print("Funding clients")
    for batch in utils.batched(invoices, 50):
        addressed_invoices = []
        for client, values in batch:
            for value in values:
                addressed_invoices.append((client.get_new_address(), value))
        if str(distributor.send(addressed_invoices)) == "timeout":
            print("- funding timeout")
            raise Exception("Distributor timeout")
        else:
            print("- created funding transaction")

    with get_paralelism_pool() as pool:
        pool.starmap(wait_funds, invoices)


def start_coinjoin(client, delay):
    client.start_coinjoin()
    print(f"- started mixing {client.name} (delay {delay})")


def start_coinjoins(delay=0):
    ready = list(filter(lambda x: (x.delay <= delay and not x.active), clients))

    with get_paralelism_pool() as pool:
        pool.starmap(start_coinjoin, ((client, delay) for client in ready))

    # client object are modified in different processes, so we need to update them manually
    for client in ready:
        client.active = True


def stop_coinjoins():
    print("Stopping coinjoins")
    for client in clients:
        client.stop_coinjoin()
        print(f"- stopped mixing {client.name}")


def store_client_logs(client, data_path):
    sleep(random.random() * 3)
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
        driver.download(client.name, "/home/wasabi/.walletwasabi/client/", client_path)

        print(f"- stored {client.name} logs")
    except:
        print(f"- could not store {client.name} logs")


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
            os.path.join(data_path, "wasabi-backend"),
        )

        print(f"- stored backend logs")
    except:
        print(f"- could not store backend logs")

    with get_paralelism_pool() as pool:
        pool.starmap(store_client_logs, ((client, data_path) for client in clients))

    shutil.make_archive(experiment_path, "zip", *os.path.split(experiment_path))
    print("- zip archive created")


def run():
    if args.scenario:
        with open(args.scenario) as f:
            SCENARIO.update(json.load(f))

    try:
        print(f"=== Scenario {SCENARIO['name']} ===")
        prepare_images()
        start_infrastructure()
        fund_distributor(1000)
        start_clients(SCENARIO["wallets"])
        invoices = [
            (client, wallet.get("funds", []))
            for client, wallet in zip(clients, SCENARIO["wallets"])
        ]
        fund_clients(invoices)

        print("Mixing")
        rounds = 0
        initial_blocks = node.get_block_count()
        blocks = 0
        while (SCENARIO["rounds"] == 0 or rounds < SCENARIO["rounds"]) and (
            SCENARIO["blocks"] == 0 or blocks < SCENARIO["blocks"]
        ):
            for _ in range(3):
                try:
                    rounds = sum(
                        1
                        for _ in driver.peek(
                            "wasabi-backend",
                            "/home/wasabi/.walletwasabi/backend/WabiSabi/CoinJoinIdStore.txt",
                        ).split("\n")[:-1]
                    )
                    break
                except Exception as e:
                    print(f"- could not get rounds ({e})")
                    rounds = 0

            start_coinjoins(blocks := node.get_block_count() - initial_blocks)
            print(f"- coinjoin rounds: {rounds} (block {blocks})", end="\r")
            sleep(1)
        print()
        print(f"- limit reached")
    except KeyboardInterrupt:
        print()
        print("KeyboardInterrupt received")
    except Exception as e:
        print(f"Exception: {e}", file=sys.stderr)
    finally:
        stop_coinjoins()
        if not args.no_logs:
            store_logs()
        driver.cleanup(args.image_prefix)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run coinjoin simulation setup")
    subparsers = parser.add_subparsers(dest="command", title="command")

    parser.add_argument(
        "--driver",
        type=str,
        choices=["docker", "podman", "kubernetes"],
        default="docker",
    )
    parser.add_argument("--no-logs", action="store_true", default=False)

    build_subparser = subparsers.add_parser("build", help="build images")
    build_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )

    run_subparser = subparsers.add_parser("run", help="run simulation")
    run_subparser.add_argument(
        "--force-rebuild", action="store_true", help="force rebuild of images"
    )
    run_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )
    run_subparser.add_argument(
        "--scenario", type=str, help="scenario specification file"
    )
    run_subparser.add_argument(
        "--btc-node-ip", type=str, help="override btc-node ip", default=""
    )
    run_subparser.add_argument(
        "--wasabi-backend-ip",
        type=str,
        help="override wasabi-backend ip",
        default="",
    )
    run_subparser.add_argument(
        "--control-ip", type=str, help="control ip", default="localhost"
    )
    run_subparser.add_argument("--proxy", type=str, default="")
    run_subparser.add_argument("--namespace", type=str, default="coinjoin")
    run_subparser.add_argument("--reuse-namespace", action="store_true", default=False)

    clean_subparser = subparsers.add_parser("clean", help="clean up")
    clean_subparser.add_argument("--namespace", type=str, default="coinjoin")
    clean_subparser.add_argument(
        "--reuse-namespace", action="store_true", default=False
    )
    clean_subparser.add_argument("--proxy", type=str, default="")
    clean_subparser.add_argument(
        "--image-prefix", type=str, default="", help="image prefix"
    )

    genscen_subparser = subparsers.add_parser("genscen", help="generate scenario file")
    manager.commands.genscen.setup_parser(genscen_subparser)

    args = parser.parse_args()

    if args.command == "genscen":
        manager.commands.genscen.handler(args)
        exit(0)

    match args.driver:
        case "docker":
            from manager.driver.docker import DockerDriver

            driver = DockerDriver(args.namespace)
        case "podman":
            from manager.driver.podman import PodmanDriver

            driver = PodmanDriver()
        case "kubernetes":
            from manager.driver.kubernetes import KubernetesDriver

            driver = KubernetesDriver(args.namespace, args.reuse_namespace)
        case _:
            print(f"Unknown driver '{args.driver}'")
            exit(1)

    match args.command:
        case "build":
            prepare_images()
        case "clean":
            driver.cleanup(args.image_prefix)
        case "run":
            run()
        case _:
            print(f"Unknown command '{args.command}'")
            exit(1)
