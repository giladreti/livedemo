import argparse
import fcntl
import functools
import os
import pathlib
import pty
import random
import subprocess
import sys
import time
import termios
import threading
import tty

from typing import IO


def input_string(pty: IO, b: bytes, is_interactive: bool):
    for c in b:
        if is_interactive:
            read_char()
        else:
            time.sleep(random.random() / 2)

        fcntl.ioctl(pty.fileno(), termios.TIOCSTI, c.to_bytes(1, sys.byteorder))


def set_ctty(slave_fd: int, master_fd: int):
    os.setsid()
    os.close(master_fd)
    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)


def splice_master(master: IO):
    while True:
        try:
            sys.stdout.write(master.read(1).decode())
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


def run_demo(commands: list[bytes], is_interactive: bool):
    master_fd, slave_fd = pty.openpty()

    p = subprocess.Popen(
        ["bash"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=functools.partial(set_ctty, slave_fd, master_fd),
    )

    with os.fdopen(master_fd, "rb") as master:
        t = threading.Thread(target=splice_master, args=(master,))
        t.start()

        with os.fdopen(slave_fd, "rb") as slave:
            for command in commands:
                input_string(slave, command, is_interactive)
                read_char()

            try:
                p.wait(0)
            except subprocess.TimeoutExpired:
                input_string(slave, b"exit\n", is_interactive)

        p.wait()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("script_path", type=pathlib.Path, help="the demo script path")
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="whether or not to emulate user keystrokes",
    )

    args = parser.parse_args()

    commands = args.script_path.read_bytes().splitlines(keepends=True)

    run_demo(commands, args.interactive)


if __name__ == "__main__":
    main()
