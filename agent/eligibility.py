"""
agent/eligibility.py — scheme-level eligibility on top of the pure rule engine.

rule_engine.evaluate_rule stays a pure function of (rule tree, memory). This wrapper adds the things a
rule tree cannot express by itself:

  * value normalisation  — "obc"/"OBC category", "Jobless"/"unemployed" compare equal;
  * jurisdiction         — a STATE scheme is only for residents of that state, even if the rule
                           never mentions `state`;
  * manual checks        — criteria that are not among the 14 profile fields (BPL card, land holding…)
                           are listed so they are never silently skipped.
"""
from agent.normalize import canonical_state, normalize_memory, normalize_rule
from agent.rule_engine import evaluate_rule


def scheme_state(scheme):
    """State/UT a STATE-level scheme belongs to (from its reviewed source), or None."""
    if str(getattr(scheme, "government_level", "") or "").upper() != "STATE":
        return None
    sources = sorted(getattr(scheme, "sources", None) or [],
                     key=lambda s: 0 if getattr(s, "status", "") == "VERIFIED" else 1)
    for source in sources:
        state = canonical_state(getattr(source, "jurisdiction", None))
        if state:
            return state
    return None


def _apply_jurisdiction(result, scheme_state_name, user_state):
    if user_state is None:
        if result["status"] != "NOT_ELIGIBLE":
            result["status"] = "NEEDS_INFORMATION"
            result["missing_fields"] = sorted(set(result["missing_fields"]) | {"state"})
        return result
    if user_state != scheme_state_name:
        result["status"] = "NOT_ELIGIBLE"
        result["failed_conditions"] = result["failed_conditions"] + [
            {"field": "state", "operator": "==", "expected": scheme_state_name, "actual": user_state}]
        result["missing_fields"] = []
        return result
    result["reasons"] = result["reasons"] + [f"state == {scheme_state_name} (actual: {user_state})"]
    return result


def evaluate_scheme(scheme, rule_json, memory):
    """Evaluate one scheme for one citizen. Returns the rule-engine dict plus jurisdiction + manual_checks."""
    memory = normalize_memory(memory)
    result = evaluate_rule(normalize_rule(rule_json), memory)
    state = scheme_state(scheme)
    if state:
        result = _apply_jurisdiction(result, state, canonical_state(memory.get("state")) or memory.get("state"))
    manual = list(getattr(scheme, "manual_checks", None) or [])
    if str(getattr(scheme, "government_level", "") or "").upper() == "STATE" and not state:
        manual.append("Confirm this state scheme is available in your state.")
    result["jurisdiction"] = state
    result["manual_checks"] = manual
    return result


def rule_to_text(node):
    """Human-readable form of a rule tree, so a reviewer can compare it with the official text."""
    if not isinstance(node, dict):
        return str(node)
    if "field" in node:
        field, op, value = node["field"], node.get("operator"), node.get("value")
        if op == "between" and isinstance(value, list) and len(value) == 2:
            return f"{field} between {value[0]} and {value[1]}"
        return f"{field} {op} {value}"
    parts = [rule_to_text(child) for child in node.get("conditions", [])]
    if node.get("logic") == "NOT":
        return "NOT (" + " ".join(parts) + ")"
    return "(" + f" {node.get('logic')} ".join(parts) + ")"
