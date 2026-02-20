from flask import Flask, request, jsonify, send_from_directory, session
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
import bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import tensorflow as tf
import numpy as np
import base64, io, cv2, json, os
from PIL import Image
import math
import random  # if you later want server-chosen prompts
import re
import secrets
from functools import wraps

# set up flask and static folder
app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.secret_key = "supersecretkey"
from flask_cors import CORS
CORS(app, supports_credentials=True)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://" # Using in-memory storage for simplicity
)

# mongodb configuration
app.config["MONGO_URI"] = "mongodb://localhost:27017/girlwhoisyou"
mongo = PyMongo(app)
users = mongo.db.users

MODEL_PATH = "model/doodle_model.h5"
LABEL_MAP_PATH = "model/label_map.json"
IMG_SIZE = 28

# Load model and labels
model = tf.keras.models.load_model(MODEL_PATH, safe_mode=False)
with open(LABEL_MAP_PATH, "r") as f:
    label_data = json.load(f)
classes = label_data["labels"]

print(f"Loaded model: {MODEL_PATH}")
print(f"Classes: {classes}")

# --- Human-behavior heuristic thresholds (tune as needed) ---
MIN_DRAW_TIME_MS = 1000     # must draw at least 1s
MAX_DRAW_TIME_MS = 60000    # cap at 60s
MIN_PATH_POINTS  = 15       # at least 15 recorded points
MIN_PATH_LENGTH  = 50.0    # total drawn pixels
MAX_AVG_SPEED    = 5.0      # pixels per millisecond (very fast if > 5)
MIN_SPEED_STD    = 0.05     # speed should vary a bit (bots draw too consistently)

def preprocess_base64_image(b64_str):
    """Convert base64 canvas image to model input (28x28 grayscale, centered, normalized)."""
    if ',' in b64_str:
        b64_str = b64_str.split(',')[1]
    img_bytes = base64.b64decode(b64_str)
    img = Image.open(io.BytesIO(img_bytes)).convert('L')
    arr = np.array(img)

    # Invert colors: canvas black=0, model expects white=1
    arr = 255 - arr

    # Threshold to binary
    _, binary = cv2.threshold(arr, 50, 255, cv2.THRESH_BINARY)

    # Crop to bounding box
    coords = cv2.findNonZero(binary)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        arr = arr[y:y+h, x:x+w]

    # Resize to 28x28
    arr = cv2.resize(arr, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)

    # Normalize to 0-1
    arr = arr.astype("float32") / 255.0
    arr = arr.reshape(1, IMG_SIZE, IMG_SIZE, 1)
    return arr

def predict_class(b64_str):
    tensor = preprocess_base64_image(b64_str)
    preds = model.predict(tensor)
    class_idx = np.argmax(preds)
    confidence = float(np.max(preds))
    return classes[class_idx], confidence

@app.route("/get_captcha")
@limiter.limit("120 per minute") # Rate limit the challenge generation itself
def get_captcha_challenge():
    """Generates a random challenge and a one-time token."""
    
    # This selects a random class from your loaded 'classes' list
    challenge = np.random.choice(classes) 
    
    # Generate a secure one-time token
    one_time_token = secrets.token_urlsafe(16) 
    
    # Store the token and challenge in the session
    session["captcha_token"] = one_time_token
    session["captcha_challenge"] = challenge # Store the challenge on the server side
    
    return jsonify({
        "success": True, 
        "challenge": challenge, 
        "token": one_time_token
    })

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/signup", methods=["GET"])
def signup_page():
    return send_from_directory(app.static_folder, "signup.html")
@app.route("/signup", methods=["POST"])
@limiter.limit("5 per hour") # Limit signup attempts from one IP
def signup_user():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email", "").lower()
    password = data.get("password")
    question = data.get("security_question")  # dropdown selected value
    answer = data.get("security_answer", "").lower()

    if not all([name, email, password, question, answer]):
        return jsonify({"success": False, "message": "All fields are required"}), 400

    # Email format check (basic)
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "message": "Invalid email format"}), 400
    
    # Password minimum length check
    if len(password) < 8:
        return jsonify({"success": False, "message": "Password must be at least 8 characters long"}), 400
    # ----------------------------

    if users.find_one({"email": email}):
        return jsonify({"success": False, "message": "Email already registered"}), 400

    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    users.insert_one({
        "name": name,
        "email": email,
        "password": hashed_pw,
        "security_question": question,
        "security_answer": answer,
        "stats": {"captchas_completed": 0, "average_time": 0, "best_prompt": ""},
        "gallery": []
    })

    return jsonify({"success": True, "message": "Signup successful!"})

# -------------------------------------------
# 🔐 Password Reset / Forgot Password
# -------------------------------------------

@app.route("/forgot", methods=["GET"])
def forgot_page():
    """Serve forgot password page from frontend."""
    return send_from_directory(app.static_folder, "forgot.html")


