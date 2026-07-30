#!/bin/bash

set -ex
rm -rf ./dist
uv build
sudo pip3 install --force-reinstall --break-system-packages --no-deps --upgrade ./dist/qemu_compose-*.whl
