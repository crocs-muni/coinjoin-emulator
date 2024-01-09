#!/bin/sh
until [ -f /tmp/bitcoin-main ]
do
    echo "Waiting for bitcoin-main IP to be provided..."
    sleep 1
done
export BTC_MAIN=$(cat /tmp/bitcoin-main)
( echo "cat <<EOF" ; cat /home/bitcoin/bitcoin.conf ; echo EOF ) | sh > /home/bitcoin/.bitcoin/bitcoin.conf
bitcoind -conf=/home/bitcoin/.bitcoin/bitcoin.conf -datadir=/home/bitcoin/data -printtoconsole