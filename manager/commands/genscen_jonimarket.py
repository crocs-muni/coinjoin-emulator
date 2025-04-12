SCENARIO = {
    "name": "expanded",
    "default_version": "joinmarket",
    "rounds": 10,  # the number of coinjoins after which the simulation stops (0 for no limit)
    "blocks": 0,  # the number of mined blocks after which the simulation stops (0 for no limit)
    "wallets": []
}

from random import randint, uniform


def generate_wallet(wallet_type, funds_range, min_offer_size, max_offer_size, counterparties_range):
    # Create a random list of funds (between 1 and 3 entries)
    funds = [randint(*funds_range) for _ in range(randint(1, 3))]

    if wallet_type == "taker":
        offers = [{
            "mixdepth": randint(0, len(funds) - 1),
            "amount_sats": randint(min_offer_size, max_offer_size),
            "counterparties": randint(*counterparties_range)
        }]
        wallet = {"funds": funds, "type": wallet_type, "offers": offers}

    elif wallet_type == "tumbler_taker":
        # Similar to taker, but with extra schedule options that will trigger the scheduled coinjoin RPC call.
        offers = [{
            "mixdepth": randint(0, len(funds) - 1),
            "amount_sats": randint(min_offer_size, max_offer_size),
            "counterparties": randint(*counterparties_range)
        }]
        # Here we generate some random schedule options. Adjust the ranges or use fixed values as needed.
        schedule = {
            "destination_addresses": [
                # A random (dummy) address; in your actual use you would likely have a deterministic or pre‐configured address.
                f"bcrt1q{randint(100000, 999999)}"
            ],
            "tumbler_options": {
                "addrcount": randint(1, 5),
                "minmakercount": randint(1, 3),
                # Ensure the lower bound is not larger than the upper bound
                "makercountrange": [randint(2, 5), randint(6, 10)],
                "mixdepthcount": randint(1, 4),
                "mintxcount": randint(1, 3),
                "txcountparams": [randint(1, 3), randint(4, 6)],
                "timelambda": randint(4, 10),
                "stage1_timelambda_increase": randint(1, 2),
                "liquiditywait": randint(60, 300),
                "waittime": randint(1, 5),
                "mixdepthsrc": 0,
                "restart": True,
                "mincjamount": randint(10000, 50000),
                "amtmixdepths": randint(1, 4),
                "rounding_chance": randint(0, 100),
                "rounding_sigfig_weights": [randint(1, 3) for _ in range(3)]
            }
        }
        wallet = {"funds": funds, "type": wallet_type, "offers": offers, "schedule": schedule}

    elif wallet_type == "maker":
        offers = [{
            "txfee": randint(0, 5000),
            "cjfee_a": randint(1000, 10000),
            "cjfee_r": round(uniform(0.00001, 0.0001), 8),
            "ordertype": "sw0reloffer",
            "minsize": randint(min_offer_size, int(max_offer_size / 2)),
            "maxsize": randint(int(max_offer_size / 2), max_offer_size)
        }]
        wallet = {"funds": funds, "type": wallet_type, "offers": offers}

    else:
        raise ValueError(f"Unknown wallet type: {wallet_type}")
    return wallet


def generate_scenario(maker_count: int = 8,
                      taker_count: int = 2,
                      tumbler_taker_count: int = 1,
                      round_count: int = 10,
                      block_count: int = 0):
    # Add standard taker wallets.
    for _ in range(taker_count):
        SCENARIO["wallets"].append(generate_wallet(
            "taker",
            funds_range=(100000, 5000000),
            min_offer_size=30000,
            max_offer_size=100000,
            counterparties_range=(4, 6)
        ))

    # Add tumbler_taker wallets, which include schedule options.
    for _ in range(tumbler_taker_count):
        SCENARIO["wallets"].append(generate_wallet(
            "tumbler_taker",
            funds_range=(100000, 5000000),
            min_offer_size=30000,
            max_offer_size=100000,
            counterparties_range=(4, 6)
        ))

    # Add maker wallets.
    for _ in range(maker_count):
        SCENARIO["wallets"].append(generate_wallet(
            "maker",
            funds_range=(500000, 10000000),
            min_offer_size=30000,
            max_offer_size=3000000,
            counterparties_range=(0, 0)  # Not relevant for makers
        ))


# Example usage:
generate_scenario(maker_count=30, taker_count=2, tumbler_taker_count=1)
print(SCENARIO)
