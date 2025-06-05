#!/usr/bin/env python3

import ast
import sys

buf = [b'', b'']

for line in open(sys.argv[1]):
    if 'SocketIO.recv(' in line:
        if buf[1]:
            print('>', buf[1])
            buf[1] = b''
        i = line.index(' -> ')
        buf[0] += ast.literal_eval(line[i+4:-1])
    elif 'SocketIO.send(' in line:
        if buf[0]:
            print('<', buf[0])
            buf[0] = b''
        i = line.index(' -> ')
        buf[1] += ast.literal_eval(line[i+4:-1])
    else:
        continue

if buf[0]:
    print('<', buf[0])
if buf[1]:
    print('>', buf[1])
