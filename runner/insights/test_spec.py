"""Extracts the literal strings each pytest test checks for, from the test source.

These are compared against the task instruction to find requirements the tests enforce
but the instruction never states, a common cause of tasks being unfair to agents.
"""

import ast
import re
from dataclasses import dataclass

REGEX_FUNCTIONS = {"search", "match", "fullmatch", "findall", "finditer", "compile"}
REGEX_META = re.compile(r"[\\()\[\]{}.*+?^$|]")
MIN_LITERAL_CHARS = 4


@dataclass(frozen=True)
class TestLiteral:
    test: str
    literal: str
    line: int


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _is_excluded(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Skip assertion messages, f-strings, dict/subscript keys, and call arguments such as
    file modes or subprocess argv: they are not content the agent must produce."""
    child, parent = node, parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.Assert) and child is parent.msg:
            return True
        if isinstance(parent, (ast.JoinedStr, ast.Dict, ast.Subscript)):
            return True
        if isinstance(parent, ast.Call) and child in parent.args and not _is_regex_call(parent):
            return True
        if isinstance(parent, ast.Expr) and isinstance(parents.get(parent), ast.FunctionDef):
            return True
        child, parent = parent, parents.get(parent)
    return False


def _is_regex_call(call: ast.Call) -> bool:
    func = call.func
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "re" \
        and func.attr in REGEX_FUNCTIONS


def _literal_text(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> str:
    parent = parents.get(node)
    if isinstance(parent, ast.Call) and _is_regex_call(parent):
        return REGEX_META.split(node.value, maxsplit=1)[0]
    return node.value


def required_literals(source: str) -> dict[str, list[TestLiteral]]:
    tree = ast.parse(source)
    parents = _parents(tree)
    lines = source.splitlines()
    literals: dict[str, list[TestLiteral]] = {}

    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith("test"):
            continue
        found = []
        for node in ast.walk(function):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if _is_excluded(node, parents):
                continue
            text = _literal_text(node, parents).strip()
            line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if len(text) >= MIN_LITERAL_CHARS and any(c.isalnum() for c in text) and text in line_text:
                found.append(TestLiteral(function.name, text, node.lineno))
        literals[function.name] = found
    return literals
