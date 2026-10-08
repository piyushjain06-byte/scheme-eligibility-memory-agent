"""
Database models for the Scheme Eligibility Memory Agent.

Design notes for the team:
- CitizenProfile is the single source of truth for the citizen's structured memory. UserMemory rows are a
  metadata layer on top of it (where a fact came from, whether the user confirmed it, when it was last
  checked); agent/memory.py keeps the two in sync.
- Age is derived from date_of_birth when one is known, so it never goes stale.
- EligibilityRule.rule_json stores the rule tree consumed by agent/rule_engine.py (SQLAlchemy JSON type).
- EligibilityEvaluation stores runs of the rule engine so old and new status can be diffed.
- Notification.citizen_id points at User.id (not CitizenProfile.id).
"""

from datetime import date, datetime, timezone

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
    consent_at = db.Column(db.DateTime)  # when the citizen agreed to store their profile details

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
    conversations = db.relationship("Conversation", backref="user", cascade="all, delete-orphan")
    memory_facts = db.relationship("UserMemory", backref="user", cascade="all, delete-orphan")

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
            "consent_at": self.consent_at.isoformat() if self.consent_at else None,
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
    category = db.Column(db.String(30))  # e.g. GENERAL / OBC / SC / ST / EWS
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

    def current_age(self, today=None):
        """Age today: computed from date_of_birth when known, otherwise the stored value."""
        if self.date_of_birth:
            today = today or date.today()
            dob = self.date_of_birth
            return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return self.age

    def to_memory_dict(self) -> dict:
        """
        Flatten the profile into the dict the rule engine and agent consume
        as the citizen's stored "memory". This is the single source of
        truth other modules should use instead of touching columns directly.
        """
        data = {field: getattr(self, field) for field in self.RULE_FIELDS}
        data["age"] = self.current_age()
        return data

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
    ministry = db.Column(db.String(160))
    objective = db.Column(db.Text)
    eligibility = db.Column(db.Text)
    required_documents = db.Column(db.JSON, default=list)
    application_process = db.Column(db.Text)
    source_url = db.Column(db.String(1000))
    last_updated = db.Column(db.Date)
    source_verified = db.Column(db.Boolean, default=False, nullable=False)
    source_type = db.Column(db.String(40))
    scheme_status = db.Column(db.String(40), default="ACTIVE")
    exclusions = db.Column(db.Text)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    last_verified = db.Column(db.DateTime)
    rule_version = db.Column(db.Integer, default=1)  # convenience pointer to current rule version
    # Criteria the 14 profile fields cannot express (BPL card, land holding, ...). Shown to the citizen as
    # "check these yourself" so they are never silently skipped.
    manual_checks = db.Column(db.JSON, default=list)

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
    documents = db.relationship("GovernmentDocument", backref="scheme", cascade="all, delete-orphan")

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
            "ministry": self.ministry,
            "objective": self.objective,
            "eligibility": self.eligibility,
            "required_documents": self.required_documents or [],
            "application_process": self.application_process,
            "source_url": self.source_url,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "source_verified": self.source_verified,
            "source_type": self.source_type,
            "scheme_status": self.scheme_status,
            "exclusions": self.exclusions,
            "is_demo": self.is_demo,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
            "manual_checks": self.manual_checks or [],
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


class SchemeSource(db.Model):
    """Official-source evidence used to ground answers about a scheme."""

    __tablename__ = "scheme_sources"

    id = db.Column(db.Integer, primary_key=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id"), nullable=False)
    source_url = db.Column(db.String(1000), nullable=False)
    source_title = db.Column(db.String(255), nullable=False)
    publisher = db.Column(db.String(255), nullable=False)
    excerpt = db.Column(db.Text, nullable=False)
    jurisdiction = db.Column(db.String(100), nullable=False)  # a state/UT name for STATE schemes, else "India"
    proposed_rule_json = db.Column(db.JSON)
    rule_version = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    retrieved_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    source_type = db.Column(db.String(40), default="OFFICIAL_PAGE")
    last_verified = db.Column(db.DateTime)

    scheme = db.relationship("Scheme", backref=db.backref("sources", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "scheme_id": self.scheme_id,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "publisher": self.publisher,
            "jurisdiction": self.jurisdiction,
            "excerpt": self.excerpt,
            "rule_version": self.rule_version,
            "status": self.status,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes": self.review_notes,
            "source_type": self.source_type,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
        }

    def __repr__(self):
        return f"<SchemeSource scheme_id={self.scheme_id} status={self.status}>"


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


class GovernmentDocument(db.Model):
    """Source document text retained for retrieval and citation tracking."""

    __tablename__ = "government_documents"
    id = db.Column(db.Integer, primary_key=True)
    scheme_id = db.Column(db.Integer, db.ForeignKey("schemes.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    source_url = db.Column(db.String(1000))
    source_type = db.Column(db.String(40))
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    verification_status = db.Column(db.String(20), nullable=False, default="DEMO")
    is_current = db.Column(db.Boolean, nullable=False, default=True, index=True)
    last_updated = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    chunks = db.relationship("DocumentChunk", backref="document", cascade="all, delete-orphan")


class DocumentChunk(db.Model):
    __tablename__ = "document_chunks"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("government_documents.id"), nullable=False, index=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    embedding = db.Column(db.JSON)
    __table_args__ = (db.UniqueConstraint("document_id", "chunk_index"),)


class Conversation(db.Model):
    __tablename__ = "conversations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(160))
    # Scheme ids the last answer was about, so a follow-up like "what documents do I need?" knows the topic
    # without forwarding earlier user messages to the hosted model.
    focus_scheme_ids = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    messages = db.relationship("Message", backref="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class UserMemory(db.Model):
    """
    Metadata about one remembered fact. The VALUE lives on CitizenProfile (single source of truth);
    agent/memory.py keeps this row in sync and records where it came from and whether the user confirmed it.
    """
    __tablename__ = "user_memory"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    key = db.Column(db.String(80), nullable=False)
    value = db.Column(db.JSON, nullable=False)
    source_message_id = db.Column(db.Integer, db.ForeignKey("messages.id"))
    source = db.Column(db.String(20), default="chat")  # chat | profile
    confirmed = db.Column(db.Boolean, nullable=False, default=False)
    last_confirmed_at = db.Column(db.DateTime)
    previous_value = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "key"),)


class IngestionRun(db.Model):
    """Small audit trail for admin-triggered imports and their validation errors."""
    __tablename__ = "ingestion_runs"
    id = db.Column(db.Integer, primary_key=True)
    initiated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    source_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="RUNNING")
    result = db.Column(db.JSON)
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime)