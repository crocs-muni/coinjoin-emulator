FROM mcr.microsoft.com/dotnet/sdk:7.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN apt update && apt install -y patch

RUN mkdir -p /wasabi-src
WORKDIR /wasabi-src
RUN git clone https://github.com/zkSNACKs/WalletWasabi.git .
RUN git checkout v2.0.4

COPY logger.patch /wasabi-src/logger.patch
RUN patch --binary -p1 < logger.patch

WORKDIR /wasabi-src/WalletWasabi.Backend
RUN dotnet build -c Release

# FROM mcr.microsoft.com/dotnet/runtime:7.0 # Missing ASP.NET Core
FROM mcr.microsoft.com/dotnet/aspnet:7.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN apt update && apt install -y curl
RUN useradd -ms /bin/sh wasabi
# Needs to be numeric for kubernetes security context
USER 1000:1000
COPY --from=0 --chown=wasabi:wasabi /wasabi-src/WalletWasabi.Backend/bin/Release/net7.0 /home/wasabi/
COPY --chown=wasabi:wasabi Config.json /home/wasabi/
COPY --chown=wasabi:wasabi run.sh /home/wasabi/
WORKDIR /home/wasabi
CMD ["./run.sh"]
