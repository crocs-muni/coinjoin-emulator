#!/bin/sh
./mine.sh &
bitcoind -conf=/home/bitcoin/.bitcoin/bitcoin.conf -datadir=/home/bitcoin/data -printtoconsole