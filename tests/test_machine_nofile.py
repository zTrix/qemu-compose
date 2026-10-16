from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from qemu_compose.qemu.machine import machine

TARGET = machine.QEMU_NOFILE_SOFT_LIMIT
RLIMIT_NOFILE = machine.resource.RLIMIT_NOFILE


# ---------------------------------------------------------------------------
# Unit tests for the preexec helper
# ---------------------------------------------------------------------------

def test_no_change_when_soft_limit_already_sufficient(monkeypatch):
    calls = []
    monkeypatch.setattr(machine.resource, "getrlimit", lambda res: (TARGET, TARGET))
    monkeypatch.setattr(machine.resource, "setrlimit", lambda *a: calls.append(a))

    machine._raise_nofile_limit()

    assert calls == []


def test_no_change_when_soft_limit_is_infinity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        machine.resource, "getrlimit",
        lambda res: (machine.resource.RLIM_INFINITY, machine.resource.RLIM_INFINITY),
    )
    monkeypatch.setattr(machine.resource, "setrlimit", lambda *a: calls.append(a))

    machine._raise_nofile_limit()

    assert calls == []


def test_raises_soft_and_hard_to_target(monkeypatch):
    calls = []
    monkeypatch.setattr(machine.resource, "getrlimit", lambda res: (1024, TARGET))
    monkeypatch.setattr(machine.resource, "setrlimit",
                        lambda res, lim: calls.append((res, lim)))

    machine._raise_nofile_limit()

    assert calls == [(RLIMIT_NOFILE, (TARGET, TARGET))]


def test_falls_back_to_hard_limit_when_unprivileged(monkeypatch):
    calls = []

    def fake_setrlimit(res, lim):
        calls.append((res, lim))
        if lim == (TARGET, TARGET):
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(machine.resource, "getrlimit", lambda res: (1024, 4096))
    monkeypatch.setattr(machine.resource, "setrlimit", fake_setrlimit)

    machine._raise_nofile_limit()

    assert calls == [
        (RLIMIT_NOFILE, (TARGET, TARGET)),
        (RLIMIT_NOFILE, (4096, 4096)),
    ]


def test_uses_existing_hard_limit_when_above_target(monkeypatch):
    calls = []
    hard = TARGET + 4096

    def fake_setrlimit(res, lim):
        calls.append((res, lim))
        if lim == (TARGET, TARGET):
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(machine.resource, "getrlimit", lambda res: (1024, hard))
    monkeypatch.setattr(machine.resource, "setrlimit", fake_setrlimit)

    machine._raise_nofile_limit()

    assert calls == [
        (RLIMIT_NOFILE, (TARGET, TARGET)),
        (RLIMIT_NOFILE, (TARGET, hard)),
    ]


def test_setrlimit_failure_is_swallowed(monkeypatch):
    def boom(*args):
        raise OSError(1, "nope")

    monkeypatch.setattr(machine.resource, "getrlimit", lambda res: (1024, 4096))
    monkeypatch.setattr(machine.resource, "setrlimit", boom)

    # Must not raise: a failed limit change must not prevent QEMU from starting.
    machine._raise_nofile_limit()


def test_getrlimit_failure_is_swallowed(monkeypatch):
    def boom(res):
        raise OSError(1, "nope")

    monkeypatch.setattr(machine.resource, "getrlimit", boom)

    machine._raise_nofile_limit()


# ---------------------------------------------------------------------------
# Wiring test: _launch must pass the helper as preexec_fn
# ---------------------------------------------------------------------------

def test_launch_passes_nofile_preexec_fn(monkeypatch, tmp_path):
    vm = machine.QEMUMachine(binary="/bin/true", log_dir=str(tmp_path))

    def fake_pre_launch():
        vm._qemu_full_args = ("/bin/true",)
        vm._qemu_log_file = None

    monkeypatch.setattr(vm, "_pre_launch", fake_pre_launch)
    monkeypatch.setattr(vm, "_post_launch", lambda: None)

    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(machine.subprocess, "Popen", fake_popen)

    vm._launch()

    assert captured["preexec_fn"] is machine._raise_nofile_limit


# ---------------------------------------------------------------------------
# Functional test: the limit really is raised in the exec'd child process
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "posix", reason="preexec_fn requires POSIX")
def test_preexec_actually_raises_nofile_limit_in_child():
    repo_root = Path(machine.__file__).resolve().parents[3]
    script = textwrap.dedent(
        """
        import resource
        import subprocess
        import sys

        from qemu_compose.qemu.machine.machine import (
            _raise_nofile_limit,
            QEMU_NOFILE_SOFT_LIMIT,
        )

        _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        # Drop the soft limit low so the preexec change is observable.
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))

        code = "import resource; print(resource.getrlimit(resource.RLIMIT_NOFILE)[0])"
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            text=True,
            preexec_fn=_raise_nofile_limit,
        )
        out, _ = proc.communicate()
        child_soft = int(out.strip())

        if hard == resource.RLIM_INFINITY or hard >= QEMU_NOFILE_SOFT_LIMIT:
            floor = QEMU_NOFILE_SOFT_LIMIT
        else:
            floor = hard

        print(child_soft, floor)
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    child_soft, floor = (int(v) for v in result.stdout.split())

    # The child inherited 256; it must have been raised to at least the
    # best-effort target (the requested value, or the hard limit if lower).
    assert child_soft > 256
    assert child_soft >= floor
