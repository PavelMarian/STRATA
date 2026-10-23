"""Running untrusted, agent-written code.

Every call happens in a separate process with a wall-clock timeout and an
address-space limit, and without provider credentials in its environment:
the code under test is model-written, and the process that executes it must
not be able to reach a model on our account.
"""
from __future__ import annotations

import importlib.util
import multiprocessing as mp
import os
import shlex
import subprocess
import sys
import traceback
from pathlib import Path

SECRET_HINTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")


class ProgramError(RuntimeError):
    """The program crashed, timed out or broke its contract."""


def scrubbed_env(extra_keep=()):
    keep = set(extra_keep)
    return {k: v for k, v in os.environ.items()
            if k in keep or not any(h in k.upper() for h in SECRET_HINTS)}


def _limit(mem_mb):
    if mem_mb:
        try:
            import resource
            b = int(mem_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
        except (ImportError, ValueError, OSError):
            pass


def load_callable(spec: str):
    """'path/to/file.py:function' -> callable (imported in the current process)."""
    path, _, name = spec.rpartition(":")
    if not path:
        raise ValueError(f"expected FILE.py:FUNCTION, got {spec!r}")
    path = Path(path).resolve()
    mod_name = "strata_user_" + path.stem
    spec_ = importlib.util.spec_from_file_location(mod_name, path)
    if spec_ is None:
        raise ValueError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec_)
    sys.path.insert(0, str(path.parent))
    try:
        spec_.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    fn = getattr(mod, name, None)
    if not callable(fn):
        raise ValueError(f"{name} is not defined in {path}")
    return fn


def _child(conn, target, args, mem_mb, keep_env):
    try:
        os.environ.clear()
        os.environ.update(scrubbed_env(keep_env))
        _limit(mem_mb)
        fn = load_callable(target) if isinstance(target, str) else target
        conn.send(("ok", fn(*args)))
    except BaseException as e:  # noqa: BLE001 -- report everything the program throws
        conn.send(("err", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"))
    finally:
        conn.close()


def call_isolated(target, args, timeout=60, mem_mb=4096, keep_env=()):
    """Call target(*args) in a forked child. `target` is a callable or a
    'file.py:function' spec. Arguments reach the child through fork, so large
    databases are not copied or pickled; only the result is."""
    ctx = mp.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    p = ctx.Process(target=_child, args=(child, target, args, mem_mb, keep_env), daemon=True)
    p.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise ProgramError(f"timeout after {timeout}s")
        status, payload = parent.recv()
    except EOFError:
        raise ProgramError(f"program died (exit code {p.exitcode}); memory limit {mem_mb} MB?")
    finally:
        if p.is_alive():
            p.kill()
        p.join(1)
    if status != "ok":
        raise ProgramError(payload)
    return payload


def run_command(template: str, mapping: dict, timeout=600, mem_mb=4096, cwd=None, keep_env=()):
    """Run a shell-free command built from a template with {placeholders}."""
    argv = [part.format(**mapping) for part in shlex.split(template)]
    env = scrubbed_env(keep_env)
    env.setdefault("OMP_NUM_THREADS", "1")
    try:
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=timeout, preexec_fn=(lambda: _limit(mem_mb)))
    except subprocess.TimeoutExpired:
        raise ProgramError(f"timeout after {timeout}s: {' '.join(argv)}")
    if r.returncode != 0:
        raise ProgramError(f"exit {r.returncode}: {r.stderr.strip()[-800:]}")
    return r
