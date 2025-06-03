#!/usr/bin/env python3
from typing import List, Optional, Any
import os
import sys
import logging

from pyte import ByteStream, Screen
from qemu.machine import QEMUMachine
from qemu.machine.machine import AbnormalShutdown

from zio import zio, TTY_RAW, TTY, write_debug

class MyStream(ByteStream):

    def __init__(self, *args: Any, **kwargs: Any):
        ByteStream.__init__(self, *args, **kwargs)
        self.select_other_charset('@')

        self.cursor_pos = None

    def write(self, buf:bytes):
        self.feed(buf)

        new_pos = (self.listener.cursor.y, self.listener.cursor.x)

        if new_pos != self.cursor_pos:
            self.listener.render_to(sys.stderr)
            self.cursor_pos = new_pos

    def flush(self):
        pass

class Terminal(Screen):
    def __init__(self, fd, log_path=None):
        Screen.__init__(self, 80, 24)

        self.fd = fd

        self.stream = MyStream()

        self.debug_file = open(log_path, "wb") if log_path else None
        self.io = zio(fd, print_write=False, logfile=self.stream, debug=self.debug_file)

        self.stream.attach(self)

    def render_to(self, target=None, clear_screen=True):
        if target is None:
            target = sys.stderr

        if clear_screen:
            target.write(b"\33[H\33[2J\33[3J".decode('latin-1'))

        for y in range(self.cursor.y):
            line = self.buffer[y]

            if y < self.cursor.y:
                for x in range(self.columns):
                    if line[x].data:
                        target.write(line[x].data[0])
                target.write('\r\n')
            else:
                for x in range(self.cursor.x):
                    if line[x].data:
                        target.write(line[x].data[0])

        target.flush()

    def write_process_input(self, data: str) -> None:
        v = data.encode('latin-1')
        self.io.write(v)
        if self.debug_file:
            write_debug(self.debug_file, b'write_process_input: %r -> %r' % (data, v))

    def run_batch(self, ops:List):
        io = self.io
        io.read_until(b"Boot the Arch Linux install medium on BIOS.")
        io.write(b"\t")
        io.read_until(b"initramfs-linux.img")
        io.write(b" console=ttyS0\n")

        io.read_until(b"archiso login: ")
        io.write(b"root\r\n")

        shell_prompt = b"\x00\x00\x1b[1m\x1b[31mroot\x1b[39m\x1b[0m\x00\x00@archiso \x1b[1m~ \x1b[0m\x00\x00# \x1b[K\x1b[?2004h"
        io.read_until(shell_prompt)

    def interact(self, buffered:Optional[bytes]=None):
        self.io.interactive(raw_mode=True, buffered=buffered)

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

        term.run_batch([])

        term.interact()

        # my_term_size = os.get_terminal_size()

        # cmds = [
        #     b"stty rows %d" % my_term_size.lines,
        #     b"stty columns %d" % my_term_size.columns,
        #     b"sed -i -e 's|#PermitRootLogin prohibit-password|PermitRootLogin yes|g' /etc/ssh/sshd_config",
        #     b"echo _ | passwd root --stdin",
        #     b"systemctl restart sshd",
        #     b"echo 'Server = https://mirrors.tuna.tsinghua.edu.cn/archlinux/$repo/os/$arch' > /etc/pacman.d/mirrorlist",
        #     b"pacman -Sy"
        # ]

        # for cmd in cmds:
        #     io.write(cmd)
        #     io.read_until_timeout(0.1)
        #     io.write(b'\r\n')
        #     io.read_until(shell_prompt)

        # tty_control_chars_without_cursor_report = tty_control_chars.replace(b'\x1b[6n', b'')
        # io.interactive(raw_mode=True, buffered=tty_control_chars_without_cursor_report)
        # if io.is_eof_seen():
        #     print('vm.is_running = ', vm.is_running())
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
