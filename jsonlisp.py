import json
import logging
import operator
from collections import ChainMap
import ast

logger = logging.getLogger(__name__)

Symbol = str
List = list
Number = (int, float)
Dict = dict


class Env(ChainMap):
    def __json__(self):
        return self.maps


class Proc:
    def __init__(self, params, body, env):
        self.params = params
        self.body = body
        self.env = env

    def __call__(self, *args):
        env = Env(dict(zip(self.params, args)), self.env)
        return interp(self.body, env)

    def __json__(self):
        return ["lambda", self.params, self.body]


class Macro:
    def __init__(self, params, body, env):
        self.params = params
        self.body = body
        self.env = env

    def expand(self, *args, env):
        static_env = Env(dict(zip(self.params, args)), self.env)
        exp = interp(self.body, static_env)
        return interp(exp, env)

    def __json__(self):
        return ["macro", self.params, self.body]


builtins = {
    # Operators
    "*": operator.mul,
    "+": operator.add,
    "-": operator.sub,
    "/": operator.truediv,
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
    ">": operator.gt,
    ">=": operator.ge,
    "^": operator.xor,
    "and": operator.and_,
    "contains": operator.contains,
    "in": lambda x, y: x in y,
    "is": operator.is_,
    "is-not": operator.is_not,
    "not": operator.not_,
    "or": operator.or_,
    "xor": lambda x, y: bool(x) ^ bool(y),  # logical XOR
    # Typechecks
    "dict?": lambda x: isinstance(x, Dict),
    "list?": lambda x: isinstance(x, List),
    "macro?": lambda x: isinstance(x, Macro),
    "null?": lambda x: x is None,
    "number?": lambda x: isinstance(x, Number),
    "proc?": callable,
    "symbol?": lambda x: isinstance(x, Symbol),
    # List functions
    "begin": lambda *x: x[-1],
    "cons": lambda x, y: [x, *y],
    "head": lambda x: x[0],
    "len": len,
    "list": lambda *x: list(x),
    "map": lambda *args: list(map(*args)),
    "range": lambda *x: list(range(*x)),
    "tail": lambda x: x[1:],
    # Dict functions
    "dict": lambda x: dict(x),
    "dict-del": lambda d, k: {_k: d[_k] for _k in d if k != _k},
    "dict-get": lambda d, k: d.get(k),
    "dict-items": lambda x: list(x.items()),
    "dict-set": lambda d, k, v: {**d, k: v},
    # Misc functions
    "apply": lambda proc, args: proc(*args),
    "print": print,
    "literal": ast.literal_eval,
    "str": str,
    "format": lambda x, *args: x % tuple(args),
}


std_lib = [
    "list",
    [
        "def",
        "defmacro",
        [
            "macro",
            ["name", "params", "body"],
            [
                "list",
                ["quote", "def"],
                "name",
                ["list", ["quote", "macro"], "params", "body"],
            ],
        ],
    ],
    [
        "defmacro",
        "defproc",
        ["name", "params", "body"],
        [
            "list",
            ["quote", "def"],
            "name",
            ["list", ["quote", "lambda"], "params", "body"],
        ],
    ],
]


def default_env():
    env = Env()
    env.update(builtins)
    env['key_up'] = "\x1b[A"
    env['key_down'] = "\x1b[B"
    env['key_right'] = "\x1b[C"
    env['key_left'] = "\x1b[D"
    env['key_home'] = "\x1b[H"
    env['key_end'] = "\x1b[F"
    env['key_ctrl_space'] = '\x00'
    env['key_escape'] = '\x1b'
    env['key_tab'] = '\t'
    env['key_enter'] = '\n'
    env['key_backspace'] = '\x7f'
    interp(std_lib, env)
    return env


def parse(line):
    return json.loads(line)


def parse_file(path):
    return json.load(path)


def unparse(expr):
    return json.dumps(expr, default=to_json)


def to_json(obj):
    if hasattr(obj, "__json__"):
        return obj.__json__()
    return repr(obj)


def interp(x, env):
    # a shortcut syntax for human readability
    if isinstance(x, Dict) and len(x) == 1:
        for k in x:
            v = x[k]
            if isinstance(v, List) or isinstance(v, Dict):
                v = interp(v, env)

            if not isinstance(v, List):
                v = [v]

            f = env[k]
            logger.info('CALL_STEP: %s %s' % (f.__name__, v))
            return f(*v)

    if isinstance(x, Symbol):
        if x.startswith('key_') and len(x) == 5:
            return x[4]
        return env[x]

    if not isinstance(x, List):
        return x

    if x == []:
        return x

    if x[0] == "quote" or x[0] == "'":
        _, exp = x
        return exp

    if x[0] == "flat_quote" or x[0] == "_'":
        _, *exp = x
        return exp

    if x[0] == "if":
        _, test, conseq, alt = x
        exp = conseq if interp(test, env) else alt
        return interp(exp, env)

    if x[0] == "def":
        _, var, exp = x
        val = env[var] = interp(exp, env)
        return val

    if x[0] == "lambda":
        _, params, body = x
        return Proc(params, body, env)

    if x[0] == "macro":
        _, params, body = x
        return Macro(params, body, env)

    proc_or_macro_exp, *args = x
    proc = interp(proc_or_macro_exp, env)
    if isinstance(proc, Macro):
        return proc.expand(*args, env=env)
    else:
        args = [interp(exp, env) for exp in args]
        if callable(proc):
            if proc_or_macro_exp != "begin":
                logger.info('CALL_STEP: %s(%s) %s' % (proc.__name__, proc_or_macro_exp, args))
        else:
            logger.error('CALL_STEP:ERROR: function not callable: %s(%s) %s' % (proc, proc_or_macro_exp, args))
        return proc(*args)

def repl(prompt=r"{λ}> "):
    env = default_env()

    while True:
        try:
            line = input(prompt)
            print(unparse(interp(parse(line), env)))
        except EOFError:
            print("Bye")
            break
        except Exception as err:
            print(repr(err))


def run_file(path):
    env = default_env()

    with open(path) as f:
        print(unparse(interp(parse_file(f), env)))
