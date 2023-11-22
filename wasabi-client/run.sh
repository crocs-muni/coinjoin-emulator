#!/bin/bash
if [ -n "$ADDR_BTC_NODE" ]; then
    echo "$ADDR_BTC_NODE btc-node" >> /etc/hosts
fi
if [ -n "$ADDR_WASABI_BACKEND" ]; then
    echo "$ADDR_WASABI_BACKEND wasabi-backend" >> /etc/hosts
fi
su wasabi -c ./WalletWasabi.Daemon