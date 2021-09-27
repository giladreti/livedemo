import argparse
import fcntl
import functools
import os
import pathlib
import pty
import random
import shutil
import struct
import subprocess
import sys
import time
import termios
import threading
import tty

from typing import IO, Callable


def input_string_generic(slave_fd: IO, b: bytes, delay_fn: Callable[[], None]):
    read_char()

    for c in b:
        delay_fn()

        fcntl.ioctl(slave_fd, termios.TIOCSTI, c.to_bytes(1, sys.byteorder))


def input_string_interactive(slave_fd: IO, b: bytes):
    return input_string_generic(slave_fd, b, delay_fn=read_char())


def input_string_noninteractive(slave_fd: IO, b: bytes, rate: float):
    return input_string_generic(slave_fd, b, delay_fn=lambda: time.sleep(random.random() / rate))


def set_winsize(fd: int, row: int, col: int, xpix: int = 0, ypix: int = 0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def set_ctty(slave_fd: int, master_fd: int, rows: int, cols: int):
    os.setsid()
    os.close(master_fd)
    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
    set_winsize(slave_fd, rows, cols)


def splice_master(master: IO):
    while True:
        try:
            sys.stdout.buffer.write(master.read(1))
            sys.stdout.flush()
        except OSError:
            break


def read_char() -> str:
    fd = sys.stdin.fileno()

    toggle_echo(fd)

    attrs = termios.tcgetattr(fd)

    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)

    toggle_echo(fd)

    return ch


def toggle_echo(slave_fd: int):
    attrs = termios.tcgetattr(slave_fd)

    attrs[3] ^= termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)


def is_alive(p: subprocess.Popen) -> bool:
    try:
        p.wait(0)
    except subprocess.TimeoutExpired:
        return True
    return False


def run_demo(interpreter: str, commands: list[bytes], is_interactive: bool, rate: float):
    master_fd, slave_fd = pty.openpty()

    cols, rows = shutil.get_terminal_size()

    p = subprocess.Popen(
        [interpreter],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=functools.partial(set_ctty, slave_fd, master_fd, rows, cols),
    )

    with os.fdopen(master_fd, "rb") as master:
        t = threading.Thread(target=splice_master, args=(master,), daemon=True)
        t.start()

        for command in commands:
            if is_interactive:
                input_string_interactive(slave_fd, command)
            else:
                input_string_noninteractive(slave_fd, command, rate)

        if is_alive(p):
            input_string_noninteractive(slave_fd, b"exit\n", rate)

        p.wait()


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("script_path", type=pathlib.Path, help="the demo script path")
    parser.add_argument("--interpreter", "--interp", default="bash", help="the interpreter to execuet the demo in")

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="whether or not to emulate user keystrokes",
    )
    group.add_argument(
        "-r",
        "--rate",
        type=float,
        default=2,
        help="the keystrokes rate",
    )

    args = parser.parse_args()

    commands = args.script_path.read_bytes().splitlines(keepends=True)

    run_demo(args.interpreter, commands, args.interactive, args.rate)


if __name__ == "__main__":
    main()
