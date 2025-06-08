#!/bin/bash

set -ex

args=(
  --enable-kvm
  -vga std
  -monitor stdio
  -m 4G
  -smp 2
  -net nic,model=e1000e
  -net user,hostfwd=tcp:127.0.0.1:7022-:22,hostname=arch
  --drive media=cdrom,file=archlinux-2025.06.01-x86_64.iso,readonly=on
  -boot d
)

qemu-system-x86_64 "${args[@]}"
