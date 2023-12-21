#!/bin/sh

sleep 1 # TODO make more robust by waiting for bitcoind to be ready

BLOCK_COUNT=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getblockcount", "params": []}' -H 'content-type: text/plain;' http://localhost:18443 | jq ".result")

if [ "$BLOCK_COUNT" == "0" ]
then
    curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "createwallet", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 > /dev/null

    # Mine first 200 blocks
    ADDR=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getnewaddress", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 | jq -r '.result')
    curl -s -u user:password --data-binary "{\"jsonrpc\": \"2.0\", \"method\": \"generatetoaddress\", \"params\": [201, \"$ADDR\"]}" -H 'content-type: text/plain;' http://localhost:18443 > /dev/null
fi

# Mine new block periodically
while true
do
    sleep $(($RANDOM % 60 + 30))
    ADDR=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getnewaddress", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 | jq -r '.result')
    curl -s -u user:password --data-binary "{\"jsonrpc\": \"2.0\", \"method\": \"generatetoaddress\", \"params\": [1, \"$ADDR\"]}" -H 'content-type: text/plain;' http://localhost:18443 > /dev/null
done
