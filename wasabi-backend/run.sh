#!/bin/bash
if [ -z "$ADDR_BTC_NODE" ]; then
    export ADDR_BTC_NODE="btc-node"
fi
mkdir -p /home/wasabi/.walletwasabi/backend
( echo "cat <<EOF" ; cat /home/wasabi/Config.json ; echo EOF ) | sh > /home/wasabi/.walletwasabi/backend/Config.json
./WalletWasabi.Backend