#!/usr/bin/env python3
from typing import List, Optional, Any
import os
import sys
import yaml
import logging
import shutil

from pyte import ByteStream, Screen
from qemu.machine import QEMUMachine
from qemu.machine.machine import AbnormalShutdown

from zio import zio, TTY_RAW, TTY, write_debug

class MyStream(ByteStream):

    def __init__(self, *args: Any, debug=None, **kwargs: Any):
        self.debug_file = debug

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

    def debug(self, *args, **kwargs):
        if self.debug_file:
            write_debug(self.debug_file, b'MyStream.unknown_escape_sequence(%r, %r)' % (args, kwargs))

class Terminal(Screen):
    def __init__(self, fd, log_path=None):
        Screen.__init__(self, 80, 24)

        self.fd = fd

        self.debug_file = open(log_path, "wb") if log_path else None

        self.stream = MyStream(debug=self.debug_file)
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

        my_term_size = os.get_terminal_size()

        self.resize(my_term_size.lines, my_term_size.columns)

        cmds = [
            b"stty rows %d cols %d" % (my_term_size.lines, my_term_size.columns),
            b"sed -i '/#PermitRootLogin/c\PermitRootLogin yes' /etc/ssh/sshd_config",
            b"sed -i '/#PasswordAuthentication/c\PasswordAuthentication yes' /etc/ssh/sshd_config",
            b"echo _ | passwd root --stdin",
            b"systemctl restart sshd",
            b"echo 'Server = https://mirrors.tuna.tsinghua.edu.cn/archlinux/$repo/os/$arch' > /etc/pacman.d/mirrorlist",
        ]

        for cmd in cmds:
            io.write(cmd)
            io.read_until_timeout(0.1)
            io.write(b'\r\n')
            io.read_until(shell_prompt)

    def interact(self, buffered:Optional[bytes]=None):
        self.io.interactive(raw_mode=True, buffered=buffered)

def run(config_path, log_path=None, env_update=None):
    logging.basicConfig(level=logging.DEBUG)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    name = config.get('name')

    binary = config.get('binary', shutil.which('qemu-system-x86_64'))
    if not binary:
        raise Exception('qemu binary not found')

    default_env = {
        'PWD': os.path.normpath(os.path.dirname(config_path)),
    }

    if env_update:
        default_env.update(env_update)

    default_args = {
        'cpu': 'max',
        'machine': 'type=q35,accel=kvm:tcg',
        'm': '1G',
        'smp': '1',
    }

    for block in config.get('args'):
        for key in block:
            # FIXME: format has security issues
            val = block[key].format(**default_env) if block[key] else None
            if key in default_args:
                default_args[key] = val

    args = []
    for key in default_args:
        args.append('-' + key)
        args.append(default_args[key])

    for block in config.get('args'):
        for key in block:
            val = block[key].format(**default_env) if block[key] else None
            if key in default_args:
                continue
            args.append('-' + key)
            if val is not None:
                args.append(val)

    vm = QEMUMachine(binary, args=args, name=name)
    vm.add_monitor_null()
    vm.set_qmp_monitor(True)
    vm.set_console(device_type='isa-serial')

    try:
        vm.launch()

        term = Terminal(vm._cons_sock_pair[1], log_path)

        # term.run_batch([])

        term.interact()
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
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
