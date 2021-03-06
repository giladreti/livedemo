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


def input_char(slave_fd: int, ch: bytes):
    fcntl.ioctl(slave_fd, termios.TIOCSTI, ch)


def input_string_generic(slave_fd: IO, b: bytes, delay_fn: Callable[[], None]):
    read_char()

    for ch in b:
        delay_fn()

        input_char(slave_fd, ch.to_bytes(1, sys.byteorder))


def input_string_interactive(slave_fd: IO, b: bytes):
    return input_string_generic(slave_fd, b, delay_fn=read_char())


def input_string_noninteractive(slave_fd: IO, b: bytes, rate: float):
    return input_string_generic(
        slave_fd, b, delay_fn=lambda: time.sleep(random.random() / rate)
    )


def set_winsize(fd: int, row: int, col: int, xpix: int = 0, ypix: int = 0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def set_ctty(slave_fd: int, master_fd: int, rows: int, cols: int):
    os.setsid()
    os.close(master_fd)
    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
    set_winsize(slave_fd, rows, cols)


def splice_master(master: IO, end_event: threading.Event):
    while not end_event.is_set():
        sys.stdout.buffer.write(master.read(1))
        sys.stdout.flush()


def read_char() -> str:
    fd = sys.stdin.fileno()

    attrs = termios.tcgetattr(fd)

    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)

    return ch


def toggle_echo(slave_fd: int):
    attrs = termios.tcgetattr(slave_fd)

    attrs[3] ^= termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)


def interact(slave_fd: int, p: subprocess.Popen):
    while is_alive(p):
        ch = read_char()
        input_char(slave_fd, ch)


def is_alive(p: subprocess.Popen) -> bool:
    try:
        p.wait(0)
    except subprocess.TimeoutExpired:
        return True
    return False


def run_demo(
    interpreter: str,
    commands: list[bytes],
    is_interactive: bool,
    rate: float,
    keep: bool,
):
    master_fd, slave_fd = pty.openpty()

    cols, rows = shutil.get_terminal_size()

    os.system("clear")  # clear screen

    p = subprocess.Popen(
        [interpreter],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=functools.partial(set_ctty, slave_fd, master_fd, rows, cols),
    )

    with os.fdopen(master_fd, "rb") as master:
        end_event = threading.Event()
        t = threading.Thread(
            target=splice_master, args=(master, end_event), daemon=True
        )
        t.start()

        toggle_echo(sys.stdin.fileno())

        for command in commands:
            if is_interactive:
                input_string_interactive(slave_fd, command)
            else:
                input_string_noninteractive(slave_fd, command, rate)

        if keep:
            interact(slave_fd, p)

        end_event.set()
        p.wait()

        input_char(slave_fd, b" ")  # release reading thread

        toggle_echo(sys.stdin.fileno())


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("script_path", type=pathlib.Path, help="the demo script path")
    parser.add_argument(
        "--interpreter",
        "--interp",
        default="bash",
        help="the interpreter to execuet the demo in",
    )

    parser.add_argument(
        "--keep",
        action="store_true",
        help="whether to keep the demo for interaction after it has ended",
    )
    parser.add_argument(
        "--remove_empty",
        action="store_true",
        default=True,
        help="whether to remove empty input lines from demo",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="whether to emulate user keystrokes",
    )
    group.add_argument(
        "-r",
        "--rate",
        type=float,
        default=2,
        help="the keystrokes rate",
    )

    args = parser.parse_args()

    script_path: pathlib.Path = args.script_path
    commands = script_path.read_bytes().splitlines(keepends=True)
    if args.remove_empty:
        commands = [command for command in commands if not command.isspace()]

    run_demo(args.interpreter, commands, args.interactive, args.rate, args.keep)


if __name__ == "__main__":
    main()
