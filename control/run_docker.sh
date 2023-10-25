#!/bin/bash

rm -rf ../mounts/backend/*
cp ../wasabi-backend/Config.json ../mounts/backend/
cp ../wasabi-backend/WabiSabiConfig.json ../mounts/backend/

docker compose up
docker compose down

mkdir -p "../out/$(date +%Y-%m-%d_%H-%M-%S)/"
cp -r ../mounts/backend/ "../out/$(date +%Y-%m-%d_%H-%M-%S)/"