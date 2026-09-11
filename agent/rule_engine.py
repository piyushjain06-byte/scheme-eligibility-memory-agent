"""
agent/rule_engine.py — deterministic eligibility evaluation.

This is the only piece of the system that decides ELIGIBLE / NOT_ELIGIBLE /
NEEDS_INFORMATION. It is a pure function of (rule tree, memory dict) — no
LLM, no randomness, no side effects, no DB access — so every verdict is
reproducible and traceable back to the exact rule version + memory
snapshot that produced it.

Rule tree shape (see data/demo_schemes.json for real examples):

    {
      "logic": "AND" | "OR" | "NOT",
      "conditions": [
        {"field": "age", "operator": "between", "value": [18, 25]},
        {"logic": "OR", "conditions": [ ... ]}   # nodes can nest
      ]
    }

Supported operators: ==, !=, <, <=, >, >=, between, in
Supported logic: AND, OR, NOT (NOT expects exactly one child condition/node)

Public API:
    evaluate_rule(rule_json, memory) -> dict
        {
          "status": "ELIGIBLE" | "NOT_ELIGIBLE" | "NEEDS_INFORMATION",
          "reasons": [str, ...],
          "failed_conditions": [{"field", "operator", "expected", "actual"}, ...],
          "missing_fields": [str, ...],
        }
"""

SUPPORTED_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "between", "in"}
SUPPORTED_LOGIC = {"AND", "OR", "NOT"}


class InvalidRuleError(Exception):
    """Raised when a rule tree is malformed (bad logic/operator/shape)."""


class _NodeResult:
    """
    Internal tri-state result for a subtree: True (satisfied), False
    (failed), or None (can't be determined — some required field is
    missing from memory). Carries the explanation data needed to build the
    final response without re-walking the tree.
    """

    __slots__ = ("result", "reasons", "failed_conditions", "missing_fields")

    def __init__(self, result, reasons=None, failed_conditions=None, missing_fields=None):
        self.result = result
        self.reasons = reasons or []
        self.failed_conditions = failed_conditions or []
        self.missing_fields = missing_fields or []


def _is_leaf_condition(node: dict) -> bool:
    return "field" in node


def _describe(field, operator, value) -> str:
    if operator == "between":
        return f"{field} between {value[0]} and {value[1]}"
    if operator == "in":
        return f"{field} in {value}"
    return f"{field} {operator} {value}"


def _apply_operator(operator, actual, expected):
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == ">=":
        return actual >= expected
    if operator == "between":
        low, high = expected
        return low <= actual <= high
    if operator == "in":
        return actual in expected
    raise InvalidRuleError(f"Unsupported operator: {operator!r}")


def _evaluate_leaf(condition: dict, memory: dict) -> _NodeResult:
    field = condition.get("field")
    operator = condition.get("operator")
    expected = condition.get("value")

    if field is None or operator is None:
        raise InvalidRuleError(f"Malformed condition (needs 'field' and 'operator'): {condition}")
    if operator not in SUPPORTED_OPERATORS:
        raise InvalidRuleError(f"Unsupported operator: {operator!r}")

    actual = memory.get(field)
    if actual is None:
        return _NodeResult(result=None, missing_fields=[field])

    satisfied = _apply_operator(operator, actual, expected)
    description = _describe(field, operator, expected)

    if satisfied:
        return _NodeResult(result=True, reasons=[f"{description} (actual: {actual})"])
    return _NodeResult(
        result=False,
        failed_conditions=[
            {"field": field, "operator": operator, "expected": expected, "actual": actual}
        ],
    )


def _evaluate_and(children: list) -> _NodeResult:
    if any(c.result is False for c in children):
        failed = [fc for c in children if c.result is False for fc in c.failed_conditions]
        return _NodeResult(result=False, failed_conditions=failed)
    if any(c.result is None for c in children):
        missing = sorted({f for c in children if c.result is None for f in c.missing_fields})
        return _NodeResult(result=None, missing_fields=missing)
    reasons = [r for c in children for r in c.reasons]
    return _NodeResult(result=True, reasons=reasons)


def _evaluate_or(children: list) -> _NodeResult:
    if any(c.result is True for c in children):
        reasons = [r for c in children if c.result is True for r in c.reasons]
        return _NodeResult(result=True, reasons=reasons)
    if any(c.result is None for c in children):
        missing = sorted({f for c in children if c.result is None for f in c.missing_fields})
        return _NodeResult(result=None, missing_fields=missing)
    failed = [fc for c in children for fc in c.failed_conditions]
    return _NodeResult(result=False, failed_conditions=failed)


def _evaluate_not(children: list) -> _NodeResult:
    """
    NOT wraps exactly one child condition/node and inverts its result.
    True/False flip; an indeterminate (None) child stays indeterminate,
    since we can't know what NOT of "unknown" is.
    """
    if len(children) != 1:
        raise InvalidRuleError("'NOT' logic expects exactly one condition")
    child = children[0]

    if child.result is None:
        return _NodeResult(result=None, missing_fields=child.missing_fields)

    if child.result is True:
        # The wrapped condition held, so its negation fails.
        failed = [
            {"field": "NOT", "operator": "negation", "expected": "condition to fail", "actual": reason}
            for reason in child.reasons
        ] or [{"field": "NOT", "operator": "negation", "expected": "condition to fail", "actual": "condition held"}]
        return _NodeResult(result=False, failed_conditions=failed)

    # child.result is False -> its negation holds.
    reasons = [
        f"NOT ({fc['field']} {fc['operator']} {fc['expected']})" for fc in child.failed_conditions
    ] or ["NOT condition satisfied"]
    return _NodeResult(result=True, reasons=reasons)


def _evaluate_node(node: dict, memory: dict) -> _NodeResult:
    if _is_leaf_condition(node):
        return _evaluate_leaf(node, memory)

    logic = node.get("logic")
    conditions = node.get("conditions")
    if logic not in SUPPORTED_LOGIC:
        raise InvalidRuleError(f"Unsupported logic: {logic!r}")
    if not isinstance(conditions, list) or not conditions:
        raise InvalidRuleError("Logic node requires a non-empty 'conditions' list")

    children = [_evaluate_node(child, memory) for child in conditions]

    if logic == "AND":
        return _evaluate_and(children)
    if logic == "OR":
        return _evaluate_or(children)
    return _evaluate_not(children)  # logic == "NOT"


def evaluate_rule(rule_json: dict, memory: dict) -> dict:
    """
    Evaluate a rule tree against a citizen's memory dict.

    Returns a plain dict (not an ORM object) so callers — including
    EligibilityEvaluation rows and chat explanations — can serialize it
    directly.
    """
    if not isinstance(rule_json, dict):
        raise InvalidRuleError("rule_json must be a dict")

    root = _evaluate_node(rule_json, memory or {})

    if root.result is True:
        status = "ELIGIBLE"
    elif root.result is False:
        status = "NOT_ELIGIBLE"
    else:
        status = "NEEDS_INFORMATION"

    return {
        "status": status,
        "reasons": root.reasons,
        "failed_conditions": root.failed_conditions,
        "missing_fields": sorted(set(root.missing_fields)),
    }