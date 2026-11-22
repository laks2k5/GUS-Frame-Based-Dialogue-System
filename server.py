#!/usr/bin/env python3
"""
GUS – General User System  |  Flask Backend  (server.py)
─────────────────────────────────────────────────────────
Quick start:
  pip install -r requirements.txt
  copy .env.example .env         # then edit .env with your API keys
  python server.py

API base: http://localhost:5000/api/
Health:   http://localhost:5000/api/health
"""

import json, logging, os, secrets
from datetime import datetime, timedelta
from functools import wraps

import bcrypt
import jwt
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

from api.database import init_db, get_db
from api.amadeus_service  import AmadeusService
from api.railway_service  import RailwayService
from api.bus_service      import BusService
from api.payment_service  import PaymentService

# ══════════════════════════════════════════════════════════════
#  App setup
# ══════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, origins=os.getenv("ALLOWED_ORIGINS", "*"))
app.config.update(
    SECRET_KEY     = os.getenv("SECRET_KEY", secrets.token_hex(32)),
    DB_PATH        = os.getenv("DB_PATH", "gus.db"),
    JWT_EXPIRY_H   = int(os.getenv("JWT_EXPIRY_HOURS", 24)),
)

logging.basicConfig(
    level   = logging.DEBUG if os.getenv("FLASK_ENV") == "development" else logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("gus.server")

SUPPORTED_SPEECH_LANGUAGES = {"en", "hi", "bn", "te", "ta"}
WHISPER_LANGUAGE_NAMES = {
    "en": "english",
    "hi": "hindi",
    "bn": "bengali",
    "te": "telugu",
    "ta": "tamil",
}

# ── Init DB & services ────────────────────────────────────────
init_db(app.config["DB_PATH"])
amadeus = AmadeusService()
railway = RailwayService()
bus     = BusService()
payment = PaymentService()

# ══════════════════════════════════════════════════════════════
#  Auth helpers
# ══════════════════════════════════════════════════════════════
def _hash(pwd: str) -> str:
    return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

def _check(pwd: str, hashed: str) -> bool:
    return bcrypt.checkpw(pwd.encode(), hashed.encode())

def _make_token(uid: int) -> str:
    return jwt.encode(
        {"sub": uid, "iat": datetime.utcnow(),
         "exp": datetime.utcnow() + timedelta(hours=app.config["JWT_EXPIRY_H"])},
        app.config["SECRET_KEY"], algorithm="HS256",
    )

def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if not token:
            return jsonify({"error": "Authentication required"}), 401
        try:
            payload = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session expired — please log in again"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(payload["sub"], *args, **kwargs)
    return wrapper

# ══════════════════════════════════════════════════════════════
#  Static / page serving
# ══════════════════════════════════════════════════════════════
@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")

@app.route("/pages/<path:fn>")
def serve_pages(fn):
    return send_from_directory("pages", fn)

# ══════════════════════════════════════════════════════════════
#  Health
# ══════════════════════════════════════════════════════════════
@app.route("/api/health")
def health():
    return jsonify({
        "status":   "ok",
        "env":      os.getenv("FLASK_ENV", "production"),
        "services": {
            "amadeus":  amadeus.is_configured(),
            "railway":  railway.is_configured(),
            "bus":      bus.is_configured(),
            "payment":  payment.is_configured(),
        },
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """Transcribe browser-recorded audio using the configured multilingual Whisper API."""
    language = (request.form.get("language") or "").strip().lower()
    audio = request.files.get("audio")

    if language not in SUPPORTED_SPEECH_LANGUAGES:
        return jsonify({"error": "Unsupported speech language. Use en, hi, bn, te, or ta."}), 400
    if not audio or not audio.filename:
        return jsonify({"error": "No audio recording was uploaded."}), 400

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return jsonify({
            "error": "Voice transcription is not configured. Add OPENAI_API_KEY to .env."
        }), 503

    audio_bytes = audio.read()
    if not audio_bytes:
        return jsonify({"error": "The audio recording was empty. Please try speaking again."}), 400
    if len(audio_bytes) > 25 * 1024 * 1024:
        return jsonify({"error": "The audio recording is too large. Please keep it under 25 MB."}), 413

    filename = audio.filename or "gus-recording.webm"
    content_type = audio.mimetype or "audio/webm"
    try:
        response = requests.post(
            os.getenv("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions"),
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (filename, audio_bytes, content_type)},
            data={
                "model": os.getenv("WHISPER_MODEL", "whisper-1"),
                "language": language,
                "prompt": (
                    f"Transcribe this {WHISPER_LANGUAGE_NAMES[language]} travel conversation "
                    "accurately, preserving city and passenger names."
                ),
                "response_format": "json",
            },
            timeout=90,
        )
    except requests.RequestException:
        log.exception("Whisper transcription request failed")
        return jsonify({"error": "The transcription service could not be reached. Please try again."}), 502

    if not response.ok:
        log.error("Whisper API returned %s: %s", response.status_code, response.text[:500])
        return jsonify({"error": "The transcription service rejected the recording. Please try again."}), 502

    try:
        text = (response.json().get("text") or "").strip()
    except (ValueError, TypeError):
        log.error("Whisper API returned invalid JSON")
        return jsonify({"error": "The transcription service returned an invalid response."}), 502
    if not text:
        return jsonify({"error": "No speech was recognized. Please speak clearly and try again."}), 422
    return jsonify({"text": text, "language": language})

# ══════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════
@app.route("/api/auth/register", methods=["POST"])
def register():
    d     = request.json or {}
    name  = (d.get("name")  or "").strip()
    email = (d.get("email") or "").strip().lower()
    pwd   = d.get("password") or ""
    phone = (d.get("phone") or "").strip()

    if not name or not email or not pwd:
        return jsonify({"error": "name, email and password are required"}), 400
    if len(pwd) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    with get_db(app.config["DB_PATH"]) as db:
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({"error": "Email already registered"}), 409
        db.execute(
            "INSERT INTO users (name,email,password_hash,phone) VALUES (?,?,?,?)",
            (name, email, _hash(pwd), phone),
        )
        db.commit()
        uid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    return jsonify({"token": _make_token(uid), "name": name, "email": email}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    d     = request.json or {}
    email = (d.get("email") or "").strip().lower()
    pwd   = d.get("password") or ""

    with get_db(app.config["DB_PATH"]) as db:
        u = db.execute(
            "SELECT id,name,email,password_hash FROM users WHERE email=?", (email,)
        ).fetchone()

    if not u or not _check(pwd, u["password_hash"]):
        return jsonify({"error": "Invalid email or password"}), 401

    return jsonify({"token": _make_token(u["id"]), "name": u["name"], "email": u["email"]})


@app.route("/api/auth/me")
@token_required
def me(uid):
    with get_db(app.config["DB_PATH"]) as db:
        u = db.execute(
            "SELECT id,name,email,phone,created_at FROM users WHERE id=?", (uid,)
        ).fetchone()
    return jsonify(dict(u)) if u else (jsonify({"error": "Not found"}), 404)

# ══════════════════════════════════════════════════════════════
#  LOCATION AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════
@app.route("/api/locations/airports")
def airports():
    kw = (request.args.get("keyword") or "").strip()
    if len(kw) < 2:
        return jsonify({"locations": []})
    if not amadeus.is_configured():
        return jsonify({"locations": [], "note": "Amadeus not configured"})
    return jsonify({"locations": amadeus.search_locations(kw)})


@app.route("/api/locations/train-stations")
def stations():
    kw = (request.args.get("keyword") or "").strip()
    if len(kw) < 2:
        return jsonify({"stations": []})
    return jsonify({"stations": railway.search_stations(kw)})

# ══════════════════════════════════════════════════════════════
#  SEARCH
# ══════════════════════════════════════════════════════════════
def _cache_session(service_type: str, params: dict, results: dict) -> str:
    sid = secrets.token_urlsafe(16)
    with get_db(app.config["DB_PATH"]) as db:
        db.execute(
            "INSERT INTO search_sessions (session_id,service_type,search_params,results,expires_at)"
            " VALUES (?,?,?,?,?)",
            (sid, service_type, json.dumps(params), json.dumps(results),
             (datetime.utcnow() + timedelta(minutes=20)).isoformat()),
        )
        db.commit()
    return sid


def _not_configured(service: str, details: dict):
    return jsonify({"error": f"{service} not configured", "setup": details}), 503


@app.route("/api/search/flights", methods=["POST"])
def search_flights():
    d = request.json or {}
    missing = [f for f in ("origin","destination","date") if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    orig_code = amadeus.resolve_code(d["origin"])
    dest_code = amadeus.resolve_code(d["destination"])

    if not amadeus.is_configured():
        return jsonify({
            "error": "Amadeus (flights) not configured",
            "is_configured": False,
            "origin_code": orig_code,
            "destination_code": dest_code,
            "setup": {
                "steps": [
                    "1. Register FREE at https://developers.amadeus.com/",
                    "2. Create a Self-Service app",
                    "3. Set AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET in .env",
                ]
            }
        }), 503
    try:
        results = amadeus.search_flights(
            origin        = orig_code,
            destination   = dest_code,
            date          = d["date"],
            adults        = int(d.get("adults", 1)),
            travel_class  = d.get("travelClass", "ECONOMY"),
            return_date   = d.get("returnDate"),
        )
        results["origin_code"] = orig_code
        results["destination_code"] = dest_code
        results["session_id"] = _cache_session("flight", d, results)
        return jsonify(results)
    except Exception as exc:
        log.error(f"Flight search: {exc}")
        return jsonify({"error": str(exc), "origin_code": orig_code, "destination_code": dest_code}), 500


@app.route("/api/search/trains", methods=["POST"])
def search_trains():
    d = request.json or {}
    missing = [f for f in ("from_station","to_station","date") if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    from_stn = railway._code(d["from_station"])
    to_stn = railway._code(d["to_station"])

    if not railway.is_configured():
        return jsonify({
            "error": "Railway API not configured",
            "is_configured": False,
            "from_station": from_stn,
            "to_station": to_stn,
            "setup": {
                "options": [
                    "Option A: Register at https://www.railwayapi.com/ → set RAILWAY_API_KEY",
                    "Option B: https://rapidapi.com/ → Indian Railway IRCTC → set RAPIDAPI_KEY",
                ]
            }
        }), 503
    try:
        results = railway.search_trains(
            from_code   = from_stn,
            to_code     = to_stn,
            date        = d["date"],
            passengers  = int(d.get("passengers", 1)),
            travel_class= d.get("travelClass"),
        )
        results["from_station"] = from_stn
        results["to_station"] = to_stn
        results["session_id"] = _cache_session("train", d, results)
        return jsonify(results)
    except Exception as exc:
        log.error(f"Train search: {exc}")
        return jsonify({"error": str(exc), "from_station": from_stn, "to_station": to_stn}), 500


@app.route("/api/search/buses", methods=["POST"])
def search_buses():
    d = request.json or {}
    missing = [f for f in ("from_city","to_city","date") if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    if not bus.is_configured():
        return _not_configured("Bus API", {
            "note":    "No public Indian bus API exists.",
            "options": [
                "RedBus Partner API — partner@redbus.in",
                "AbhiBus API        — technology@abhibus.com",
            ],
            "dev":     "Set BUS_USE_MOCK=true in .env to enable sample data for development",
        })
    try:
        results = bus.search_buses(
            from_city  = d["from_city"],
            to_city    = d["to_city"],
            date       = d["date"],
            passengers = int(d.get("passengers", 1)),
        )
        results["session_id"] = _cache_session("bus", d, results)
        return jsonify(results)
    except Exception as exc:
        log.error(f"Bus search: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/search/revalidate", methods=["POST"])
def revalidate():
    d          = request.json or {}
    stype      = d.get("service_type")
    offer_id   = d.get("offer_id")
    session_id = d.get("session_id")
    if not all([stype, offer_id, session_id]):
        return jsonify({"error": "service_type, offer_id, session_id required"}), 400

    with get_db(app.config["DB_PATH"]) as db:
        sess = db.execute(
            "SELECT results FROM search_sessions WHERE session_id=? AND expires_at>?",
            (session_id, datetime.utcnow().isoformat()),
        ).fetchone()
    if not sess:
        return jsonify({"error": "Session expired — please search again"}), 410

    cached = json.loads(sess["results"])
    key    = "flights" if stype == "flight" else ("trains" if stype == "train" else "buses")
    offer  = next((o for o in cached.get(key, []) if str(o.get("id")) == str(offer_id)), None)
    if not offer:
        return jsonify({"error": "Offer not found in session"}), 404

    if stype == "flight" and amadeus.is_configured():
        try:
            offer = amadeus.revalidate_price(offer.get("raw_offer", offer))
        except Exception as exc:
            return jsonify({"valid": False, "error": str(exc)}), 500

    return jsonify({"valid": True, "offer": offer})

# ══════════════════════════════════════════════════════════════
#  BOOKING
# ══════════════════════════════════════════════════════════════
@app.route("/api/booking/initiate", methods=["POST"])
@token_required
def booking_initiate(uid):
    d = request.json or {}
    missing = [f for f in ("service_type","offer","passengers") if not d.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    offer  = d["offer"]
    pax    = d["passengers"]
    stype  = d["service_type"]

    if not isinstance(pax, list) or not pax:
        return jsonify({"error": "passengers must be a non-empty list"}), 400
    for p in pax:
        for field in ("firstName","lastName","dateOfBirth","gender"):
            if not p.get(field):
                return jsonify({"error": f"Passenger field missing: {field}"}), 400

    ref = f"GUS-{stype[:3].upper()}-{secrets.token_hex(4).upper()}"
    with get_db(app.config["DB_PATH"]) as db:
        db.execute(
            """INSERT INTO bookings
               (booking_ref,user_id,service_type,status,
                origin,destination,journey_date,
                selected_option,passengers,
                base_price,taxes,total_price,currency)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ref, uid, stype, "pending",
             offer.get("origin", offer.get("from","")),
             offer.get("destination", offer.get("to","")),
             offer.get("departureDate", offer.get("date","")),
             json.dumps(offer), json.dumps(pax),
             offer.get("price",{}).get("base",0),
             offer.get("price",{}).get("taxes",0),
             offer.get("price",{}).get("total",0),
             offer.get("price",{}).get("currency","INR")),
        )
        db.commit()

    return jsonify({"booking_ref": ref, "status": "pending"}), 201


@app.route("/api/booking/<ref>/create-payment", methods=["POST"])
@token_required
def booking_create_payment(uid, ref):
    with get_db(app.config["DB_PATH"]) as db:
        b = db.execute(
            "SELECT * FROM bookings WHERE booking_ref=? AND user_id=?", (ref, uid)
        ).fetchone()
    if not b:
        return jsonify({"error": "Booking not found"}), 404
    if b["status"] != "pending":
        return jsonify({"error": f"Booking already {b['status']}"}), 400
    if not payment.is_configured():
        return _not_configured("Razorpay (payments)", {
            "steps": [
                "1. Register at https://razorpay.com/",
                "2. Settings → API Keys → Generate Test Key",
                "3. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env",
            ]
        })
    try:
        amount_paise = max(int(float(b["total_price"]) * 100), 100)
        order = payment.create_order(amount_paise, b["currency"] or "INR", ref)
        with get_db(app.config["DB_PATH"]) as db:
            db.execute(
                "UPDATE bookings SET payment_order_id=? WHERE booking_ref=?",
                (order["id"], ref),
            )
            db.commit()
        return jsonify({
            "order_id":    order["id"],
            "amount":      amount_paise,
            "currency":    b["currency"] or "INR",
            "key_id":      os.getenv("RAZORPAY_KEY_ID"),
            "booking_ref": ref,
            "is_test":     payment.is_test_mode(),
        })
    except Exception as exc:
        log.error(f"Create payment: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/booking/<ref>/confirm", methods=["POST"])
@token_required
def booking_confirm(uid, ref):
    d = request.json or {}
    rp_order_id   = d.get("razorpay_order_id","")
    rp_payment_id = d.get("razorpay_payment_id","")
    rp_signature  = d.get("razorpay_signature","")

    with get_db(app.config["DB_PATH"]) as db:
        b = db.execute(
            "SELECT * FROM bookings WHERE booking_ref=? AND user_id=?", (ref, uid)
        ).fetchone()
    if not b:
        return jsonify({"error": "Booking not found"}), 404

    # 1 — Verify payment signature
    if payment.is_configured():
        try:
            payment.verify_signature(rp_order_id, rp_payment_id, rp_signature)
        except Exception as exc:
            log.error(f"Signature verify: {exc}")
            return jsonify({"error": "Payment verification failed", "detail": str(exc)}), 400

    # 2 — Provider booking
    stype  = b["service_type"]
    offer  = json.loads(b["selected_option"] or "{}")
    pax    = json.loads(b["passengers"]      or "[]")
    prov_pnr  = ref   # fallback to our internal ref
    prov_resp = {}
    is_test   = True

    try:
        if stype == "flight" and amadeus.is_configured():
            result    = amadeus.create_order(offer.get("raw_offer", offer), pax)
            prov_pnr  = result.get("pnr") or result.get("id") or ref
            prov_resp = result
            is_test   = result.get("is_test", True)
        elif stype == "train":
            # IRCTC booking not supported — tell user to book on IRCTC
            prov_resp = {
                "note":   "Train tickets must be purchased through IRCTC.",
                "url":    "https://www.irctc.co.in/",
                "train":  offer.get("trainNumber",""),
            }
        else:
            prov_resp = {"note": "Provider API not configured — internal reference used"}
    except Exception as exc:
        log.error(f"Provider booking failed: {exc}")
        # Payment received but provider booking failed — keep record
        with get_db(app.config["DB_PATH"]) as db:
            db.execute(
                "UPDATE bookings SET status='payment_received',payment_id=?,"
                "payment_status='paid',provider_response=? WHERE booking_ref=?",
                (rp_payment_id, json.dumps({"error": str(exc)}), ref),
            )
            db.commit()
        return jsonify({
            "error":       "Payment received but provider booking failed",
            "detail":      str(exc),
            "booking_ref": ref,
            "action":      "Contact support with your booking reference",
        }), 500

    # 3 — Mark confirmed
    with get_db(app.config["DB_PATH"]) as db:
        db.execute(
            """UPDATE bookings
               SET status='confirmed', payment_id=?, payment_status='paid',
                   provider_booking_id=?, provider_response=?,
                   updated_at=datetime('now')
               WHERE booking_ref=?""",
            (rp_payment_id, prov_pnr, json.dumps(prov_resp), ref),
        )
        db.commit()

    return jsonify({
        "booking_ref":  ref,
        "status":       "confirmed",
        "provider_pnr": prov_pnr,
        "is_test":      is_test,
        "disclaimer":   "⚠️ TEST — no real ticket issued." if is_test else "Booking confirmed.",
    })


@app.route("/api/bookings", methods=["GET"])
@token_required
def list_bookings(uid):
    with get_db(app.config["DB_PATH"]) as db:
        rows = db.execute(
            """SELECT booking_ref,service_type,status,origin,destination,
                      journey_date,total_price,currency,provider_booking_id,
                      payment_status,created_at
               FROM bookings WHERE user_id=? ORDER BY created_at DESC""",
            (uid,),
        ).fetchall()
    return jsonify({"bookings": [dict(r) for r in rows]})


@app.route("/api/bookings/<ref>", methods=["GET"])
@token_required
def get_booking(uid, ref):
    with get_db(app.config["DB_PATH"]) as db:
        b = db.execute(
            "SELECT * FROM bookings WHERE booking_ref=? AND user_id=?", (ref, uid)
        ).fetchone()
    if not b:
        return jsonify({"error": "Booking not found"}), 404
    out = dict(b)
    out["selected_option"]   = json.loads(out.get("selected_option")  or "{}")
    out["passengers"]        = json.loads(out.get("passengers")        or "[]")
    out["provider_response"] = json.loads(out.get("provider_response") or "{}")
    return jsonify(out)


@app.route("/api/bookings/<ref>/cancel", methods=["POST"])
@token_required
def cancel_booking(uid, ref):
    with get_db(app.config["DB_PATH"]) as db:
        b = db.execute(
            "SELECT * FROM bookings WHERE booking_ref=? AND user_id=?", (ref, uid)
        ).fetchone()
    if not b:
        return jsonify({"error": "Booking not found"}), 404
    if b["status"] == "cancelled":
        return jsonify({"error": "Already cancelled"}), 400

    prov_msg = "No provider cancellation (not configured or not applicable)"
    pnr      = b["provider_booking_id"]
    try:
        if b["service_type"] == "flight" and amadeus.is_configured() and pnr:
            if amadeus.cancel_order(pnr):
                prov_msg = "Amadeus order cancelled"
    except Exception as exc:
        prov_msg = f"Provider cancel failed: {exc}"

    with get_db(app.config["DB_PATH"]) as db:
        db.execute(
            "UPDATE bookings SET status='cancelled',cancelled_at=datetime('now'),"
            "updated_at=datetime('now') WHERE booking_ref=?",
            (ref,),
        )
        db.commit()

    return jsonify({
        "booking_ref":  ref,
        "status":       "cancelled",
        "provider_msg": prov_msg,
        "refund_note":  "Raise refund requests through support for paid bookings.",
    })

# ══════════════════════════════════════════════════════════════
#  Error handlers
# ══════════════════════════════════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    log.error(f"Unhandled: {e}")
    return jsonify({"error": "Internal server error"}), 500

# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"
    log.info(f"GUS server → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
