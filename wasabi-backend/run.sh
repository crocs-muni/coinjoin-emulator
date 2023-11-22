#!/bin/bash
if [ -n "$ADDR_BTC_NODE" ]; then
    echo "$ADDR_BTC_NODE btc-node" >> /etc/hosts
fi
su wasabi -c ./WalletWasabi.Backend