@app.route("/forgot_password", methods=["POST"])
def forgot_password():
    """Return security question for the given email."""
    data = request.get_json()
    email = data.get("email", "").lower()

    user = users.find_one({"email": email})
    if not user:
        return jsonify({"success": False, "message": "No account found with that email."}), 404

    return jsonify({"success": True, "question": user.get("security_question", "No question set")})


@app.route("/reset_password", methods=["POST"])
def reset_password():
    """Validate security answer and update password."""
    data = request.get_json()
    email = data.get("email", "").lower()
    answer = data.get("security_answer", "").lower().strip()
    new_password = data.get("new_password", "")

    user = users.find_one({"email": email})
    if not user:
        return jsonify({"success": False, "message": "No account found."}), 404

    if user.get("security_answer", "").lower() != answer:
        return jsonify({"success": False, "message": "Incorrect answer."}), 401

    if len(new_password) < 8:
        return jsonify({"success": False, "message": "Password must be at least 8 characters long."}), 400

    hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())
    users.update_one({"_id": user["_id"]}, {"$set": {"password": hashed_pw}})

    return jsonify({"success": True, "message": "Password reset successful!"})


@app.route("/change_password", methods=["POST"])
def change_password():
    """In-dashboard password change (requires login)."""
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Not logged in"}), 401

    data = request.get_json()
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")

    user = users.find_one({"_id": ObjectId(session["user_id"])})
    if not bcrypt.checkpw(old_pw.encode("utf-8"), user["password"]):
        return jsonify({"success": False, "message": "Old password incorrect."}), 401

    if len(new_pw) < 8:
        return jsonify({"success": False, "message": "New password must be at least 8 characters long."}), 400

    hashed_pw = bcrypt.hashpw(new_pw.encode("utf-8"), bcrypt.gensalt())
    users.update_one({"_id": user["_id"]}, {"$set": {"password": hashed_pw}})

    return jsonify({"success": True, "message": "Password changed successfully."})


def _path_length(path):
    """Total Euclidean distance of the path (pixels)."""
    if not path or len(path) < 2:
        return 0.0
    total = 0.0
    for i in range(len(path) - 1):
        x1, y1 = float(path[i]['x']), float(path[i]['y'])
        x2, y2 = float(path[i+1]['x']), float(path[i+1]['y'])
        total += math.hypot(x2 - x1, y2 - y1)
    return total

def _speed_stats(path):
    """Average speed and std-dev of speed (pixels/ms)."""
    v = []
    for i in range(len(path) - 1):
        x1, y1, t1 = float(path[i]['x']),  float(path[i]['y']),  float(path[i]['t'])
        x2, y2, t2 = float(path[i+1]['x']),float(path[i+1]['y']),float(path[i+1]['t'])
        dt = max(0.0001, t2 - t1)  # avoid div-by-zero
        dist = math.hypot(x2 - x1, y2 - y1)
        v.append(dist / dt)
    if len(v) < 2:
        return 0.0, 0.0
    avg = sum(v) / len(v)
    var = sum((vi - avg) ** 2 for vi in v) / len(v)
    return avg, math.sqrt(var)

def _pressure_variability(path):
    """Measure how much the user’s pen pressure varies."""
    pressures = [float(p.get('p', 0.5)) for p in path if 'p' in p]
    if len(pressures) < 2:
        return 0.0
    avg = sum(pressures) / len(pressures)
    var = sum((p - avg) ** 2 for p in pressures) / len(pressures)
    return math.sqrt(var)

