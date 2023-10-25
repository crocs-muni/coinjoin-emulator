FROM ruimarinho/bitcoin-core:23-alpine
COPY bitcoin.conf /home/bitcoin/.bitcoin/bitcoin.conf
COPY mine.sh /home/bitcoin/mine.sh
COPY run.sh /home/bitcoin/run.sh
RUN apk add curl jq
WORKDIR /home/bitcoin
CMD ["./run.sh"]
