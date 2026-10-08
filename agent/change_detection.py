"""Re-evaluation and newly-eligible change detection (run by an admin, after a rule is approved, or by cron)."""
from database.db import db
from database.models import CitizenProfile, EligibilityEvaluation, Notification
from agent.eligibility import evaluate_scheme
from agent.memory import get_memory_dict


def reevaluate_scheme(scheme, record_unchanged=True):
    """Re-run one scheme for all citizens. record_unchanged=False skips storing identical repeat results."""
    rule = scheme.latest_rule()
    if rule is None:
        return {"evaluated": 0, "newly_eligible": 0, "error": "Scheme has no eligibility rule"}
    evaluated = newly_eligible = 0
    for profile in CitizenProfile.query.order_by(CitizenProfile.id).all():
        previous = EligibilityEvaluation.query.filter_by(
            citizen_id=profile.id, scheme_id=scheme.id
        ).order_by(EligibilityEvaluation.evaluated_at.desc(), EligibilityEvaluation.id.desc()).first()
        current = evaluate_scheme(scheme, rule.rule_json, get_memory_dict(profile.user_id))
        if (not record_unchanged and previous is not None and previous.status == current["status"]
                and previous.rule_version == rule.version and (previous.reasons or []) == current["reasons"]
                and (previous.missing_fields or []) == current["missing_fields"]
                and (previous.failed_conditions or []) == current["failed_conditions"]):
            evaluated += 1
            continue
        result = EligibilityEvaluation(
            citizen_id=profile.id, scheme_id=scheme.id, status=current["status"],
            reasons=current["reasons"], failed_conditions=current["failed_conditions"],
            missing_fields=current["missing_fields"], rule_version=rule.version,
        )
        db.session.add(result)
        evaluated += 1
        if current["status"] == "ELIGIBLE" and (previous is None or previous.status != "ELIGIBLE"):
            db.session.add(Notification(
                citizen_id=profile.user_id, scheme_id=scheme.id,
                title="You may now qualify for a scheme",
                message=f"Your latest eligibility check for {scheme.name} returned ELIGIBLE. Review current official requirements before applying.",
                notification_type="NEW_ELIGIBILITY",
            ))
            newly_eligible += 1
    db.session.commit()
    return {"evaluated": evaluated, "newly_eligible": newly_eligible, "rule_version": rule.version}