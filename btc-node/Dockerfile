FROM ruimarinho/bitcoin-core:23-alpine
RUN apk add curl jq
USER 100:101
COPY --chown=100:101 bitcoin.conf /home/bitcoin/.bitcoin/bitcoin.conf
COPY --chown=100:101 mine.sh /home/bitcoin/mine.sh
COPY --chown=100:101 run.sh /home/bitcoin/run.sh
RUN mkdir /home/bitcoin/data
WORKDIR /home/bitcoin
CMD ["./run.sh"]
