#!/bin/bash

# Set default addresses if not provided by environment
if [ -z "$ADDR_BTC_NODE" ]; then
    export ADDR_BTC_NODE="btc-node"
fi
if [ -z "$ADDR_WASABI_BACKEND" ]; then
    export ADDR_WASABI_BACKEND="wasabi-backend"
fi
if [ -z "$ADDR_WASABI_COORDINATOR" ]; then
    export ADDR_WASABI_COORDINATOR="wasabi-coordinator"
fi

# Clean up any existing data
rm -rf /home/wasabi/.walletwasabi

printf '\n\n\nStarting WalletWasabi Daemon with CLI arguments...\n\n'

# Start WalletWasabi Daemon with all config passed as CLI arguments
dotnet run -p:NuGetAudit=false \
  --Network=RegTest \
  --MainNetBackendUri=https://api.wasabiwallet.io/ \
  --TestNetBackendUri=https://api.wasabiwallet.co/ \
  --RegTestBackendUri=http://${ADDR_WASABI_BACKEND}:37127/ \
  --MainNetCoordinatorUri=https://api.wasabiwallet.io/ \
  --TestNetCoordinatorUri=https://api.wasabiwallet.co/ \
  --RegTestCoordinatorUri=http://${ADDR_WASABI_COORDINATOR}:37128/ \
  --UseTor=Disabled \
  --TerminateTorOnExit=true \
  --DownloadNewVersion=false \
  --UseBitcoinRpc=true \
  --MainNetBitcoinRpcCredentialString="" \
  --TestNetBitcoinRpcCredentialString="" \
  --RegTestBitcoinRpcCredentialString=user:password \
  --MainNetBitcoinRpcEndPoint=127.0.0.1:8332 \
  --TestNetBitcoinRpcEndPoint=127.0.0.1:48332 \
  --RegTestBitcoinRpcEndPoint=${ADDR_BTC_NODE}:18443 \
  --JsonRpcServerEnabled=true \
  --JsonRpcUser="" \
  --JsonRpcPassword="" \
  --DustThreshold=0.00005 \
  --jsonrpcserverprefixes="http://*:37128/" \
  --EnableGpu=false \
  --CoordinatorIdentifier=CoinJoinCoordinatorIdentifier \
  --ExchangeRateProvider=MempoolSpace \
  --FeeRateEstimationProvider=none \
  --ExternalTransactionBroadcaster=MempoolSpace \
  --MaxCoinjoinMiningFeeRate=150 \
  --AbsoluteMinInputCount=2 \
  --LogLevel=trace