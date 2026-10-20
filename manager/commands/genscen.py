import argparse
import json
import os
import sys
import numpy.random
import copy
import random

from manager.engine.configuration import ScenarioConfig, WalletConfig, WasabiConfig

def create_backend_config(args):
    """Create backend configuration dictionary."""
    return {
        "MaxInputCountByRound": args.max_coinjoin,
        "MinInputCountByRoundMultiplier": args.min_coinjoin / args.max_coinjoin,
        "StandardInputRegistrationTimeout": "0d 0h 20m 0s",
        "ConnectionConfirmationTimeout": "0d 0h 6m 0s",
        "OutputRegistrationTimeout": "0d 0h 6m 0s",
        "TransactionSigningTimeout": "0d 0h 6m 0s",
        "FailFastTransactionSigningTimeout": "0d 0h 6m 0s",
        "RoundExpiryTimeout": "0d 0h 10m 0s",
    }


def setup_parser(parser: argparse.ArgumentParser):
    parser.add_argument("--name", type=str, help="scenario name")
    parser.add_argument(
        "--client-count", type=int, default=10, help="number of wallets"
    )
    parser.add_argument("--type", type=str, default="static", help="scenario type")
    parser.add_argument(
        "--distribution",
        type=str,
        default="lognorm",
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
        default=0,
        help="terminate after N blocks, 0 for no limit",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument(
        "--out-dir", type=str, default="scenarios", help="output directory"
    )
    parser.add_argument(
        "--distributor-version",
        type=str,
        required=False,
        help="version of the distibutor wallet",
    )
    parser.add_argument(
        "--client-version",
        type=str,
        required=False,
        help="version of the client wallet",
    )
    parser.add_argument(
        "--anon-score-target",
        type=int,
        required=False,
        help="default anon score target used for wallets",
    )
    parser.add_argument(
        "--redcoin-isolation",
        type=bool,
        required=False,
        help="default redcoin isolation setting used for wallets",
    )


def format_name(args):
    if args.name:
        return args.name
    if args.type == "static":
        return (
            f"{args.distribution}-{args.type}-{args.client_count}-{args.utxo_count}utxo"
        )
    if args.type == "default":
        return f"{args.distribution}-{args.type}-{args.client_count}"
    if args.type == "overmixing":
        return f"{args.distribution}-{args.type}-{args.client_count}"
    if args.type == "delayed":
        return f"{args.distribution}-{args.type}-{args.client_count}"
    if args.type == "delayed-overmixing":
        return f"{args.distribution}-{args.type}-{args.client_count}"
    
    # Default fallback
    return f"{args.distribution}-{args.type}-{args.client_count}"


def prepare_distribution(distribution):
    dist_name = distribution.split("[")[0]
    dist_params = None
    if "[" in distribution:
        dist_params = list(map(float, distribution.split("[")[1].split("]")[0].split(",")))

    match dist_name:
        case "uniform":
            params = dist_params or [0.0, 10_000_000.0]
            return lambda x: map(round, numpy.random.uniform(params[0], params[1], x))
        case "pareto":
            params = dist_params or [1.16]
            return lambda x: map(
                round, numpy.random.pareto(params[0], x) * 1_000_000
            )
        case "lognorm":
            # parameters estimated from mainnet data of Wasabi 2.0 coinjoins
            params = dist_params or [14.1, 2.29]
            return lambda x: map(round, numpy.random.lognormal(params[0], params[1], x))
        case _:
            return None


def prepare_wallet(args, idx, distribution):
    """Create a WalletConfig object based on args and wallet type."""
    funds = None
    anon_score_target = None
    redcoin_isolation = None
    delay_rounds = None

    if args.type == "default":
        funds = list(distribution(random.randint(1, 10)))
        if idx < args.client_count // 5:
            anon_score_target = random.randint(27, 75)
            redcoin_isolation = True
        else:
            anon_score_target = 5
    elif args.type == "overmixing":
        funds = list(distribution(random.randint(1, 10)))
        if idx < args.client_count // 10:
            anon_score_target = 1_000_000
        elif idx < args.client_count // 5:
            anon_score_target = random.randint(27, 75)
            redcoin_isolation = True
        else:
            anon_score_target = 5
    elif args.type == "delayed":
        funds = list(distribution(random.randint(1, 10)))
        delay_rounds = random.randint(1, 5)
        if idx < args.client_count // 5:
            anon_score_target = random.randint(27, 75)
            redcoin_isolation = True
        else:
            anon_score_target = 5
    elif args.type == "delayed-overmixing":
        funds = list(distribution(random.randint(1, 10)))
        if idx < args.client_count // 10:
            anon_score_target = 1_000_000
        elif idx < args.client_count // 5:
            delay_rounds = random.randint(1, 5)
            anon_score_target = random.randint(27, 75)
            redcoin_isolation = True
        else:
            delay_rounds = random.randint(1, 5)
            anon_score_target = 5
    else:
        funds = list(distribution(args.utxo_count))

    # Create Wasabi-specific config if any Wasabi settings are present
    wasabi_config = None
    if anon_score_target is not None or redcoin_isolation is not None:
        wasabi_config = WasabiConfig(
            anon_score_target=anon_score_target,
            redcoin_isolation=redcoin_isolation,
        )

    return WalletConfig(
        funds=funds,
        delay_rounds=delay_rounds,
        wasabi=wasabi_config
    )


def handler(args):
    print("Generating scenario...")
    
    distribution = prepare_distribution(args.distribution)
    if not distribution:
        print("- invalid distribution")
        sys.exit(1)

    # Generate wallets
    wallets = []
    for idx in range(args.client_count):
        wallets.append(prepare_wallet(args, idx, distribution))

    # Create scenario
    scenario = ScenarioConfig(
        name=format_name(args),
        rounds=args.stop_round,
        blocks=args.stop_block,
        default_version=args.client_version or "2.0.4",
        wallets=wallets,
        distributor_version=args.distributor_version,
        default_anon_score_target=args.anon_score_target,
        default_redcoin_isolation=args.redcoin_isolation,
        backend=create_backend_config(args)
    )

    # Calculate total BTC required
    total_funds = 0
    for wallet in scenario.wallets:
        for fund in wallet.funds:
            if isinstance(fund, int):
                total_funds += fund
            # FundConfig objects would have fund.value, but genscen only creates int funds
    print(f"- requires {total_funds / 100_000_000:0.8f} BTC")

    os.makedirs(args.out_dir, exist_ok=True)
    if os.path.exists(f"{args.out_dir}/{scenario.name}.json") and not args.force:
        print(f"- file {args.out_dir}/{scenario.name}.json already exists")
        sys.exit(1)

    with open(f"{args.out_dir}/{scenario.name}.json", "w") as f:
        json.dump(scenario.to_dict(), f, indent=2)

    print(f"- saved to {args.out_dir}/{scenario.name}.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a scenario file")
    setup_parser(parser)
    handler(parser.parse_args())
