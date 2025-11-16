# app.py
from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from dotenv import load_dotenv
import os

# Models ve Routes
from models import db
from routes import create_auth_bp, create_chat_bp, create_admin_bp

# --- Load environment ---
load_dotenv()

app = Flask(__name__)
CORS(app)

# --- Configs ---
# Secret key
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "some-random-secret-key")

# Database
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if "sslmode" not in db_url:
    db_url += "?sslmode=require"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_size": 5,
    "max_overflow": 10,
    "pool_pre_ping": True,
}

# Initialize DB
db.init_app(app)

# Rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["100 per hour"]
)

# Session
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# --- Register Blueprints ---
app.register_blueprint(create_auth_bp())
app.register_blueprint(create_chat_bp(limiter))
app.register_blueprint(create_admin_bp())

# --- Default route ---
@app.route("/")
def home():
    return "Welcome to the Chat API! Visit /admin for admin panel."

# --- Create tables on first run ---
with app.app_context():
    db.create_all()

# --- Run ---
if __name__ == "__main__":
    app.run(debug=True)
