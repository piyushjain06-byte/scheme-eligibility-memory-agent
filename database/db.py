from flask_sqlalchemy import SQLAlchemy

# Single shared SQLAlchemy instance.
# Import this `db` object everywhere (models.py, app.py, services, routes) —
# never create a second SQLAlchemy() instance.
db = SQLAlchemy()
