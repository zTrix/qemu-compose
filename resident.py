#!/usr/bin/env python3
from typing import List, Optional
import os
import re
import sys
import yaml
import logging
import shutil
import threading
import tty
import subprocess
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from qemu.machine import QEMUMachine
from qemu.machine.machine import AbnormalShutdown
from jsonlisp import default_env, interp

from zio import zio, write_debug, select_ignoring_useless_signal, ttyraw

logger = logging.getLogger("resident")

class HttpServer:
    def __init__(self, listen:str, port:int, root:str):
        self.listen = listen
        self.port = port
        self.root = root

    def start(self):
        http_handler = partial(SimpleHTTPRequestHandler, directory=self.root)
        server = ThreadingHTTPServer((self.listen, self.port), http_handler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

class StreamWrapper:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        return getattr(self.obj, name)

    def write(self, s):
        if isinstance(s, str):
            s = s.encode()
        self.obj.write(s)

class Terminal(object):
    def __init__(self, fd, log_path=None):
        self.fd = fd

        if isinstance(log_path, str):
            self.debug_file = open(log_path, "wb") if log_path else None
        else:
            self.debug_file = log_path

        self.io = zio(fd, print_write=False, logfile=sys.stdout, debug=self.debug_file, timeout=3600)

        self.term_feed_running = False
        self.term_feed_drain_thread = None

        if not os.isatty(0):
            raise Exception('resident.Terminal must run in a UNIX 98 style pty/tty')

    def term_feed_loop(self):
        logger.info('Terminal.term_feed_loop started...')
        while self.term_feed_running:
            r, _, _ = select_ignoring_useless_signal([0], [], [], 0.2)

            if 0 in r:
                data = os.read(0, 1024)
                if data:
                    logger.info('Terminal.term_feed_loop received(%d) -> %s' % (len(data), data))
                    self.io.write(data)

        logger.info('Terminal.term_feed_loop finished.')

    def run_batch(self, cmds:List, env_variables=None):
        if not isinstance(cmds, list):
            raise ValueError("cmds must be a list")
        
        current_tty_mode = tty.tcgetattr(0)[:]
        ttyraw(0)

        try:
            self.term_feed_running = True
            self.term_feed_drain_thread = threading.Thread(target=self.term_feed_loop)
            self.term_feed_drain_thread.daemon = True
            self.term_feed_drain_thread.start()
            
            io = self.io

            if self.debug_file:
                write_debug(self.debug_file, b'run_batch: cmds = %r' % cmds)

            transpiled_cmds = ['begin'] + cmds

            env = default_env()

            env['read_until'] = io.read_until
            env['write'] = io.write
            env['writeline'] = io.writeline
            env['wait'] = io.read_until_timeout
            env['RegExp'] = lambda x: re.compile(x.encode())
            env['interact'] = self.interact

            if env_variables:
                env.update(env_variables)

            interp(transpiled_cmds, env)

        finally:
            tty.tcsetattr(0, tty.TCSAFLUSH, current_tty_mode)

    def interact(self, buffered:Optional[bytes]=None, raw_mode=False):

        self.term_feed_running = False
        if self.term_feed_drain_thread is not None:
            self.term_feed_drain_thread.join()

        self.io.interactive(raw_mode=raw_mode, buffered=buffered)

def extract_format_or_default(mapping:dict, key:str, env:dict, default=None):
    value = mapping.get(key) if mapping else key
    if value:
        # FIXME: format has security issues
        return str(value).format(**env)
    return default

def run(config_path, log_path=None, env_update=None):

    if log_path:
        debug_file = open(log_path, "wb")
        logging.basicConfig(level=logging.DEBUG, stream=StreamWrapper(debug_file))
    else:
        debug_file = None

    config: dict
    with open(config_path) as f:
        config = yaml.safe_load(f)

    name = config.get('name')

    binary = config.get('binary', shutil.which('qemu-system-x86_64'))
    if not binary:
        raise Exception('qemu binary not found')
    
    cwd = os.path.normpath(os.path.dirname(config_path))
    term_size = os.get_terminal_size()

    env = {
        'CWD': cwd,
        'GATEWAY_IP': '10.0.2.2',   # qemu user network default gateway ip
        'TERM_ROWS': term_size.lines,
        'TERM_COLS': term_size.columns,
    }

    if config.get('env'):
        for k in config.get('env'):
            env[k] = config.get('env')[k]

    os.chdir(env['CWD'])
    
    http_port = None
    if config.get('http_serve'):
        http_serve_config:dict = config.get('http_serve')
        http_listen = extract_format_or_default(http_serve_config, 'listen', env, default='0.0.0.0')
        http_port = int(extract_format_or_default(http_serve_config, 'port', env, default=8888))
        http_root = extract_format_or_default(http_serve_config, 'root', env, default=env['CWD'])

        http_server = HttpServer(http_listen, http_port, http_root)
        http_server.start()
        logger.info('HTTP server started on %s:%d, serving %s' % (http_listen, http_port, http_root))

    if http_port is not None:
        env['HTTP_PORT'] = http_port
        access_ip = extract_format_or_default(config.get('http_serve'), 'access_ip', env, default=env['GATEWAY_IP']) if config.get('http_serve') else env['GATEWAY_IP']
        env['HTTP_HOST'] = access_ip

    if env_update:
        env.update(env_update)

    if config.get('before_script'):
        for line in config.get('before_script'):
            command = extract_format_or_default(None, line, env)
            if command:
                subprocess.run(command.strip(), shell=True, check=True)

    default_args = {
        'cpu': 'max',
        'machine': 'type=q35',
        'accel': 'kvm:tcg',
        'm': '1G',
        'smp': '1',
    }

    for block in config.get('args'):
        for key in block:
            val = extract_format_or_default(block, key, env)
            if key in default_args:
                default_args[key] = val

    args = []
    for key in default_args:
        args.append('-' + key)
        args.append(default_args[key])

    for block in config.get('args'):
        for key in block:
            val = extract_format_or_default(block, key, env)
            if key in default_args:
                continue
            args.append('-' + key)
            if val is not None:
                args.append(val)

    vm = QEMUMachine(binary, args=args, name=name)
    vm.add_monitor_null()
    vm.set_qmp_monitor(True)
    vm.set_console(console_chardev='socket', device_type='isa-serial')

    try:
        vm.launch()

        term = Terminal(vm.console_file, debug_file)

        boot_commands = config.get('boot_commands')
        if boot_commands:
            term.run_batch(boot_commands, env_variables=env)
        else:
            term.interact(raw_mode=True)

        if config.get('after_script'):
            for line in config.get('after_script'):
                command = extract_format_or_default(None, line, env)
                if command:
                    subprocess.run(command.strip(), shell=True, check=True)

    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt, shutting down vm...")
    finally:
        try:
            if vm.is_running():
                vm.shutdown(hard=True)
        except AbnormalShutdown:
            logger.error('abnormal shutdown exception')
        finally:
            vm._load_io_log()
            logger.info('vm.process_io_log = %r' % (vm.get_log(), ))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('%s /path/to/your-config-file [output-log-path]' % sys.argv[0])
        sys.exit()
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
