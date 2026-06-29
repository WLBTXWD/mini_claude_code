"""Terminal renderer — streaming output with ANSI colors.

Extracted from main.py: TerminalRenderer + format_tool_args.
"""
import sys


class TerminalRenderer:
    """Small stateful renderer for streaming and transcript messages."""

    RESET = "\033[0m"
    DIM = "\033[0;37m"
    USER = "\033[1;36m"
    ASSISTANT = "\033[1;32m"
    TOOL = "\033[1;33m"
    TOOL_OK = "\033[0;34m"
    TOOL_ERROR = "\033[0;31m"

    def __init__(self, margin: str = "  "):
        self.margin = margin
        self.current_block: str | None = None
        self.at_line_start = True
        self.block_started = False
        self.text_started = False

    def render_user(self, text: str):
        self.close_block()
        self.text_started = False
        self._render_static_lines(
            text,
            first_prefix=f"{self.margin}{self.USER}You:{self.RESET}  ",
            next_prefix=f"{self.margin}{' ' * 8}",
        )

    def render_thinking(self, chunk: str):
        self._begin_block("thinking")
        self._render_chunk(
            chunk,
            first_prefix=f"{self.margin}{self.DIM}Thinking:{self.RESET} ",
            next_prefix=f"{self.margin}{self.DIM}{' ' * 10}",
            color=self.DIM,
        )

    def render_text(self, chunk: str):
        if self.current_block == "thinking":
            self.close_block(blank_after=True)
        self._begin_block("text")
        self._render_chunk(
            chunk,
            first_prefix=f"{self.margin}{self.ASSISTANT}Claude:{self.RESET} ",
            next_prefix=f"{self.margin}{' ' * 8}",
            color=None,
            use_first_prefix=not self.text_started,
        )
        if chunk:
            self.text_started = True

    def render_tool_use(self, name: str, raw_input: dict):
        self.close_block()
        args_str = format_tool_args(raw_input)
        print(f"{self.margin}{self.TOOL}[Tool]{self.RESET} {name}({args_str})")

    def render_tool_result(self, result_text: str):
        self.close_block()
        result_len = len(result_text)
        if result_text.startswith("Error") or result_text.startswith("Tool execution error"):
            brief = result_text[:80].replace("\n", " ")
            print(f"{self.margin}{self.TOOL_ERROR}  -> [error]{self.RESET} {brief}")
        elif result_len == 0:
            print(f"{self.margin}{self.TOOL_OK}  -> [empty]{self.RESET}")
        else:
            print(f"{self.margin}{self.TOOL_OK}  -> [ok, {result_len} chars]{self.RESET}")

    def render_compact(self, message: str):
        self.close_block()
        print(f"{self.margin}[{message}]")

    def close_block(self, blank_after: bool = False):
        if self.current_block is not None and not self.at_line_start:
            print()
        if blank_after:
            print()
        self.current_block = None
        self.at_line_start = True
        self.block_started = False

    def _begin_block(self, block: str):
        if self.current_block == block:
            return
        self.close_block()
        self.current_block = block
        self.at_line_start = True
        self.block_started = False

    def _render_chunk(
        self,
        chunk: str,
        first_prefix: str,
        next_prefix: str,
        color: str | None,
        use_first_prefix: bool = True,
    ):
        while chunk:
            if self.at_line_start:
                if use_first_prefix and not self.block_started:
                    print(first_prefix, end="", flush=True)
                    use_first_prefix = False
                else:
                    print(next_prefix, end="", flush=True)
                self.at_line_start = False
                self.block_started = True

            nl = chunk.find("\n")
            if nl == -1:
                text = chunk
                chunk = ""
            else:
                text = chunk[:nl + 1]
                chunk = chunk[nl + 1:]

            if color:
                print(f"{color}{text}{self.RESET}", end="", flush=True)
            else:
                print(text, end="", flush=True)

            if text.endswith("\n"):
                self.at_line_start = True

    def _render_static_lines(self, text: str, first_prefix: str, next_prefix: str):
        for i, line in enumerate(text.split("\n")):
            prefix = first_prefix if i == 0 else next_prefix
            print(f"{prefix}{line}")


def format_tool_args(raw_input: dict) -> str:
    parts = []
    for k, v in list(raw_input.items())[:3]:
        vs = str(v)
        if "\n" in vs:
            parts.append(f"{k}=\n{' ' * 16}{vs.replace(chr(10), chr(10) + ' ' * 16)}")
        else:
            parts.append(f"{k}={vs}")
    args_str = ", ".join(parts)
    if len(args_str) > 300:
        args_str = args_str[:300] + "..."
    return args_str
