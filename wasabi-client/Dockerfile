FROM mcr.microsoft.com/dotnet/sdk:7.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN apt update && apt install -y patch

COPY wasabi-src /wasabi-src
COPY logger.patch /wasabi-src/logger.patch
WORKDIR /wasabi-src
RUN patch -p1 < logger.patch

WORKDIR /wasabi-src/WalletWasabi.Daemon
RUN dotnet build -c Release

# FROM mcr.microsoft.com/dotnet/runtime:7.0 # Missing ASP.NET Core
FROM mcr.microsoft.com/dotnet/aspnet:7.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN useradd -ms /bin/sh wasabi
USER wasabi
WORKDIR /home/wasabi
COPY --from=0 /wasabi-src/WalletWasabi.Daemon/bin/Release/net7.0 /home/wasabi/
COPY --chown=wasabi:wasabi Config.json /home/wasabi/.walletwasabi/client/
CMD ["./WalletWasabi.Daemon"]
