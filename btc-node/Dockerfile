FROM ruimarinho/bitcoin-core:23-alpine
COPY bitcoin.conf /home/bitcoin/.bitcoin/bitcoin.conf
RUN apk add curl
CMD ["bitcoind", "-conf=/home/bitcoin/.bitcoin/bitcoin.conf", "-datadir=/home/bitcoin/.bitcoin", "-printtoconsole"]
