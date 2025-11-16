from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from dotenv import load_dotenv
import os

load_dotenv()  # .env dosyasını yükle

app = Flask(__name__)
CORS(app)

# --- DATABASE URL DÜZELTME ---
db_url = os.getenv("DATABASE_URL", "")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Supabase genelde SSL ister — yoksa bağlanmaz
if "sslmode" not in db_url:
    db_url += "?sslmode=require"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# SQLALCHEMY ENGINE OPTIONS (pool ayarları güvenli)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 5,
    "max_overflow": 10,
    "pool_pre_ping": True,
}

db = SQLAlchemy(app)

# Rate limit
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["100 per hour"]
)

# Session
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


# --------- TEST MODEL ---------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False)

with app.app_context():
    db.create_all()


# --------- TEST ROUTE ---------
@app.route("/")
def home():
    return jsonify({"message": "Server working!"})


@app.route("/add-user", methods=["POST"])
def add_user():
    data = request.json
    u = User(username=data["username"])
    db.session.add(u)
    db.session.commit()
    return jsonify({"status": "ok"})


# --------- RUN ---------
if __name__ == "__main__":
    app.run(debug=True)
