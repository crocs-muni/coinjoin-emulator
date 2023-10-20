#!/bin/sh

# Create wallet if it doesn't exist
RESULT=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getblockcount", "params": []}' -H 'content-type: text/plain;' http://btc-node:18443)
if [ "$RESULT" = '{"result":0,"error":null,"id":null}' ] # TODO make more robust?
then
    curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "createwallet", "params": ["wallet"]}' -H 'content-type: text/plain;' http://btc-node:18443 > /dev/null
fi

# Start backend
./WalletWasabi.Backend
