import btc_node
import wasabi_node
from time import sleep

BTC = 100_000_000


def fund_distributor(btc_amount):
    wasabi_node.create_wallet("distributor")
    wasabi_node.wait_wallet("distributor")
    btc_node.fund_address(wasabi_node.get_new_address("distributor"), btc_amount)
    btc_node.mine_block()
    while wasabi_node.get_balance("distributor") < btc_amount * BTC:
        sleep(0.1)


def fund_wallets(invoices):
    for wallet, _ in invoices:
        print(f"Creating wallet {wallet}")
        wasabi_node.create_wallet(wallet)
        wasabi_node.wait_wallet(wallet)

    addressed_invoices = [
        (wasabi_node.get_new_address(wallet), amount) for wallet, amount in invoices
    ]

    print("Creating wallet-funding transaction")
    wasabi_node.send("distributor", addressed_invoices)
    btc_node.mine_block()

    print("Waiting for funds propagation")
    for wallet, target_value in invoices:
        while wasabi_node.get_balance(wallet) < target_value:
            sleep(0.1)


if __name__ == "__main__":
    print("Funding distributor")
    fund_distributor(30)
    print("Funding wallets")
    fund_wallets([("alice", BTC), ("bob", 2 * BTC), ("charlie", int(0.5 * BTC))])
    print("Funding finished")
