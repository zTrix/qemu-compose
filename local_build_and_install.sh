#!/bin/bash

set -ex
rm -rf ./dist
uv build
sudo pip install --force-reinstall --break-system-packages --no-deps ./dist/qemu_compose-*.whl
