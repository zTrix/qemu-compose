#!/usr/bin/env python3

import os
import sys
import logging

from pyte import ByteStream, Screen
from qemu.machine import QEMUMachine
from qemu.machine.machine import AbnormalShutdown

from zio import zio, TTY_RAW, TTY

class Terminal(Screen):
    def __init__(self, fd, log_path=None):
        self.fd = fd

        debug_file = open(log_path, "wb") if log_path else None
        self.io = zio(fd, debug=debug_file)


def run_archiso(iso_path, log_path=None):
    logging.basicConfig(level=logging.DEBUG)

    name = "arch"
    binary = "/usr/bin/qemu-system-x86_64"
    args = [
        "--enable-kvm",
        "-m", "4G",
        "-smp", "2",
        "-net", "nic,model=e1000e",
        "-net", "user,hostfwd=tcp:127.0.0.1:7022-:22,hostname=" + name,
        "--drive", "media=cdrom,file=%s,readonly=on" % iso_path,
        "-boot", "d",
    ]
    vm = QEMUMachine(binary, args=args, name=name)
    vm.set_machine("q35")
    vm.add_monitor_null()
    vm.set_qmp_monitor(True)
    vm.set_console(device_type='isa-serial')

    try:
        vm.launch()

        term = Terminal(vm._cons_sock_pair[1], log_path)

        term.batch(cmds)

        io.read_until(b"Boot the Arch Linux install medium on BIOS.")
        io.write(b"\t")
        io.read_until(b"initramfs-linux.img")
        io.write(b" console=ttyS0\n")

        io.read_until(b"[\x1b[0;32m  OK  \x1b[0m] Started \x1b[0;1;39mOpenSSH Daemon\x1b[0m.\r\r\n")

        tty_control_chars = b''

        io.print_read = False
        io.print_write = False

        tty_control_chars += io.read_until(b"\x1b[6n", keep=True)
        # report cursor position
        io.write(b"\x1b[47;1R\x1b[47;211R")

        tty_control_chars += io.read_until(b"\x1b[6n", keep=True)
        # report cursor position
        io.write(b"\x1b[47;1R\x1b[47;211R")

        tty_control_chars += io.read_until(b"\r\r\n", keep=False)

        io.print_read = True
        io.print_write = True

        print('[ TTY_CTRL_CHARS ]', tty_control_chars)

        io.read_until(b"archiso login: ")
        io.write(b"root\r\n")

        shell_prompt = b"\x00\x00\x1b[1m\x1b[31mroot\x1b[39m\x1b[0m\x00\x00@archiso \x1b[1m~ \x1b[0m\x00\x00# \x1b[K\x1b[?2004h"
        io.read_until(shell_prompt)

        io.read_until_timeout(0.1)
        # echoback will work
        io.print_write = False

        my_term_size = os.get_terminal_size()

        cmds = [
            b"stty rows %d" % my_term_size.lines,
            b"stty columns %d" % my_term_size.columns,
            b"sed -i -e 's|#PermitRootLogin prohibit-password|PermitRootLogin yes|g' /etc/ssh/sshd_config",
            b"echo _ | passwd root --stdin",
            b"systemctl restart sshd",
            b"echo 'Server = https://mirrors.tuna.tsinghua.edu.cn/archlinux/$repo/os/$arch' > /etc/pacman.d/mirrorlist",
            b"pacman -Sy"
        ]

        for cmd in cmds:
            io.write(cmd)
            io.read_until_timeout(0.1)
            io.write(b'\r\n')
            io.read_until(shell_prompt)

        tty_control_chars_without_cursor_report = tty_control_chars.replace(b'\x1b[6n', b'')
        io.interactive(raw_mode=True, buffered=tty_control_chars_without_cursor_report)
        if io.is_eof_seen():
            print('vm.is_running = ', vm.is_running())
    except KeyboardInterrupt:
        print("Keyboard interrupt, shutting down vm...")
    finally:
        try:
            if vm.is_running():
                vm.shutdown(hard=True)
        except AbnormalShutdown:
            print('[ EE ] abnormal shutdown exception')
        finally:
            vm._load_io_log()
            print('vm.process_io_log = %r' % (vm.get_log(), ))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('%s /path/to/your-arch-iso' % sys.argv[0])
        sys.exit()
    run_archiso(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