@app.route("/verify", methods=["POST"])
@limiter.limit("120 per minute")
def verify():
    data = request.json
    print(f"Session ID: {session.sid if hasattr(session, 'sid') else 'no sid'}")

    # --- (2) Replay-attack protection ---
    required_keys = ["image", "token"]
    if not all(key in data for key in required_keys):
        print(f"❌ Missing keys")
        return jsonify({"success": False, "error": "Missing image or security token"}), 400

    submitted_token = data["token"]
    session_token = session.pop("captcha_token", None)
    server_challenge = session.pop("captcha_challenge", None)

    if not session_token or submitted_token != session_token:
        print(f"❌ Invalid or expired token")
        return jsonify({"success": False, "error": "Invalid or expired CAPTCHA token."}), 403

    if not server_challenge:
        print(f"❌ No CAPTCHA challenge found")
        return jsonify({"success": False, "error": "Missing CAPTCHA challenge in session."}), 403

    # Use the server-side challenge and client-provided image
    b64_image = data["image"]
    challenge = server_challenge

    # --- (3) Human-behavior heuristics ---
    drawing_time_ms = float(data.get("drawingTime", 0))
    path_data = data.get("pathData", [])

    print("\n🧩 Heuristic Report ----------------------")
    print(f"⏱️ Draw Time: {drawing_time_ms:.0f} ms")
    print(f"📊 Path Points: {len(path_data)}")
    print(f"📏 Path Length: {_path_length(path_data):.1f} px")
    avg_speed, std_speed = _speed_stats(path_data)
    pressure_var = _pressure_variability(path_data)
    print(f"⚡ Avg Speed: {avg_speed:.3f} px/ms | Speed StdDev: {std_speed:.3f}")
    print(f"✍️ Pressure Variation: {pressure_var:.4f}")
    print("------------------------------------------")

    # Timer check
    if not (MIN_DRAW_TIME_MS < drawing_time_ms < MAX_DRAW_TIME_MS):
        print(f"❌ Failed: Invalid drawing time")
        return jsonify({"success": False, "message": "Invalid drawing time. Please draw naturally."}), 400

    # Path complexity
    if not isinstance(path_data, list) or len(path_data) < MIN_PATH_POINTS:
        print(f"❌ Failed: Too few points")
        return jsonify({"success": False, "message": "Drawing too simple. Try a fuller sketch."}), 400

    total_len = _path_length(path_data)
    if total_len < MIN_PATH_LENGTH:
        print(f"❌ Failed: Path too short")
        return jsonify({"success": False, "message": "Drawing too short. Sketch more detail."}), 400

    # Speed dynamics
    if avg_speed > MAX_AVG_SPEED:
        print(f"❌ Failed: Too fast")
        return jsonify({"success": False, "message": "Too fast to be human. Slow down a bit."}), 400

    if std_speed < MIN_SPEED_STD:
        print(f"❌ Failed: Constant speed")
        return jsonify({"success": False, "message": "Stroke speed unusually constant."}), 400

    # Adaptive pressure heuristic
    if pressure_var < 0.0001 and all(abs(p.get("p", 0.5) - 0.5) < 1e-5 for p in path_data):
        print("⚠️ Skipping pressure heuristic — constant 0.5 (mouse device)")
    else:
        if pressure_var < 0.01:
            print(f"❌ Failed: Pressure too uniform")
            return jsonify({"success": False, "message": "Pressure pattern too uniform — looks automated."}), 400

    # --- (4) Model verification ---
    print("✅ Passed all human heuristics.")
    pred_class, confidence = predict_class(b64_image)
    success = (pred_class.lower() == challenge.lower()) and (confidence >= 0.8)

    if success:
        print("✅ CAPTCHA success.")
        if "user_id" in session:
            user_id = session["user_id"]
            user = users.find_one({"_id": ObjectId(user_id)}, {"stats": 1})
            is_new_best = not user or confidence > user["stats"].get("best_confidence", 0)
            update_data = {
                "$inc": {"stats.captchas_completed": 1},
                "$push": {"gallery": {"$each": [b64_image], "$slice": -10}}
            }
            if is_new_best:
                update_data["$set"] = {
                    "stats.best_confidence": confidence,
                    "stats.best_prompt": challenge
                }
            users.update_one({"_id": ObjectId(user_id)}, update_data)
            print("✅ User stats updated.")
    else:
        print(f"❌ CAPTCHA failed")
        return jsonify({
            "success": False,
            "message": "Incorrect CAPTCHA attempt."
        }), 401

    print(f"🎯 Prompt: {challenge} | Predicted: {pred_class} | Confidence: {confidence:.3f} | Success: {success}")
    return jsonify({
        "success": success,
        "predicted": pred_class,
        "confidence": round(confidence, 3)
    })

@app.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json()
    email = data.get("email", "").lower()
    password = data.get("password", "")

    user = users.find_one({"email": email})
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if not bcrypt.checkpw(password.encode("utf-8"), user["password"]):
        return jsonify({"success": False, "message": "Incorrect password"}), 401

    session["user_id"] = str(user["_id"])
    return jsonify({"success": True, "message": "Login successful!"})

@app.route("/logout")
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out"})

@app.route("/dashboard", methods=["GET"])
def dashboard():
    # check if the user is logged in
    user_id = session.get("user_id")
    if not user_id:
        # if the request came from JS (API call)
        if request.headers.get("Accept") == "application/json":
            return jsonify({"success": False, "message": "Not logged in"}), 401
        # otherwise (browser visiting directly)
        return send_from_directory(app.static_folder, "index.html")

    # handle API call for user data
    if request.headers.get("Accept") == "application/json":
        user = users.find_one({"_id": ObjectId(user_id)}, {"password": 0})
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
        user["_id"] = str(user["_id"])
        return jsonify({"success": True, "user": user})

    # handle normal page visit
    return send_from_directory(app.static_folder, "dashboard.html")

@app.route("/leaderboard")
def leaderboard():
    top_users = list(
        users.find({}, {"name": 1, "stats.captchas_completed": 1})
        .sort("stats.captchas_completed", -1)
        .limit(10)
    )
    for u in top_users:
        u["_id"] = str(u["_id"])
    return jsonify({"success": True, "leaders": top_users})

@app.route("/upload-avatar", methods=["POST"])
def upload_avatar():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Not logged in"}), 401
    data = request.json
    avatar = data.get("avatar")
    users.update_one({"_id": ObjectId(session["user_id"])}, {"$set": {"avatar": avatar}})
    return jsonify({"success": True, "message": "Avatar updated!"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)