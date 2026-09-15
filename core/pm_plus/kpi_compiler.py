"""KPI formula validation and evaluation for PM Plus."""

from __future__ import annotations

import ast
import re

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_AGG_CALL_RE = re.compile(r"\b(SUM|AVG)\s*\(\s*([^)]+)\s*\)", re.I)


def formula_tokens(formula: str) -> list[str]:
    text = str(formula or "")
    # strip SUM()/AVG() wrappers for token discovery
    cleaned = _AGG_CALL_RE.sub(lambda m: m.group(2), text)
    tokens = []
    reserved = {"SUM", "AVG", "MIN", "MAX", "AND", "OR", "NOT"}
    for tok in _TOKEN_RE.findall(cleaned):
        if tok.upper() in reserved:
            continue
        if tok not in tokens:
            tokens.append(tok)
    return tokens


def validate_formula(formula: str, known_counters: set[str] | list[str] | None = None) -> dict:
    text = str(formula or "").strip()
    errors: list[str] = []
    warnings: list[str] = []
    if not text:
        errors.append("Formula cannot be empty.")
    if len(text) > 2000:
        errors.append("Formula is too long (max 2000 characters).")
    if re.search(r"[;\"'`]|--|/\*|\*/", text):
        errors.append("Only counter math is allowed (no SQL keywords or quotes).")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_().+-*/%, \t\n")
    if any(ch not in allowed for ch in text):
        errors.append("Formula contains unsupported characters.")

    known = {str(c).strip() for c in (known_counters or []) if str(c).strip()}
    tokens = formula_tokens(text)
    unknown = [t for t in tokens if known and t not in known and "*" not in t]
    if unknown:
        warnings.append(f"Unknown counter(s): {', '.join(sorted(set(unknown))[:8])}")

    bal = 0
    for ch in text:
        if ch == "(":
            bal += 1
        elif ch == ")":
            bal -= 1
        if bal < 0:
            errors.append("Unbalanced parentheses.")
            break
    if bal > 0:
        errors.append("Unbalanced parentheses.")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "tokens": tokens}


class _SafeEval(ast.NodeVisitor):
    """Evaluate arithmetic AST with a name → float map."""

    def __init__(self, names: dict[str, float | None]):
        self.names = names

    def visit(self, node):  # type: ignore[override]
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            return self.names.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = self.visit(node.left)
            right = self.visit(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    return None
                return left / right
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            val = self.visit(node.operand)
            if val is None:
                return None
            return val if isinstance(node.op, ast.UAdd) else -val
        if isinstance(node, ast.Call):
            # SUM(x)/AVG(x) treated as identity for already-aggregated map values
            if isinstance(node.func, ast.Name) and node.func.id.upper() in ("SUM", "AVG") and node.args:
                return self.visit(node.args[0])
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def eval_formula(formula: str, counter_values: dict[str, float | None]) -> float | None:
    """Evaluate a KPI formula against a counter_id → value map. /0 → None."""
    text = str(formula or "").strip()
    if not text:
        return None
    # Normalize SUM(x) → x for AST
    text = _AGG_CALL_RE.sub(lambda m: m.group(2).strip(), text)
    try:
        tree = ast.parse(text, mode="eval")
        return _SafeEval(counter_values).visit(tree)
    except Exception:  # noqa: BLE001
        return None


def completeness(expected: int, received: int) -> float | None:
    if expected <= 0:
        return None
    return round(100.0 * min(received, expected) / expected, 2)
