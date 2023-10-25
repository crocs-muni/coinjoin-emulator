import btc_node
import wasabi_client
from time import sleep
import random

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
        print(f"Creating wallet {wallet}")
        wasabi_client.create_wallet(wallet)
        wasabi_client.wait_wallet(wallet)

    addressed_invoices = [
        (wasabi_client.get_new_address(wallet), amount) for wallet, amount in invoices
    ]

    print("Creating wallet-funding transaction")
    wasabi_client.send("distributor", addressed_invoices)
    btc_node.mine_block()

    print("Waiting for funds propagation")
    for wallet, target_value in invoices:
        while wasabi_client.get_balance(wallet) < target_value:
            sleep(0.1)


if __name__ == "__main__":
    wallets = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    print("Funding distributor")
    fund_distributor(30)
    print("Funding wallets")
    invoices = list(
        zip(
            wallets,
            [int(random.random() * BTC * 0.001 + BTC) for _ in range(26)],
        )
    )
    fund_wallets(invoices)
    print("Funding finished")

    sleep(10)

    print("Starting coinjoins")
    for wallet in wallets:
        wasabi_client.start_coinjoin(wallet)
    print("Coinjoins started")
