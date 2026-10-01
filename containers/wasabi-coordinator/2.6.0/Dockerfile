FROM mcr.microsoft.com/dotnet/sdk:8.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN apt update && apt install -y patch

RUN mkdir -p /wasabi-src
WORKDIR /wasabi-src
RUN git clone https://github.com/WalletWasabi/WalletWasabi.git .
RUN git checkout v2.6.0

COPY logger.patch /wasabi-src/logger.patch
RUN patch --binary -p1 < logger.patch

COPY mining_fee_rate.patch /wasabi-src/mining_fee_rate.patch
RUN patch --binary -p1 < mining_fee_rate.patch

WORKDIR /wasabi-src/WalletWasabi.Coordinator
RUN dotnet build -c Release

# FROM mcr.microsoft.com/dotnet/runtime:8.0 # Missing ASP.NET Core
FROM mcr.microsoft.com/dotnet/aspnet:8.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN apt update && apt install -y curl
RUN useradd -u 1000 -ms /bin/sh wasabi
# Needs to be numeric for kubernetes security context
USER 1000:1000
COPY --from=0 --chown=wasabi:wasabi /wasabi-src/WalletWasabi.Coordinator/bin/Release/net8.0 /home/wasabi/
COPY --chown=wasabi:wasabi appsettings.json /home/wasabi/
COPY --chown=wasabi:wasabi Config.json /home/wasabi/Config.json
COPY --chown=wasabi:wasabi run.sh /home/wasabi/
WORKDIR /home/wasabi
CMD ["./run.sh"]
