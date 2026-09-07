"""
Database models for the Scheme Eligibility Memory Agent.

Design notes for the team:
- CitizenProfile is the agent's "persistent memory" of the citizen — see
  to_memory_dict() and missing_fields(), which agent/memory.py will call.
- EligibilityRule.rule_json stores the actual rule tree consumed by
  agent/rule_engine.py. It uses SQLAlchemy's JSON type, which SQLAlchemy
  serializes to/from text automatically on SQLite — you get/set it as a
  normal Python dict, no manual json.dumps/loads needed.
- EligibilityEvaluation stores every run of the rule engine so we have
  history + can diff old vs new status for change detection.
- Notification.citizen_id points at User.id (not CitizenProfile.id) so we
  can notify a user even before their profile is fully filled in.
"""

from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from database.db import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="citizen")  # citizen | admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    profile = db.relationship(
        "CitizenProfile",
        backref="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    notifications = db.relationship(
        "Notification",
        backref="user",
        cascade="all, delete-orphan",
        order_by="Notification.created_at.desc()",
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class CitizenProfile(db.Model):
    __tablename__ = "citizen_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)

    full_name = db.Column(db.String(120))
    date_of_birth = db.Column(db.Date)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(20))
    state = db.Column(db.String(80))
    district = db.Column(db.String(80))
    annual_income = db.Column(db.Float)
    occupation = db.Column(db.String(80))
    education_level = db.Column(db.String(80))
    family_size = db.Column(db.Integer)
    marital_status = db.Column(db.String(30))
    disability_status = db.Column(db.Boolean)
    student_status = db.Column(db.Boolean)
    employment_status = db.Column(db.String(30))
    category = db.Column(db.String(30))  # e.g. GENERAL / OBC / SC / ST
    farmer_status = db.Column(db.Boolean)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    evaluations = db.relationship(
        "EligibilityEvaluation",
        backref="citizen",
        cascade="all, delete-orphan",
        order_by="EligibilityEvaluation.evaluated_at.desc()",
    )

    # Fields the rule engine is allowed to reason over. Keep this list in
    # sync with the columns above — agent/memory.py and rule_engine.py both
    # rely on it.
    RULE_FIELDS = [
        "age",
        "gender",
        "state",
        "district",
        "annual_income",
        "occupation",
        "education_level",
        "family_size",
        "marital_status",
        "disability_status",
        "student_status",
        "employment_status",
        "category",
        "farmer_status",
    ]

    def to_memory_dict(self) -> dict:
        """
        Flatten the profile into the dict the rule engine and agent consume
        as the citizen's stored "memory". This is the single source of
        truth other modules should use instead of touching columns directly.
        """
        return {field: getattr(self, field) for field in self.RULE_FIELDS}

    def missing_fields(self, required_fields=None) -> list:
        """
        Which memory fields are still unset. If required_fields is given
        (e.g. the fields a specific scheme's rule references), only check
        those; otherwise check every rule field.
        """
        data = self.to_memory_dict()
        fields_to_check = required_fields if required_fields is not None else self.RULE_FIELDS
        return [f for f in fields_to_check if data.get(f) is None]

    def completion_percentage(self) -> int:
        total = len(self.RULE_FIELDS)
        filled = total - len(self.missing_fields())
        return round((filled / total) * 100) if total else 0

    def to_dict(self):
        d = self.to_memory_dict()
        d.update(
            {
                "id": self.id,
                "user_id": self.user_id,
                "full_name": self.full_name,
                "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }
        )
        return d

    def __repr__(self):
        return f"<CitizenProfile user_id={self.user_id}>"


class Scheme(db.Model):
    __tablename__ = "schemes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    department = db.Column(db.String(120))
    government_level = db.Column(db.String(30))  # e.g. CENTRAL / STATE / DEMO
    category = db.Column(db.String(80))
    benefits = db.Column(db.Text)
    application_url = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    rule_version = db.Column(db.Integer, default=1)  # convenience pointer to current rule version

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rules = db.relationship(
        "EligibilityRule",
        backref="scheme",
        cascade="all, delete-orphan",
        order_by="EligibilityRule.version",
    )
    evaluations = db.relationship(
        "EligibilityEvaluation", backref="scheme", cascade="all, delete-orphan"
    )
    notifications = db.relationship("Notification", backref="scheme")

    def latest_rule(self):
        """Return the highest-version EligibilityRule for this scheme, or None."""
        if not self.rules:
            return None
        return max(self.rules, key=lambda r: r.version)

    def to_dict(self, include_rule=False):
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "department": self.department,
            "government_level": self.government_level,
            "category": self.category,
            "benefits": self.benefits,
            "application_url": self.application_url,
            "active": self.active,
            "rule_version": self.rule_version,
        }
        if include_rule:
            rule = self.latest_rule()
            d["rule_json"] = rule.rule_json if rule else None
        return d

    def __repr__(self):
        return f"<Scheme {self.name}>"


class EligibilityRule(db.Model):
    __tablename__ = "eligibility_rules"

    id = db.Column(db.Integer, primary_key=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id"), nullable=False)

    # Rule tree, e.g.:
    # {"logic": "AND", "conditions": [{"field": "age", "operator": ">=", "value": 18}, ...]}
    # SQLAlchemy's JSON type stores/loads this as a plain Python dict.
    rule_json = db.Column(db.JSON, nullable=False)

    version = db.Column(db.Integer, nullable=False, default=1)
    effective_from = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<EligibilityRule scheme_id={self.scheme_id} v{self.version}>"


class EligibilityEvaluation(db.Model):
    __tablename__ = "eligibility_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey("citizen_profiles.id"), nullable=False)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id"), nullable=False)

    status = db.Column(db.String(30), nullable=False)  # ELIGIBLE | NOT_ELIGIBLE | NEEDS_INFORMATION
    reasons = db.Column(db.JSON, default=list)
    failed_conditions = db.Column(db.JSON, default=list)
    missing_fields = db.Column(db.JSON, default=list)
    rule_version = db.Column(db.Integer)

    evaluated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "citizen_id": self.citizen_id,
            "scheme_id": self.scheme_id,
            "status": self.status,
            "reasons": self.reasons or [],
            "failed_conditions": self.failed_conditions or [],
            "missing_fields": self.missing_fields or [],
            "rule_version": self.rule_version,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
        }

    def __repr__(self):
        return f"<Evaluation citizen={self.citizen_id} scheme={self.scheme_id} {self.status}>"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id"), nullable=True)

    title = db.Column(db.String(200))
    message = db.Column(db.Text)
    notification_type = db.Column(db.String(30))
    # NEW_ELIGIBILITY | RULE_CHANGE | PROFILE_CHANGE | GENERAL

    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "scheme_id": self.scheme_id,
            "title": self.title,
            "message": self.message,
            "notification_type": self.notification_type,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Notification {self.notification_type} for user={self.citizen_id}>"
