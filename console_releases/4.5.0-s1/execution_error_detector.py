from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorSignature:
    signature_id: str
    description: str
    pattern: re.Pattern[str]


# Keep this list deliberately conservative. These are signatures that almost
# always mean the command did not execute as intended, even when an outer shell
# later returns rc=0 or user-provided CONTINUE_RUN markers happen to match.
# New signatures can be added independently as production evidence appears.
ERROR_SIGNATURES: tuple[ErrorSignature, ...] = (
    ErrorSignature(
        "NODE_MODULE_NOT_FOUND",
        "Node.js could not resolve an imported module",
        re.compile(r"(?m)^Error \[ERR_MODULE_NOT_FOUND\]:"),
    ),
    ErrorSignature(
        "NODE_MISSING_NAMED_EXPORT",
        "Node.js imported a module that does not provide a requested named export",
        re.compile(r"(?m)^SyntaxError: The requested module .+ does not provide an export named "),
    ),
    ErrorSignature(
        "NODE_FATAL_ERROR",
        "Node.js reported a fatal runtime error",
        re.compile(r"(?m)^FATAL ERROR: .+$"),
    ),
    ErrorSignature(
        "PYTHON_IMPORT_FAILURE",
        "Python failed to import a module",
        re.compile(r"(?m)^(?:ModuleNotFoundError|ImportError): .+$"),
    ),
    ErrorSignature(
        "PYTHON_SYNTAX_ERROR",
        "Python could not parse source code",
        re.compile(r"(?m)^SyntaxError: .+$"),
    ),
    ErrorSignature(
        "SHELL_COMMAND_NOT_FOUND",
        "The shell could not find a command",
        re.compile(r"(?mi)^(?:-?(?:ba)?sh|/bin/(?:ba)?sh): .*command not found\s*$"),
    ),
    ErrorSignature(
        "SHELL_PATH_NOT_FOUND",
        "The shell could not open an executable or path",
        re.compile(r"(?mi)^(?:-?(?:ba)?sh|/bin/(?:ba)?sh): .*No such file or directory\s*$"),
    ),
    ErrorSignature(
        "GIT_FATAL",
        "Git reported a fatal error",
        re.compile(r"(?m)^fatal: .+$"),
    ),
    ErrorSignature(
        "SEGMENTATION_FAULT",
        "A process terminated with a segmentation fault",
        re.compile(r"(?mi)\bSegmentation fault(?: \(core dumped\))?\b"),
    ),
    ErrorSignature(
        "PROCESS_ABORTED",
        "A process aborted and may have dumped core",
        re.compile(r"(?mi)^Aborted(?: \(core dumped\))?\s*$"),
    ),
)


class ExecutionErrorDetector:
    """Incrementally detect high-confidence execution failures in output.

    The detector only sees raw combined stdout+stderr emitted by the command;
    it never scans the terminal prompt or the command source itself. A rolling
    tail lets regular expressions match across subprocess read boundaries.
    """

    def __init__(self, *, tail_chars: int = 8192, excerpt_chars: int = 320) -> None:
        self.tail_chars = max(1024, int(tail_chars))
        self.excerpt_chars = max(80, int(excerpt_chars))
        self._tail = ""
        self._matches: dict[str, dict[str, Any]] = {}

    def feed(self, text: str) -> bool:
        if not text:
            return False
        combined = self._tail + text
        changed = False
        for signature in ERROR_SIGNATURES:
            if signature.signature_id in self._matches:
                continue
            match = signature.pattern.search(combined)
            if match is None:
                continue
            start = max(0, match.start() - self.excerpt_chars // 3)
            end = min(len(combined), match.end() + self.excerpt_chars)
            excerpt = combined[start:end].replace("\r", "")
            excerpt = "\n".join(line.rstrip() for line in excerpt.splitlines())
            if len(excerpt) > self.excerpt_chars:
                excerpt = excerpt[: self.excerpt_chars] + "…"
            self._matches[signature.signature_id] = {
                "id": signature.signature_id,
                "description": signature.description,
                "excerpt": excerpt,
            }
            changed = True
        self._tail = combined[-self.tail_chars :]
        return changed

    @property
    def detected(self) -> bool:
        return bool(self._matches)

    def result(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._matches.values()]
