"""
Unit tests for agent/rule_engine.py — pure function, no DB / app context
needed. Run with: python -m pytest tests/test_rule_engine.py -v
"""

import pytest

from agent.rule_engine import evaluate_rule, InvalidRuleError


# ---------------------------------------------------------------------
# Basic operators
# ---------------------------------------------------------------------

def test_equals_operator_true():
    rule = {"logic": "AND", "conditions": [{"field": "gender", "operator": "==", "value": "female"}]}
    result = evaluate_rule(rule, {"gender": "female"})
    assert result["status"] == "ELIGIBLE"
    assert result["failed_conditions"] == []
    assert result["missing_fields"] == []


def test_equals_operator_false():
    rule = {"logic": "AND", "conditions": [{"field": "gender", "operator": "==", "value": "female"}]}
    result = evaluate_rule(rule, {"gender": "male"})
    assert result["status"] == "NOT_ELIGIBLE"
    assert result["failed_conditions"][0]["field"] == "gender"


def test_not_equals_operator():
    rule = {"logic": "AND", "conditions": [{"field": "occupation", "operator": "!=", "value": "farmer"}]}
    assert evaluate_rule(rule, {"occupation": "teacher"})["status"] == "ELIGIBLE"
    assert evaluate_rule(rule, {"occupation": "farmer"})["status"] == "NOT_ELIGIBLE"


@pytest.mark.parametrize(
    "operator,threshold,actual,expected_status",
    [
        ("<", 30, 25, "ELIGIBLE"),
        ("<", 30, 30, "NOT_ELIGIBLE"),
        ("<=", 30, 30, "ELIGIBLE"),
        ("<=", 30, 31, "NOT_ELIGIBLE"),
        (">", 60, 65, "ELIGIBLE"),
        (">", 60, 60, "NOT_ELIGIBLE"),
        (">=", 60, 60, "ELIGIBLE"),
        (">=", 60, 59, "NOT_ELIGIBLE"),
    ],
)
def test_numeric_comparison_operators(operator, threshold, actual, expected_status):
    rule = {"logic": "AND", "conditions": [{"field": "age", "operator": operator, "value": threshold}]}
    assert evaluate_rule(rule, {"age": actual})["status"] == expected_status


def test_between_operator_inclusive_bounds():
    rule = {"logic": "AND", "conditions": [{"field": "age", "operator": "between", "value": [18, 25]}]}
    assert evaluate_rule(rule, {"age": 18})["status"] == "ELIGIBLE"
    assert evaluate_rule(rule, {"age": 25})["status"] == "ELIGIBLE"
    assert evaluate_rule(rule, {"age": 17})["status"] == "NOT_ELIGIBLE"
    assert evaluate_rule(rule, {"age": 26})["status"] == "NOT_ELIGIBLE"


def test_in_operator():
    rule = {"logic": "AND", "conditions": [{"field": "category", "operator": "in", "value": ["SC", "ST", "OBC"]}]}
    assert evaluate_rule(rule, {"category": "SC"})["status"] == "ELIGIBLE"
    assert evaluate_rule(rule, {"category": "GENERAL"})["status"] == "NOT_ELIGIBLE"


def test_unsupported_operator_raises():
    rule = {"logic": "AND", "conditions": [{"field": "age", "operator": "~=", "value": 10}]}
    with pytest.raises(InvalidRuleError):
        evaluate_rule(rule, {"age": 10})


# ---------------------------------------------------------------------
# AND / OR / NOT logic + nesting
# ---------------------------------------------------------------------

def test_and_logic_all_satisfied():
    rule = {
        "logic": "AND",
        "conditions": [
            {"field": "age", "operator": "between", "value": [18, 25]},
            {"field": "student_status", "operator": "==", "value": True},
            {"field": "annual_income", "operator": "<=", "value": 250000},
        ],
    }
    memory = {"age": 20, "student_status": True, "annual_income": 200000}
    result = evaluate_rule(rule, memory)
    assert result["status"] == "ELIGIBLE"
    assert len(result["reasons"]) == 3


def test_and_logic_one_fails_short_circuits_even_with_missing_field():
    """A known failure makes the verdict NOT_ELIGIBLE regardless of what
    else is missing — filling in the missing field can't change the
    outcome, so the agent shouldn't bother asking for it."""
    rule = {
        "logic": "AND",
        "conditions": [
            {"field": "age", "operator": ">=", "value": 60},
            {"field": "annual_income", "operator": "<=", "value": 100000},
        ],
    }
    memory = {"age": 40}  # fails age; annual_income unknown
    result = evaluate_rule(rule, memory)
    assert result["status"] == "NOT_ELIGIBLE"
    assert result["missing_fields"] == []


def test_and_logic_missing_field_when_no_known_failure():
    rule = {
        "logic": "AND",
        "conditions": [
            {"field": "age", "operator": ">=", "value": 60},
            {"field": "annual_income", "operator": "<=", "value": 100000},
        ],
    }
    memory = {"age": 65}  # age passes; income unknown
    result = evaluate_rule(rule, memory)
    assert result["status"] == "NEEDS_INFORMATION"
    assert result["missing_fields"] == ["annual_income"]


