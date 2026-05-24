# SPDX-License-Identifier: MIT
"""Shared console input helpers for GitAgents runtime tools."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path


def send_console_input(state_dir: Path, message: str, mode: str = "prompt", quiet: bool = False) -> bool:
    fifo = state_dir / "agents" / "console" / "input.fifo"
    payload = json.dumps({"message": message, "mode": mode}) + "\n"
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ENXIO, errno.ENOTDIR}:
            if not quiet:
                print(f"console input unavailable: {exc}", flush=True)
            return False
        raise
    try:
        try:
            os.write(fd, payload.encode("utf-8"))
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EPIPE}:
                if not quiet:
                    print(f"console input unavailable: {exc}", flush=True)
                return False
            raise
    finally:
        os.close(fd)
    return True
