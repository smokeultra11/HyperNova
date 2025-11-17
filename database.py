from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import json

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    premium_until = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_premium(self):
        return self.premium_until > datetime.utcnow()

class Chat(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    messages = db.Column(db.Text, nullable=False)  # JSON string
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'messages': json.loads(self.messages),
            'last_updated': self.last_updated.isoformat()
        }

# Admin init fonksiyonu (utils'e taşındı)
DEVELOPER_USERNAME = "yuiouo"
DEVELOPER_PASSWORD_HASH = generate_password_hash("TheLastGalaxy*")
