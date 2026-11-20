"""Terminal helpers: ANSI colours, centring, width."""

import os
import re


class fg:
    """Foreground ANSI colour codes."""
    cyan_bold = "\033[1;34m"
    red_bold = "\033[1;31m"
    cyan = "\033[96m"
    red = "\033[31m"
    green = "\033[1;32m"
    yellow = "\033[1;33m"
    grey = "\033[1;30m"
    reset = "\033[0m"
    bold = "\033[1m"


def strip_ansi(text: str) -> str:
    """Return *text* with all ANSI escape sequences removed."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def center(text: str, width: int) -> str:
    """Centre *text* that may contain ANSI codes inside *width* columns."""
    visible = len(strip_ansi(text))
    pad = max(0, width - visible) // 2
    return " " * pad + text


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80
