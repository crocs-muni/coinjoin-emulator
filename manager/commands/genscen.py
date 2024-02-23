import argparse
import json
import os
import sys
import numpy.random
import copy

SCENARIO_TEMPLATE = {
    "name": "template",
    "rounds": 0,
    "blocks": 120,
    "backend": {
        "MaxInputCountByRound": 400,
        "MinInputCountByRoundMultiplier": 0.01,
        "StandardInputRegistrationTimeout": "0d 0h 20m 0s",
        "ConnectionConfirmationTimeout": "0d 0h 6m 0s",
        "OutputRegistrationTimeout": "0d 0h 6m 0s",
        "TransactionSigningTimeout": "0d 0h 6m 0s",
        "FailFastTransactionSigningTimeout": "0d 0h 6m 0s",
        "RoundExpiryTimeout": "0d 0h 10m 0s",
    },
    "wallets": [],
}


def setup_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--client-count", type=int, default=10, help="number of wallets"
    )
    parser.add_argument(
        "--distribution",
        type=str,
        default="uniformsum",
        choices=["uniformsum", "paretosum"],
        help="fund distribution strategy",
    )
    parser.add_argument(
        "--utxo-count", type=int, default=30, help="number of UTXOs per wallet"
    )
    parser.add_argument(
        "--max-coinjoin",
        type=int,
        default=400,
        help="maximal number of inputs to a coinjoin",
    )
    parser.add_argument(
        "--min-coinjoin",
        type=int,
        default=4,
        help="minimal number of inputs to a coinjoin",
    )
    parser.add_argument(
        "--stop-round",
        type=int,
        default=0,
        help="terminate after N coinjoin rounds, 0 for no limit",
    )
    parser.add_argument(
        "--stop-block",
        type=int,
        default=120,
        help="terminate after N blocks, 0 for no limit",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument(
        "--out-dir", type=str, default="scenarios", help="output directory"
    )


def handler(args):
    scenario = copy.deepcopy(SCENARIO_TEMPLATE)
    scenario["name"] = (
        f"{args.distribution}-static-{args.client_count}-{args.utxo_count}utxo"
    )

    scenario["backend"]["MaxInputCountByRound"] = args.max_coinjoin
    scenario["backend"]["MinInputCountByRoundMultiplier"] = (
        args.min_coinjoin / args.max_coinjoin
    )
    scenario["rounds"] = args.stop_round
    scenario["blocks"] = args.stop_block

    delays = [0] * args.client_count

    match args.distribution:
        case "uniformsum":
            for delay in delays:
                dist = numpy.random.uniform(0.0, 1.0, args.utxo_count)
                funds = list(
                    map(lambda x: round(x), list(dist / sum(dist) * 100_000_000))
                )
                scenario["wallets"].append({"funds": funds, "delay": delay})
        case "paretosum":
            for delay in delays:
                dist = numpy.random.pareto(1.16, args.utxo_count)
                funds = list(
                    map(lambda x: round(x), list(dist / sum(dist) * 100_000_000))
                )
                scenario["wallets"].append({"funds": funds, "delay": delay})
        case _:
            print("Invalid distribution")
            return {}

    os.makedirs(args.out_dir, exist_ok=True)
    if os.path.exists(f"{args.out_dir}/{scenario['name']}.json") and not args.force:
        print(f"File {args.out_dir}/{scenario['name']}.json already exists", file=sys.stderr)
        return

    with open(f"{args.out_dir}/{scenario['name']}.json", "w") as f:
        json.dump(scenario, f, indent=2)

    print(f"Scenario generated and saved to {args.out_dir}/{scenario['name']}.json")
    print(
        f"- requires {(sum(map(lambda x: sum(x['funds']), scenario['wallets'])) / 100_000_000):0.8f} BTC"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a scenario file")
    setup_parser(parser)
    handler(parser.parse_args())
