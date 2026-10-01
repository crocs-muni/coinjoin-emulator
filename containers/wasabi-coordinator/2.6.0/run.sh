#!/bin/bash
if [ -z "$ADDR_BTC_NODE" ]; then
    export ADDR_BTC_NODE="btc-node"
fi

export WASABI_BIND="http://0.0.0.0:37128"


echo "Wasabi binding to $WASABI_BIND"
echo $WASABI_BIND
rm -rf /home/wasabi/.walletwasabi
mkdir -p /home/wasabi/.walletwasabi/coordinator

( echo "cat <<EOF" ; cat /home/wasabi/Config.json ; echo EOF ) | sh > /home/wasabi/.walletwasabi/coordinator/Config.json

sleep 15

./WalletWasabi.Coordinator --loglevel=trace
