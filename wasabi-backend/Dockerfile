FROM mcr.microsoft.com/dotnet/sdk:7.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
COPY wasabi-src /wasabi-src
WORKDIR /wasabi-src/WalletWasabi.Backend
RUN dotnet build -c Release

# FROM mcr.microsoft.com/dotnet/runtime:7.0 # Missing ASP.NET Core
FROM mcr.microsoft.com/dotnet/aspnet:7.0
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1
RUN apt update && apt install -y curl
COPY --from=0 /wasabi-src/WalletWasabi.Backend/bin/Release/net7.0 /wasabi
COPY Config.json /root/.walletwasabi/backend/
COPY run.sh /wasabi
WORKDIR /wasabi
CMD ["./run.sh"]
