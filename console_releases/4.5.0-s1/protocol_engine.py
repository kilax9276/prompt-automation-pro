# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


EXECUTABLE_TYPES = {
    "COMMAND_PUT_FILES",
    "COMMAND_RUN",
    "COMMAND_GET_REPORTS",
    "COMMAND_USER_ACTION_REQ",
    "COMMAND_RUN_WORKER",
    "COMMAND_RUN_INSERVER",
    "COMMAND_CURRENT_DEV_COMPLETE",
}

CONTROL_TYPES = {
    "COMMAND_RUN_WORKER",
    "COMMAND_RUN_INSERVER",
    "COMMAND_CURRENT_DEV_COMPLETE",
}


def decode_opaque(value: Any, item: dict[str, Any]) -> Any:
    if value is None:
        return None
    if item.get("valueEncoding") == "base64-utf8" and isinstance(value, str):
        try:
            return base64.b64decode(value).decode("utf-8")
        except Exception:
            return value
    return value


def normalize_directive_value(item: dict[str, Any]) -> Any:
    return decode_opaque(item.get("value"), item)


def _nested_by_type(items: Iterable[dict[str, Any]], item_type: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("type") == item_type:
            return item
    return None


def build_plan(result: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, DOM-order-preserving execution plan from parser JSON."""
    steps: list[dict[str, Any]] = []
    sequence = 0

    all_messages = result.get("messages") if isinstance(result.get("messages"), list) else []
    messages = all_messages[-1:] if all_messages else []
    selected_message_position = None
    if messages:
        selected_message_position = int(
            messages[0].get("messagePosition") or len(all_messages)
        )

    for message_index, message in enumerate(messages, start=1):
        message_position = int(message.get("messagePosition") or selected_message_position or message_index)
        items = message.get("items") if isinstance(message.get("items"), list) else []
        for item_index, item in enumerate(items, start=1):
            sequence += 1
            item_type = str(item.get("type") or "UNKNOWN")
            position = int(item.get("position") or item_index)
            step_id = f"s{sequence:03d}"
            base = {
                "stepId": step_id,
                "sequence": sequence,
                "messagePosition": message_position,
                "position": position,
                "sourceType": item_type,
                "commandId": item.get("commandId"),
                "executable": False,
            }

            if item_type == "RUN":
                nested = item.get("items") if isinstance(item.get("items"), list) else []
                run_type = str(item.get("runType") or "COMMAND_RUN")
                base["type"] = run_type
                base["sourceType"] = "RUN"
                base["runIndex"] = item.get("runIndex")
                base["executable"] = run_type in EXECUTABLE_TYPES

                if run_type == "COMMAND_RUN":
                    command_item = _nested_by_type(nested, "COMMAND_RUN") or {}
                    stop_item = _nested_by_type(nested, "STOP_RUN")
                    continue_item = _nested_by_type(nested, "CONTINUE_RUN")
                    condition_item = _nested_by_type(nested, "STOP_CONDITION")
                    if condition_item is None:
                        condition_item = _nested_by_type(nested, "CONDITION_RUN")
                    base.update(
                        {
                            "command": normalize_directive_value(command_item) or "",
                            "stopRun": stop_item.get("value") if stop_item else None,
                            "continueRun": continue_item.get("value") if continue_item else None,
                            "conditionRun": condition_item.get("value") if condition_item else None,
                        }
                    )
                else:
                    payload_item = _nested_by_type(nested, run_type)
                    if payload_item is None and nested:
                        payload_item = nested[0]
                    base["payload"] = normalize_directive_value(payload_item or {})
                steps.append(base)
                continue

            if item_type in EXECUTABLE_TYPES:
                base["type"] = item_type
                base["executable"] = True
                if item_type == "COMMAND_RUN":
                    base["command"] = normalize_directive_value(item) or ""
                    base["stopRun"] = None
                    base["continueRun"] = None
                    base["conditionRun"] = None
                else:
                    base["payload"] = normalize_directive_value(item)
                steps.append(base)
                continue

            if item_type == "AFTER_COMMANDS":
                base.update(
                    {
                        "type": "AFTER_COMMANDS",
                        "text": str(item.get("text") or ""),
                        "details": item.get("items") if isinstance(item.get("items"), list) else [],
                    }
                )
                steps.append(base)
                continue

            if item_type == "FILE":
                base.update(
                    {
                        "type": "FILE",
                        "name": item.get("name"),
                        "fileKind": item.get("fileKind"),
                        "extension": item.get("extension"),
                        "download": item.get("download") if isinstance(item.get("download"), dict) else {},
                    }
                )
                steps.append(base)
                continue

            base.update({"type": item_type, "payload": normalize_directive_value(item)})
            steps.append(base)

    return {
        "schemaVersion": 2,
        "messageScope": "LATEST_ASSISTANT_MESSAGE",
        "sourceMessageCount": len(all_messages),
        "selectedMessagePosition": selected_message_position,
        "page": result.get("page"),
        "generatedAt": result.get("generatedAt"),
        "order": result.get("order") or "DOM_TOP_TO_BOTTOM",
        "parserVersion": result.get("parserVersion"),
        "steps": steps,
    }


def parse_user_action_payload(payload: Any) -> dict[str, Any]:
    text = str(payload or "")
    match = re.match(r"^FOR_ID::([^\r\n]+)\r?\n?(.*)$", text, flags=re.S)
    if not match:
        return {"forId": None, "text": text}
    return {"forId": match.group(1).strip(), "text": match.group(2).strip()}


@dataclass
class MatcherResult:
    stop_run: bool | None
    continue_run: bool | None
    stop_hits: list[dict[str, Any]]
    continue_hits: list[dict[str, Any]]


class OutputMatcher:
    def __init__(self, stop_patterns: list[str] | None, continue_patterns: list[str] | None) -> None:
        self.stop_patterns = [str(x) for x in stop_patterns] if isinstance(stop_patterns, list) else None
        self.continue_patterns = [str(x) for x in continue_patterns] if isinstance(continue_patterns, list) else None
        all_patterns = (self.stop_patterns or []) + (self.continue_patterns or [])
        self._found: dict[str, bool] = {pattern: False for pattern in all_patterns}
        self._carry = ""
        self._max_pattern = max([len(x) for x in all_patterns], default=1)

    def feed(self, text: str) -> bool:
        if not text:
            return False
        probe = self._carry + text
        changed = False
        for pattern in self._found:
            if not self._found[pattern] and pattern in probe:
                self._found[pattern] = True
                changed = True
        keep = max(0, self._max_pattern - 1)
        self._carry = probe[-keep:] if keep else ""
        return changed

    def result(self) -> MatcherResult:
        stop_hits = [
            {"pattern": p, "found": bool(self._found.get(p))}
            for p in (self.stop_patterns or [])
        ]
        continue_hits = [
            {"pattern": p, "found": bool(self._found.get(p))}
            for p in (self.continue_patterns or [])
        ]
        stop_value = None if self.stop_patterns is None else any(x["found"] for x in stop_hits)
        continue_value = None if self.continue_patterns is None else all(x["found"] for x in continue_hits)
        return MatcherResult(stop_value, continue_value, stop_hits, continue_hits)


_TOKEN_RE = re.compile(r"\s*(STOP_RUN|CONTINUE_RUN|&&|\|\||!|\(|\))\s*")


def _tokenize_condition(expression: str) -> list[str]:
    pos = 0
    tokens: list[str] = []
    while pos < len(expression):
        match = _TOKEN_RE.match(expression, pos)
        if not match:
            raise ValueError(f"Unsupported CONDITION_RUN syntax near: {expression[pos:pos+40]!r}")
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


class _ConditionParser:
    def __init__(self, tokens: list[str], values: dict[str, bool | None]) -> None:
        self.tokens = tokens
        self.values = values
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, token: str | None = None) -> str:
        current = self.peek()
        if current is None:
            raise ValueError("Unexpected end of CONDITION_RUN")
        if token is not None and current != token:
            raise ValueError(f"Expected {token}, got {current}")
        self.pos += 1
        return current

    def parse(self) -> bool:
        value = self.parse_or()
        if self.peek() is not None:
            raise ValueError(f"Unexpected token {self.peek()}")
        return value

    def parse_or(self) -> bool:
        value = self.parse_and()
        while self.peek() == "||":
            self.take("||")
            rhs = self.parse_and()
            value = value or rhs
        return value

    def parse_and(self) -> bool:
        value = self.parse_unary()
        while self.peek() == "&&":
            self.take("&&")
            rhs = self.parse_unary()
            value = value and rhs
        return value

    def parse_unary(self) -> bool:
        if self.peek() == "!":
            self.take("!")
            return not self.parse_unary()
        if self.peek() == "(":
            self.take("(")
            value = self.parse_or()
            self.take(")")
            return value
        name = self.take()
        if name not in {"STOP_RUN", "CONTINUE_RUN"}:
            raise ValueError(f"Unsupported operand {name}")
        raw = self.values.get(name)
        if raw is None:
            raise ValueError(f"CONDITION_RUN references missing field {name}")
        return bool(raw)


def evaluate_condition(expression: str | None, *, stop_run: bool | None, continue_run: bool | None) -> bool | None:
    if expression is None or not str(expression).strip():
        return None
    tokens = _tokenize_condition(str(expression))
    return _ConditionParser(tokens, {"STOP_RUN": stop_run, "CONTINUE_RUN": continue_run}).parse()


def evaluate_condition_partial(expression: str | None, *, stop_run: bool | None, continue_run: bool | None) -> bool | None:
    """Evaluate a running condition only when its result is already irrevocable.

    ``None`` means an operand is still unresolved because more command output
    can arrive. With only two boolean operands it is safest to evaluate all
    possible completions and return a value only if every completion agrees.
    """
    if expression is None or not str(expression).strip():
        return None
    stop_values = [bool(stop_run)] if stop_run is not None else [False, True]
    continue_values = [bool(continue_run)] if continue_run is not None else [False, True]
    outcomes: set[bool] = set()
    for stop_value in stop_values:
        for continue_value in continue_values:
            outcomes.add(bool(evaluate_condition(str(expression), stop_run=stop_value, continue_run=continue_value)))
    return next(iter(outcomes)) if len(outcomes) == 1 else None


def normalize_filename(value: str) -> str:
    base = value.replace("\\", "/").split("/")[-1].lower().strip()
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^a-z0-9._-]+", "", base)
    return base


def plan_json(result: dict[str, Any]) -> str:
    return json.dumps(build_plan(result), ensure_ascii=False, indent=2)
