from typing import Optional, List
import os
import sys
import tty
import re
import signal
import logging
import threading

from qemu_compose.utils.zio import zio, select_ignoring_useless_signal, write_debug, ttyraw
from qemu_compose.utils.jsonlisp import interp, default_env


logger = logging.getLogger("qemu-compose.instance.terminal")


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
            raise Exception('qemu-compose.Terminal must run in a UNIX 98 style pty/tty')
        else:
            signal.signal(signal.SIGWINCH, self.handle_resize)

    def handle_resize(self, signum, frame):
        height, width = os.get_terminal_size(0)
        logger.info("try set terminal window size to %dx%d" % (width, height))
        # TODO: use qmp to set console window size

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
