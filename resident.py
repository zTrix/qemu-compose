#!/usr/bin/env python3

import sys
import logging

from qemu.machine import QEMUMachine

from zio import zio, TTY_RAW, TTY

def main():
    logging.basicConfig(level=logging.DEBUG)

    name = "arch"
    binary = "/usr/bin/qemu-system-x86_64"
    args = [
        "--enable-kvm",
        "-m", "4G",
        "-smp", "2",
        "-net", "nic,model=e1000e",
        "-net", "user,hostfwd=tcp:127.0.0.1:7022-:22,hostname=" + name,
        "--drive", "media=cdrom,file=/home/ztx/vm/arch/archlinux-2025.05.01-x86_64.iso,readonly=on",
        "-boot", "d",
    ]
    vm = QEMUMachine(binary, args=args, name=name)
    vm.set_machine("q35")
    vm.add_monitor_null()
    vm.set_qmp_monitor(True)
    vm.set_console(device_type='isa-serial')

    vm.launch()

    vm._cons_sock_pair[1].setblocking(False)
    io = zio(vm._cons_sock_pair[1])
    io.interactive(raw_mode=True)

if __name__ == '__main__':
    main()