def test_or_logic_one_satisfied_is_enough():
    rule = {
        "logic": "OR",
        "conditions": [
            {"field": "farmer_status", "operator": "==", "value": True},
            {"field": "occupation", "operator": "==", "value": "farmer"},
        ],
    }
    assert evaluate_rule(rule, {"farmer_status": True, "occupation": None})["status"] == "ELIGIBLE"
    assert evaluate_rule(rule, {"farmer_status": False, "occupation": "farmer"})["status"] == "ELIGIBLE"


def test_or_logic_all_false():
    rule = {
        "logic": "OR",
        "conditions": [
            {"field": "farmer_status", "operator": "==", "value": True},
            {"field": "occupation", "operator": "==", "value": "farmer"},
        ],
    }
    result = evaluate_rule(rule, {"farmer_status": False, "occupation": "teacher"})
    assert result["status"] == "NOT_ELIGIBLE"


def test_or_logic_needs_information_when_nothing_true_yet():
    rule = {
        "logic": "OR",
        "conditions": [
            {"field": "farmer_status", "operator": "==", "value": True},
            {"field": "occupation", "operator": "==", "value": "farmer"},
        ],
    }
    result = evaluate_rule(rule, {"farmer_status": False, "occupation": None})
    assert result["status"] == "NEEDS_INFORMATION"
    assert result["missing_fields"] == ["occupation"]


def test_not_logic_inverts_true_to_false():
    rule = {"logic": "NOT", "conditions": [{"field": "disability_status", "operator": "==", "value": True}]}
    result = evaluate_rule(rule, {"disability_status": True})
    assert result["status"] == "NOT_ELIGIBLE"


def test_not_logic_inverts_false_to_true():
    rule = {"logic": "NOT", "conditions": [{"field": "disability_status", "operator": "==", "value": True}]}
    result = evaluate_rule(rule, {"disability_status": False})
    assert result["status"] == "ELIGIBLE"


def test_not_logic_missing_stays_needs_information():
    rule = {"logic": "NOT", "conditions": [{"field": "disability_status", "operator": "==", "value": True}]}
    result = evaluate_rule(rule, {"disability_status": None})
    assert result["status"] == "NEEDS_INFORMATION"


def test_nested_and_or_combination():
    # ELIGIBLE if (age between 18-35 AND student) OR (farmer_status)
    rule = {
        "logic": "OR",
        "conditions": [
            {
                "logic": "AND",
                "conditions": [
                    {"field": "age", "operator": "between", "value": [18, 35]},
                    {"field": "student_status", "operator": "==", "value": True},
                ],
            },
            {"field": "farmer_status", "operator": "==", "value": True},
        ],
    }
    # Fails the AND branch but satisfies the OR branch via farmer_status
    memory = {"age": 50, "student_status": False, "farmer_status": True}
    assert evaluate_rule(rule, memory)["status"] == "ELIGIBLE"

    # Fails everything known
    memory2 = {"age": 50, "student_status": False, "farmer_status": False}
    assert evaluate_rule(rule, memory2)["status"] == "NOT_ELIGIBLE"


# ---------------------------------------------------------------------
# Missing field handling
# ---------------------------------------------------------------------

def test_all_fields_missing():
    rule = {"logic": "AND", "conditions": [{"field": "age", "operator": ">=", "value": 18}]}
    result = evaluate_rule(rule, {})
    assert result["status"] == "NEEDS_INFORMATION"
    assert result["missing_fields"] == ["age"]


def test_multiple_missing_fields_deduplicated_and_sorted():
    rule = {
        "logic": "AND",
        "conditions": [
            {"field": "annual_income", "operator": "<=", "value": 200000},
            {"field": "family_size", "operator": ">=", "value": 4},
        ],
    }
    result = evaluate_rule(rule, {})
    assert result["missing_fields"] == ["annual_income", "family_size"]


# ---------------------------------------------------------------------
# Malformed rules
# ---------------------------------------------------------------------

def test_invalid_logic_raises():
    with pytest.raises(InvalidRuleError):
        evaluate_rule({"logic": "XOR", "conditions": [{"field": "age", "operator": "==", "value": 1}]}, {})


def test_empty_conditions_raises():
    with pytest.raises(InvalidRuleError):
        evaluate_rule({"logic": "AND", "conditions": []}, {})


def test_leaf_missing_operator_raises():
    with pytest.raises(InvalidRuleError):
        evaluate_rule({"logic": "AND", "conditions": [{"field": "age", "value": 18}]}, {})


def test_not_logic_with_multiple_children_raises():
    rule = {
        "logic": "NOT",
        "conditions": [
            {"field": "age", "operator": "==", "value": 1},
            {"field": "gender", "operator": "==", "value": "x"},
        ],
    }
    with pytest.raises(InvalidRuleError):
        evaluate_rule(rule, {"age": 1, "gender": "x"})


# ---------------------------------------------------------------------
# Real demo scheme rules (regression against actual seed data)
# ---------------------------------------------------------------------

def test_real_scheme_student_education_support():
    rule = {
        "logic": "AND",
        "conditions": [
            {"field": "age", "operator": "between", "value": [18, 25]},
            {"field": "student_status", "operator": "==", "value": True},
            {"field": "annual_income", "operator": "<=", "value": 250000},
        ],
    }
    eligible_memory = {"age": 21, "student_status": True, "annual_income": 150000}
    assert evaluate_rule(rule, eligible_memory)["status"] == "ELIGIBLE"

    too_old_memory = {"age": 30, "student_status": True, "annual_income": 150000}
    assert evaluate_rule(rule, too_old_memory)["status"] == "NOT_ELIGIBLE"