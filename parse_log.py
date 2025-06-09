#!/usr/bin/env python3

import ast
import sys

buf = [b'', b'']

for line in open(sys.argv[1]):
    if 'IO.recv(' in line:
        if buf[1]:
            print('>', buf[1])
            buf[1] = b''
        i = line.index(' -> ')
        content = line[i+4:-1].strip()
        assert (content.startswith('b"') and content.endswith('"')) or (content.startswith("b'") and content.endswith("'"))
        buf[0] += ast.literal_eval(content)
    elif 'IO.send(' in line:
        if buf[0]:
            print('<', buf[0])
            buf[0] = b''
        i = line.index(' -> ')
        content = line[i+4:-1].strip()
        assert (content.startswith('b"') and content.endswith('"')) or (content.startswith("b'") and content.endswith("'"))
        buf[1] += ast.literal_eval(content)
    else:
        continue

if buf[0]:
    print('<', buf[0])
if buf[1]:
    print('>', buf[1])
