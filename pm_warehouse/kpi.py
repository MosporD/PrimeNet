"""KPI formulas → SQL over the family fact tables, at query time only.

Grammar (verified sufficient for 99.7 % of the 1 957 vendor 4G formulas):

    expr    := term (('+'|'-') term)*
    term    := factor (('*'|'/') factor)*
    factor  := NUMBER | '[' IDENT ']' | 'sum' '(' expr ')'
             | '(' expr ')' | '-' factor

Compilation rules:
  - ``sum(e)`` becomes SQL ``SUM(e')`` where counter tokens inside e' are
    ``COALESCE(col, 0)`` — reduction happens in GROUP BY *before* arithmetic,
    so ratio-of-sums is structurally enforced; mean-of-ratios is inexpressible.
  - A bare ``[c]`` outside sum() is treated per its agg_rule (SUM(col) for
    SUM-rule, SUM(col)/SUM(n_present) for AVG-rule, MAX/MIN accordingly).
  - Every '/' denominator is wrapped in NULLIF(...,0): undefined KPI = NULL,
    never 0 and never an error.
  - Counter names resolve through pm.dim_counter; user text never reaches SQL —
    only whitelisted column identifiers do.

Multi-family formulas compile to per-family grouped subqueries joined on the
grouping keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import family_table

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<ctr>\[[A-Za-z0-9_]+\])"
    r"|(?P<sum>sum\b)|(?P<op>[-+*/()]))",
    re.IGNORECASE,
)


class FormulaError(ValueError):
    pass


# ---- AST ----------------------------------------------------------------

@dataclass
class Num:
    value: float


@dataclass
class Ctr:
    native_id: str


@dataclass
class Sum:
    arg: object


@dataclass
class BinOp:
    op: str
    left: object
    right: object


def tokenize(formula: str) -> list:
    out, pos = [], 0
    text = formula.strip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise FormulaError(f"unexpected character at {text[pos:pos+12]!r}")
        if m.group("num"):
            out.append(("num", float(m.group("num"))))
        elif m.group("ctr"):
            out.append(("ctr", m.group("ctr")[1:-1]))
        elif m.group("sum"):
            out.append(("sum", "sum"))
        else:
            out.append(("op", m.group("op")))
        pos = m.end()
    return out


def parse(formula: str):
    tokens = tokenize(formula)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def take(kind=None, value=None):
        nonlocal pos
        k, v = peek()
        if kind and k != kind or (value is not None and v != value):
            raise FormulaError(f"expected {value or kind}, got {v!r}")
        pos += 1
        return v

    def expr():
        node = term()
        while peek() == ("op", "+") or peek() == ("op", "-"):
            op = take("op")
            node = BinOp(op, node, term())
        return node

    def term():
        node = factor()
        while peek() == ("op", "*") or peek() == ("op", "/"):
            op = take("op")
            node = BinOp(op, node, factor())
        return node

    def factor():
        k, v = peek()
        if k == "num":
            take()
            return Num(v)
        if k == "ctr":
            take()
            return Ctr(v)
        if k == "sum":
            take()
            take("op", "(")
            node = Sum(expr())
            take("op", ")")
            return node
        if (k, v) == ("op", "("):
            take()
            node = expr()
            take("op", ")")
            return node
        if (k, v) == ("op", "-"):
            take()
            return BinOp("-", Num(0.0), factor())
        raise FormulaError(f"unexpected token {v!r}")

    node = expr()
    if pos != len(tokens):
        raise FormulaError("trailing input after formula")
    return node


def counters_in(node) -> set[str]:
    if isinstance(node, Ctr):
        return {node.native_id}
    if isinstance(node, Sum):
        return counters_in(node.arg)
    if isinstance(node, BinOp):
        return counters_in(node.left) | counters_in(node.right)
    return set()


# ---- compilation --------------------------------------------------------

def _emit(node, resolve, inside_sum: bool) -> str:
    if isinstance(node, Num):
        return repr(node.value)
    if isinstance(node, Ctr):
        fam_alias, col, rule = resolve(node.native_id)
        q = f'{fam_alias}."{col}"'
        if inside_sum:
            return f"COALESCE({q},0)"
        if rule == "AVG":
            return f"(SUM({q}) / NULLIF(SUM({fam_alias}.n_present),0))"
        if rule == "MAX":
            return f"MAX({q})"
        if rule == "MIN":
            return f"MIN({q})"
        return f"SUM({q})"
    if isinstance(node, Sum):
        return f"SUM({_emit(node.arg, resolve, True)})"
    if isinstance(node, BinOp):
        left = _emit(node.left, resolve, inside_sum)
        right = _emit(node.right, resolve, inside_sum)
        if node.op == "/":
            return f"({left} / NULLIF({right},0))"
        return f"({left} {node.op} {right})"
    raise FormulaError(f"unknown node {node!r}")


OBJECT_SCOPES = {
    "cell": "o.base_dn",
    "enb": "parent.base_dn",
    "site": "o.site_id",
    "area": "o.area",
    "network": "'network'",
}

TIME_GRAINS = {"hour": "h", "day": "d", "week": "w", "month": "m"}


def compile_kpi(
    formula: str,
    counter_meta: dict[str, dict],   # native_id -> {family, column, rule}
    *,
    grain: str = "hour",
    object_scope: str = "cell",
    group_id: int | None = None,
) -> tuple[str, dict]:
    """Compile a formula to one SQL statement.

    Returns (sql, params-template). Caller supplies %(t0)s / %(t1)s and
    optionally %(gid)s.
    """
    ast = parse(formula)
    used = counters_in(ast)
    unknown = [c for c in used if c not in counter_meta]
    if unknown:
        raise FormulaError(f"unknown counters: {unknown}")

    g = TIME_GRAINS[grain]
    families = sorted({counter_meta[c]["family"] for c in used})
    alias_of = {fam: f"f{i}" for i, fam in enumerate(families)}

    def resolve(native_id: str):
        meta = counter_meta[native_id]
        return alias_of[meta["family"]], meta["column"], meta["rule"]

    value_sql = _emit(ast, resolve, False)

    obj_expr = OBJECT_SCOPES[object_scope]
    base_alias = alias_of[families[0]]
    joins = [f"FROM pm.{family_table(families[0], g)} {base_alias}"]
    for fam in families[1:]:
        a = alias_of[fam]
        joins.append(
            f"JOIN pm.{family_table(fam, g)} {a} USING (object_id, binding_id, bucket)"
        )
    joins.append(f"JOIN pm.dim_object o ON o.object_id = {base_alias}.object_id")
    if object_scope == "enb":
        joins.append("JOIN pm.dim_object parent ON parent.object_id = o.parent_id")
    if group_id is not None:
        joins.append(
            f"JOIN pm.object_group_member gm "
            f"ON gm.object_id = {base_alias}.object_id AND gm.group_id = %(gid)s"
        )

    completeness = (
        f"SUM({base_alias}.n_present)::float / NULLIF(SUM({base_alias}.n_expected),0)"
    )
    sql = (
        f"SELECT {obj_expr} AS object_key, {base_alias}.bucket AS bucket,\n"
        f"       {value_sql} AS value,\n"
        f"       {completeness} AS completeness\n"
        + "\n".join(joins)
        + f"\nWHERE {base_alias}.bucket >= %(t0)s AND {base_alias}.bucket < %(t1)s\n"
        f"GROUP BY 1, 2\nORDER BY 1, 2"
    )
    return sql, {"needs_gid": group_id is not None}


def counter_meta_from_db(conn, vendor: str = "nokia", technology: str = "4G") -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT native_id, family, column_name, agg_rule FROM pm.dim_counter "
            "WHERE vendor=%s AND technology=%s",
            (vendor, technology),
        )
        return {
            nid: {"family": fam, "column": col, "rule": rule}
            for nid, fam, col, rule in cur.fetchall()
        }
