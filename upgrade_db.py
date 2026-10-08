"""Create new tables and add the new columns without dropping data."""

from sqlalchemy import inspect, text
from app import create_app
from database.db import db
from database.models import Conversation, GovernmentDocument, Scheme, User, UserMemory


def upgrade_existing_schema():
    db.create_all()
    quote = db.engine.dialect.identifier_preparer.quote
    with db.engine.begin() as connection:
        inspector = inspect(db.engine)
        for model in (Scheme, GovernmentDocument, User, Conversation, UserMemory):
            existing = {column["name"] for column in inspector.get_columns(model.__tablename__)}
            for column in model.__table__.columns:
                if column.name in existing or column.primary_key or column.name == "id":
                    continue
                sql_type = column.type.compile(dialect=db.engine.dialect)
                nullable = "" if column.nullable else " NOT NULL"
                default = " DEFAULT 0" if column.name in {"is_demo", "source_verified", "confirmed"} else (" DEFAULT 1" if column.name == "is_current" else "")
                connection.execute(text(
                    f"ALTER TABLE {quote(model.__tablename__)} ADD COLUMN {quote(column.name)} {sql_type}{nullable}{default}"
                ))
                existing.add(column.name)


def main():
    app = create_app()
    with app.app_context():
        upgrade_existing_schema()
        print("Database schema is up to date.")


if __name__ == "__main__":
    main()