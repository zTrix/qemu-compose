#!/usr/bin/env python3

import ast
import sys
import socket
from zio import zio

def parse(log_path:str):
    buf = [bytearray(), bytearray()]
    ret = []

    for line in open(log_path):
        if 'IO.recv(' in line:
            if buf[1]:
                ret.append((1, bytes(buf[1])))
                buf[1] = bytearray()
            i = line.index(' -> ')
            content = line[i+4:-1].strip()
            assert (content.startswith('b"') and content.endswith('"')) or (content.startswith("b'") and content.endswith("'"))
            buf[0].extend(ast.literal_eval(content))
        elif 'IO.send(' in line:
            if buf[0]:
                ret.append((0, bytes(buf[0])))
                buf[0] = bytearray()
            i = line.index(' -> ')
            content = line[i+4:-1].strip()
            assert (content.startswith('b"') and content.endswith('"')) or (content.startswith("b'") and content.endswith("'"))
            buf[1].extend(ast.literal_eval(content))
        else:
            continue

    if buf[0]:
        ret.append((0, bytes(buf[0])))
    if buf[1]:
        ret.append((1, bytes(buf[1])))
    return ret

def serve(logs, addr=None):
    server = socket.socket()
    if addr is None:
        addr = ('0.0.0.0', 1111)
    server.bind(addr)
    server.listen(1)
    s, _ = server.accept()
    io = zio(s, print_read=False, print_write=False, timeout=3600)
    for d, c in logs:
        if d == 1:
            print('EXPECT', c)
            io.read_until(c)
        else:
            print('SEND', c)
            io.write(c)
    io.close()

def main(name, log_path):
    logs = parse(log_path)
    if name == 'parse':
        for direction, content in logs:
            print('<<<<----' if direction else '---->>>>', content)
    elif name == 'serve':
        serve(logs)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
