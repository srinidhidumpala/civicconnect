import hashlib, io, math, os, re, secrets, sqlite3, sys, time, uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, abort, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash

import ai

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "instance", "civic.db"))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(BASE, "uploads"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def _secret():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    os.makedirs(os.path.join(BASE, "instance"), exist_ok=True)
    p = os.path.join(BASE, "instance", "secret.key")
    if not os.path.exists(p):
        open(p, "w").write(secrets.token_hex(32))
    return open(p).read().strip()

FRONTEND = os.path.abspath(os.path.join(BASE, "..", "frontend"))
app = Flask(__name__, static_folder=FRONTEND, static_url_path="")
app.config.update(SECRET_KEY=_secret(), MAX_CONTENT_LENGTH=12 * 1024 * 1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",   # set COOKIE_SECURE=1 when served over HTTPS
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

# ----------------------------------------------------------------- configuration
# category -> (department type, base severity score 0-3)
CATEGORIES = {
    "Pothole": ("ROAD", 2), "Damaged Road": ("ROAD", 2),
    "Garbage Accumulation": ("SANITATION", 1), "Broken Streetlight": ("ELECTRICAL", 1),
    "Water Leakage": ("WATER", 1), "Waterlogging": ("WATER", 2), "Drainage Problem": ("WATER", 1),
    "Electrical Problem": ("ELECTRICAL", 2), "Fire-Related Issue": ("FIRE", 3),
    "Other Civic Issue": ("GENERAL", 0),
}
DEPT_TYPES = {"ROAD": "Road/PWD Department", "SANITATION": "Municipal/Sanitation Department",
              "ELECTRICAL": "Electrical Department", "WATER": "Water/Drainage Department",
              "FIRE": "Fire Department", "GENERAL": "General Municipal Department"}
# SAMPLE service areas for the demo (NOT official jurisdiction boundaries): name -> office lat/lon
SAMPLE_AREAS = {"Moinabad": (17.3166, 78.2646), "Himayatnagar": (17.4008, 78.4824)}
SERVICE_LOCALITIES = ['Abids', 'Adikmet', 'Alkapuri', 'Ameerpet', 'Attapur', 'Bachupally', 'Badangpet', 'Bahadurpura', 'Banjara Hills', 'Barkas', 'Begumpet', 'Boduppal', 'Bowenpally', 'Chandanagar', 'Chengicherla', 'Chevella', 'Chintal', 'Dilsukhnagar', 'ECIL', 'Erragadda', 'Falaknuma', 'Gachibowli', 'Gandipet', 'Ghatkesar', 'Hayathnagar', 'Himayatnagar', 'HITEC City', 'Ibrahimpatnam', 'Jubilee Hills', 'Kachiguda', 'Kandukur', 'Kapra', 'Karwan', 'Keesara', 'Kompally', 'Kondapur', 'Kothapet', 'Kukatpally', 'LB Nagar', 'Madhapur', 'Maheshwaram', 'Malkajgiri', 'Manikonda', 'Medchal', 'Mehdipatnam', 'Miyapur', 'Moinabad', 'Mokila', 'Moula Ali', 'Musheerabad', 'Nallagandla', 'Nanakramguda', 'Narsingi', 'Neredmet', 'Old City', 'Osman Sagar', 'Patancheru', 'Peerzadiguda', 'Pocharam', 'Pragathi Nagar', 'Rajendranagar', 'Ramachandrapuram', 'Rampally', 'Rangareddy District', 'Saidabad', 'Sainikpuri', 'Saroor Nagar', 'Serilingampally', 'Shadnagar', 'Shamshabad', 'Shankarpally', 'Tarnaka', 'Tellapur', 'Thorrur', 'Tolichowki', 'Uppal', 'Vanastalipuram', 'Yacharam', 'Yousufguda', 'Ameenpur', 'Bandlaguda Jagir', 'Bongloor', 'Chevella Mandal', 'Dammaiguda', 'Dundigal', 'Gagillapur', 'Girmapur', 'Jalpally', 'Jillelguda', 'Kollur', 'Kongara Kalan', 'Kothur', 'Mankhal', 'Mamidipally', 'Manneguda', 'Nandigama', 'Narsapur', 'Peddamberpet', 'Shamirpet', 'Turkayamjal', 'Afzalgunj', 'Amberpet', 'Asif Nagar', 'Balanagar', 'Balapur', 'BHEL Township', 'Chilkur', 'Dabeerpura', 'Domalguda', 'Film Nagar', 'Gowlidoddy', 'Hafeezpet', 'Hasmathpet', 'Jiyaguda', 'Karmanghat', 'Koti', 'Kukatpally Housing Board', 'Langer Houz', 'Lingampally', 'Mallapur', 'Marredpally', 'Masab Tank', 'Miyapur Allwyn Colony', 'Nacharam', 'Nampally', 'Nizampet', 'Panjagutta', 'Rajendra Nagar Mandal', 'Saroornagar', 'Somajiguda', 'Suraram', 'Uppal Kalan', 'Vanasthalipuram', 'Yellareddyguda', 'Moinabad Mandal', 'Amangal', 'Kadthal', 'Keshampet', 'Madgul', 'Manchal', 'Talakondapally', 'Farooqnagar', 'Kondurg', 'Kothur Mandal', 'Nandigama Mandal', 'Shabad', 'Serilingampally Mandal', 'Gandipet Mandal', 'Rajendranagar Mandal', 'Shamshabad Mandal']

MAX_ROUTE_KM = 15.0           # a complaint farther than this from every matching office is "unmapped"
DUPLICATE_RADIUS_KM = 0.10    # 100 m
DUPLICATE_DAYS = 7
SEVERITIES = ["Low", "Medium", "High", "Critical"]
RISK_WORDS = ["accident", "injur", "child", "school", "hospital", "deep", "danger", "flood", "spark",
              "shock", "live wire", "smoke", "gas", "collapse", "blocked", "main road", "highway",
              "overflow", "open manhole", "dark"]
DEPT_TRANSITIONS = {"Assigned": ["In Progress"], "Reopened": ["In Progress"],
                    "In Progress": ["In Progress", "Awaiting Verification"]}
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
MAX_IMG = 5 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ----------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT NOT NULL, dtype TEXT NOT NULL,
  area TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('CITIZEN','ADMIN','DEPARTMENT')),
  department_id INTEGER REFERENCES departments(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS complaints(id INTEGER PRIMARY KEY, public_id TEXT UNIQUE, submit_key TEXT UNIQUE,
  citizen_id INTEGER NOT NULL REFERENCES users(id), category TEXT NOT NULL, description TEXT,
  image TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
  severity TEXT NOT NULL, severity_reason TEXT, severity_overridden INTEGER DEFAULT 0,
  ai_category TEXT, ai_confidence REAL, ai_note TEXT,
  area TEXT, suggested_dept_id INTEGER REFERENCES departments(id), suggested_km REAL,
  dept_id INTEGER REFERENCES departments(id), status TEXT NOT NULL,
  admin_remark TEXT, dept_remark TEXT, resolution_image TEXT, duplicate_of TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, assigned_at TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, complaint_id INTEGER NOT NULL REFERENCES complaints(id),
  status TEXT, note TEXT, actor TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invitations(id INTEGER PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('ADMIN','DEPARTMENT')), department_id INTEGER REFERENCES departments(id),
  created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  used_at TEXT, used_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS registration_requests(
  id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('ADMIN','DEPARTMENT')),
  name TEXT NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL,
  department_name TEXT, dtype TEXT, area TEXT, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED')),
  reviewed_by INTEGER REFERENCES users(id), reviewed_at TEXT
);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def q(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    c.commit(); c.close()

def seed():
    """Creates departments, one admin, and one login per department office. Safe to re-run."""
    init_db()
    c = sqlite3.connect(DB_PATH)
    out = []
    if not c.execute("SELECT 1 FROM departments").fetchone():
        for dtype, dname in DEPT_TYPES.items():
            for area, (la, lo) in SAMPLE_AREAS.items():
                c.execute("INSERT INTO departments(name,dtype,area,lat,lon) VALUES(?,?,?,?,?)",
                          (f"{dname} - {area}", dtype, area, la, lo))
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@civic.demo").lower()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "Admin@123")
    if not c.execute("SELECT 1 FROM users WHERE email=?", (admin_email,)).fetchone():
        c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                  ("Municipal Admin", admin_email, generate_password_hash(admin_pw), "ADMIN", now()))
        out.append(("ADMIN", admin_email, admin_pw))
    for d in c.execute("SELECT id,name,dtype,area FROM departments").fetchall():
        email = f"{d[2].lower()}.{d[3].lower()}@civic.demo"
        if not c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            c.execute("INSERT INTO users(name,email,password_hash,role,department_id,created_at) VALUES(?,?,?,?,?,?)",
                      (d[1], email, generate_password_hash("Dept@123"), "DEPARTMENT", d[0], now()))
            out.append(("DEPARTMENT", email, "Dept@123"))
    c.commit(); c.close()
    return out

# ----------------------------------------------------------------- business rules
def haversine_km(la1, lo1, la2, lo2):
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def assess_severity(category, description):
    """Rule-based (NOT a trained model): base score by category + risk keywords in the description."""
    base = CATEGORIES[category][1]
    text = (description or "").lower()
    hits = [w for w in RISK_WORDS if w in text]
    score = base + min(len(hits), 2)
    level = "Low" if score <= 1 else "Medium" if score == 2 else "High" if score == 3 else "Critical"
    reason = f"Rule-based: category '{category}' base score {base}"
    reason += f" + {min(len(hits), 2)} for risk words ({', '.join(hits[:3])})" if hits else " + 0 (no risk words in description)"
    return level, reason + f" = {score} -> {level}."

def suggest_department(category, lat, lon, area=None):
    """Prefer the department matching the citizen-selected locality and category; otherwise use nearest eligible office."""
    dtype = CATEGORIES[category][0]
    if area:
        exact = q("SELECT * FROM departments WHERE dtype=? AND lower(area)=lower(?) ORDER BY id LIMIT 1",
                  (dtype, area), one=True)
        if exact:
            return (exact, haversine_km(lat, lon, exact["lat"], exact["lon"]))
    best = None
    for d in q("SELECT * FROM departments WHERE dtype=?", (dtype,)):
        km = haversine_km(lat, lon, d["lat"], d["lon"])
        if km <= MAX_ROUTE_KM and (best is None or km < best[1]):
            best = (d, km)
    return best

def find_duplicate(category, lat, lon):
    since = (datetime.now() - timedelta(days=DUPLICATE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    for r in q("SELECT public_id,lat,lon FROM complaints WHERE category=? AND status!='Resolved' AND created_at>=?",
               (category, since)):
        if haversine_km(lat, lon, r["lat"], r["lon"]) <= DUPLICATE_RADIUS_KM:
            return r["public_id"]
    return None

def save_image(file):
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        raise ValueError("Unsupported file type. Please upload a JPG, PNG or WEBP image.")
    data = file.read()
    if len(data) > MAX_IMG:
        raise ValueError("Image is larger than 5 MB.")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise ValueError("The uploaded file is not a valid image.")
    name = uuid.uuid4().hex + "." + ("jpg" if ext == "jpeg" else ext)
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return name

def add_history(cid, status, note, actor):
    db().execute("INSERT INTO history(complaint_id,status,note,actor,created_at) VALUES(?,?,?,?,?)",
                 (cid, status, note, actor, now()))

# ----------------------------------------------------------------- helpers: auth / json
def jerr(msg, code=400, **kw):
    return jsonify(error=msg, **kw), code

def body():
    return request.get_json(silent=True) or {}

@app.before_request
def load_user():
    g.user = None
    if session.get("uid"):
        g.user = q("SELECT * FROM users WHERE id=?", (session["uid"],), one=True)  # role always read from DB
    if request.method == "POST":
        tok, sent = session.get("csrf"), request.headers.get("X-CSRF-Token", "")
        if not tok or not secrets.compare_digest(sent.encode(), tok.encode()):
            return jerr("Security token missing or expired. Please refresh the page.", 400)

def role_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not g.user: return jerr("Please log in to continue.", 401)
            if g.user["role"] not in roles: return jerr("You do not have permission for this action.", 403)
            return f(*a, **k)
        return w
    return deco

@app.errorhandler(HTTPException)
def on_http_error(e):
    msg = "Upload too large (max 12 MB per request)." if e.code == 413 else e.description
    return jerr(msg, e.code)

def media_url(n):
    return f"/api/media/{n}" if n else None

def ser(c):
    """Row -> JSON dict. Staff-only fields (AI, routing, citizen email) are added only for ADMIN/DEPARTMENT."""
    k = c.keys()
    d = {f: c[f] for f in ("public_id", "category", "description", "lat", "lon", "severity", "severity_reason", "status",
                           "admin_remark", "dept_remark", "created_at", "updated_at", "assigned_at", "area",
                           "dept_name", "dept_id", "citizen_name") if f in k}
    d["image"], d["resolution_image"] = media_url(c["image"]), media_url(c["resolution_image"]) if "resolution_image" in k else None
    if g.user["role"] != "CITIZEN":
        for f in ("ai_category", "ai_confidence", "ai_note", "suggested_dept_id", "suggested_km", "sugg_name", "duplicate_of", "citizen_email"):
            if f in k: d[f] = c[f]
    else:
        d.pop("citizen_name", None)
    return d

# ----------------------------------------------------------------- auth routes
@app.route("/api/me")
def me():
    session.setdefault("csrf", secrets.token_hex(16))
    u = g.user
    profile = None
    if u:
        profile = dict(id=u["id"], name=u["name"], email=u["email"], role=u["role"], created_at=u["created_at"])
        if u["role"] == "DEPARTMENT" and u["department_id"]:
            d = q("SELECT id,name,dtype,area FROM departments WHERE id=?", (u["department_id"],), one=True)
            if d:
                profile["department"] = dict(d)
    return jsonify(csrf=session["csrf"], categories=list(CATEGORIES), severities=SEVERITIES,
                   localities=SERVICE_LOCALITIES, user=profile)

# ---- shared validation, rate limiting, invitations
NAME_MAX, EMAIL_MAX, PW_MAX = 100, 254, 128
RL_MAX, RL_WINDOW = 10, 15 * 60          # 10 failed attempts per 15 minutes per client IP and bucket
TOO_MANY = "Too many failed attempts. Please wait 15 minutes and try again."
_RL = {}
DUMMY_HASH = generate_password_hash("not-a-real-password")   # equalises timing for unknown emails
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"            # no 0/O/1/I confusion; 20 chars ~ 100 bits

def _rl_key(bucket): return (request.remote_addr or "?", bucket)
def rl_blocked(bucket):
    t = time.time(); hits = [x for x in _RL.get(_rl_key(bucket), []) if t - x < RL_WINDOW]
    _RL[_rl_key(bucket)] = hits
    return len(hits) >= RL_MAX
def rl_fail(bucket): _RL.setdefault(_rl_key(bucket), []).append(time.time())
def rl_ok(bucket): _RL.pop(_rl_key(bucket), None)

def password_errors(pw, pw2, strict=False):
    need, errs = (10 if strict else 8), []
    if len(pw) < need: errs.append(f"Password must be at least {need} characters.")
    elif len(pw) > PW_MAX: errs.append(f"Password must be at most {PW_MAX} characters.")
    elif strict and not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        errs.append("Password must contain at least one letter and one number.")
    if pw != pw2: errs.append("Passwords do not match.")
    return errs

def identity_errors(name, email, name_label="Full name"):
    errs = []
    if not name: errs.append(f"{name_label} is required.")
    elif len(name) > NAME_MAX: errs.append(f"{name_label} must be at most {NAME_MAX} characters.")
    if not EMAIL_RE.match(email) or len(email) > EMAIL_MAX: errs.append("Enter a valid email address.")
    return errs

def norm_code(c): return re.sub(r"[^A-Z0-9]", "", str(c or "").upper())
def hash_code(c): return hashlib.sha256(norm_code(c).encode()).hexdigest()   # only the hash is stored
def norm_text(t): return " ".join(str(t or "").lower().split())

def create_invitation(role, dept_id=None, created_by=None, days=7):
    """Returns (plain_code, expires_at). The plain code is shown ONCE; only its SHA-256 hash is stored."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(20))
    code = "-".join(raw[i:i + 5] for i in range(0, 20, 5))
    exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db().execute("INSERT INTO invitations(code_hash,role,department_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                 (hash_code(code), role, dept_id, created_by, now(), exp))
    db().commit()
    return code, exp

def find_invite(code, role):
    if len(norm_code(code)) != 20: return None
    inv = q("SELECT * FROM invitations WHERE code_hash=? AND role=?", (hash_code(code), role), one=True)
    return inv if inv and not inv["used_at"] and inv["expires_at"] >= now() else None

def create_staff_user(inv, name, email, pw):
    """Consumes the invitation and creates the user in ONE transaction. Role/department come from the invitation, never the request."""
    try:
        if db().execute("UPDATE invitations SET used_at=? WHERE id=? AND used_at IS NULL", (now(), inv["id"])).rowcount != 1:
            db().rollback(); return jerr("Invalid, expired or already used registration code.", 403)
        uid = db().execute("INSERT INTO users(name,email,password_hash,role,department_id,created_at) VALUES(?,?,?,?,?,?)",
                           (name, email, generate_password_hash(pw), inv["role"], inv["department_id"], now())).lastrowid
        db().execute("UPDATE invitations SET used_by=? WHERE id=?", (uid, inv["id"]))
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback(); return jerr("An account with this email already exists.", 400, errors=["An account with this email already exists."])
    return jsonify(ok=True), 201

def do_login(role):
    f = body()
    if rl_blocked("login"): return jerr(TOO_MANY, 429)
    u = q("SELECT * FROM users WHERE email=?", ((f.get("email") or "").strip().lower(),), one=True)
    good = check_password_hash(u["password_hash"] if u else DUMMY_HASH, str(f.get("password") or ""))
    if not u or not good or u["role"] != role:
        rl_fail("login")
        return jerr("Invalid email or password.", 401)
    rl_ok("login")
    session.clear(); session.permanent = True; session["uid"] = u["id"]; session["csrf"] = secrets.token_hex(16)
    return jsonify(ok=True, role=u["role"], csrf=session["csrf"])

# ---- citizen
@app.route("/api/register", methods=["POST"])
def register():
    f = body()
    name, email, pw, pw2 = (f.get("name") or "").strip(), (f.get("email") or "").strip().lower(), f.get("password") or "", f.get("confirm") or ""
    errs = identity_errors(name, email) + password_errors(pw, pw2)
    if not errs and q("SELECT 1 FROM users WHERE email=?", (email,), one=True): errs.append("An account with this email already exists.")
    if errs: return jerr(" ".join(errs), 400, errors=errs)
    try:
        db().execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                     (name, email, generate_password_hash(pw), "CITIZEN", now()))  # role is ALWAYS CITIZEN here
        db().commit()
    except sqlite3.IntegrityError:
        return jerr("An account with this email already exists.", 400, errors=["An account with this email already exists."])
    return jsonify(ok=True), 201

@app.route("/api/login", methods=["POST"])
def login():
    return do_login("CITIZEN")          # citizen portal only; staff use /api/admin/login and /api/dept/login

# ---- admin
@app.route("/api/admin/register", methods=["POST"])
def admin_register():
    """Demo-mode public admin registration. Do NOT expose unrestricted admin signup on a production deployment."""
    f = body()
    name, email = (f.get("name") or "").strip(), (f.get("email") or "").strip().lower()
    pw, pw2 = f.get("password") or "", f.get("confirm") or ""
    errs = identity_errors(name, email) + password_errors(pw, pw2, strict=True)
    if not errs and q("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,), one=True):
        errs.append("An account with this email already exists.")
    if errs: return jerr(" ".join(errs), 400, errors=errs)
    try:
        db().execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                     (name, email, generate_password_hash(pw), "ADMIN", now()))
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return jerr("An account with this email already exists.", 400, errors=["An account with this email already exists."])
    return jsonify(ok=True, message="Admin account created successfully. You can now sign in."), 201

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    return do_login("ADMIN")

# ---- department
@app.route("/api/dept/register", methods=["POST"])
def dept_register():
    """Creates a department account immediately for the demo. Verify organizations before production use."""
    f = body()
    name, email = (f.get("name") or "").strip(), (f.get("email") or "").strip().lower()
    pw, pw2 = f.get("password") or "", f.get("confirm") or ""
    dn, area = (f.get("department_name") or "").strip(), (f.get("area") or "").strip()
    dtype = (f.get("dtype") or "GENERAL").strip().upper()
    errs = identity_errors(name, email, "Authorized staff name") + password_errors(pw, pw2, strict=True)
    if area not in SERVICE_LOCALITIES: errs.append("Choose a valid Hyderabad or Rangareddy locality.")
    if dtype not in DEPT_TYPES: errs.append("Choose a valid department category.")
    if dtype in DEPT_TYPES:
        dn = f"{DEPT_TYPES[dtype]} - {area}"
    if not errs and q("SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,), one=True):
        errs.append("An account with this email already exists.")
    if errs: return jerr(" ".join(errs), 400, errors=errs)
    try:
        existing = q("SELECT * FROM departments WHERE dtype=? AND lower(area)=lower(?) ORDER BY id LIMIT 1",
                     (dtype, area), one=True)
        if existing:
            dept_id = existing["id"]
        else:
            coords = SAMPLE_AREAS.get(area, (17.3850, 78.4867))
            dept_id = db().execute("INSERT INTO departments(name,dtype,area,lat,lon) VALUES(?,?,?,?,?)",
                                   (dn, dtype, area, coords[0], coords[1])).lastrowid
        db().execute("INSERT INTO users(name,email,password_hash,role,department_id,created_at) VALUES(?,?,?,?,?,?)",
                     (name, email, generate_password_hash(pw), "DEPARTMENT", dept_id, now()))
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return jerr("An account with this email already exists.", 400, errors=["An account with this email already exists."])
    return jsonify(ok=True, message="Department account created successfully. You can now sign in."), 201

@app.route("/api/dept/login", methods=["POST"])
def dept_login():
    return do_login("DEPARTMENT")

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(ok=True)

@app.route("/api/media/<name>")
def media(name):
    if not g.user: return jerr("Please log in.", 401)
    return send_from_directory(UPLOAD_DIR, os.path.basename(name))  # random 32-hex names, login required

@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")

def count(rows, *statuses):
    return sum(r["n"] for r in rows if r["status"] in statuses)

def fetch_complaint(pid):
    c = q("SELECT c.*, u.name citizen_name, u.email citizen_email, d.name dept_name, d.area dept_area, "
          "sd.name sugg_name FROM complaints c JOIN users u ON u.id=c.citizen_id "
          "LEFT JOIN departments d ON d.id=c.dept_id LEFT JOIN departments sd ON sd.id=c.suggested_dept_id "
          "WHERE c.public_id=?", (pid,), one=True)
    if not c: abort(404, "Complaint not found.")
    u = g.user
    ok = (u["role"] == "ADMIN" or (u["role"] == "CITIZEN" and c["citizen_id"] == u["id"]) or
          (u["role"] == "DEPARTMENT" and c["dept_id"] == u["department_id"]))
    if not ok: abort(403, "You do not have access to this complaint.")
    return c

# ----------------------------------------------------------------- citizen
@app.route("/api/citizen/dashboard")
@role_required("CITIZEN")
def citizen_dashboard():
    rows = q("SELECT status, COUNT(*) n FROM complaints WHERE citizen_id=? GROUP BY status", (g.user["id"],))
    stats = dict(total=sum(r["n"] for r in rows), pending=count(rows, "Pending Assignment", "Assigned", "Reopened"),
                 progress=count(rows, "In Progress", "Awaiting Verification"), resolved=count(rows, "Resolved"))
    items = q("SELECT c.*, d.name dept_name FROM complaints c LEFT JOIN departments d ON d.id=c.dept_id "
              "WHERE citizen_id=? ORDER BY c.id DESC", (g.user["id"],))
    return jsonify(stats=stats, items=[ser(c) for c in items])

@app.route("/api/complaints", methods=["POST"])
@role_required("CITIZEN")
def create_complaint():
    f = request.form
    key = f.get("submit_key", "")
    if key:
        dup = q("SELECT public_id FROM complaints WHERE submit_key=?", (key,), one=True)
        if dup: return jsonify(public_id=dup["public_id"], duplicate_submit=True)  # double-click -> same complaint
    cat, desc = f.get("category", ""), f.get("description", "").strip()[:2000]
    selected_area = (f.get("area") or "").strip()
    errs = []
    if cat not in CATEGORIES: errs.append("Please choose a complaint category.")
    if selected_area and selected_area not in SERVICE_LOCALITIES: errs.append("Please choose a valid locality.")
    try:
        lat, lon = float(f.get("lat", "")), float(f.get("lon", ""))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError
    except ValueError:
        errs.append("Please select the issue location on the map (or use your current location).")
    image = None
    try:
        image = save_image(request.files.get("image"))
        if not image: errs.append("Please upload an image of the issue.")
    except ValueError as e:
        errs.append(str(e))
    if errs: return jerr(" ".join(errs), 400, errors=errs)
    a = ai.analyze(os.path.join(UPLOAD_DIR, image))
    sev, reason = assess_severity(cat, desc)
    sugg = suggest_department(cat, lat, lon, selected_area or None)
    dup_of = find_duplicate(cat, lat, lon)
    ts = now()
    cur = db().execute(
        "INSERT INTO complaints(submit_key,citizen_id,category,description,image,lat,lon,severity,severity_reason,"
        "ai_category,ai_confidence,ai_note,area,suggested_dept_id,suggested_km,status,duplicate_of,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key or None, g.user["id"], cat, desc, image, lat, lon, sev, reason, a["category"], a["confidence"], a["note"],
         selected_area or (sugg[0]["area"] if sugg else None), sugg[0]["id"] if sugg else None, round(sugg[1], 2) if sugg else None,
         "Pending Assignment", dup_of, ts, ts))
    cid = cur.lastrowid
    pid = f"CMP-{datetime.now().year}-{cid:05d}"
    db().execute("UPDATE complaints SET public_id=? WHERE id=?", (pid, cid))
    add_history(cid, "Pending Assignment", "Complaint submitted by citizen.", g.user["name"])
    db().commit()
    return jsonify(public_id=pid), 201

@app.route("/api/complaints/<pid>")
@role_required("CITIZEN", "ADMIN", "DEPARTMENT")
def complaint_detail(pid):
    c = fetch_complaint(pid)
    hist = [dict(h) for h in q("SELECT status,note,actor,created_at FROM history WHERE complaint_id=? ORDER BY id DESC", (c["id"],))]
    out = dict(complaint=ser(c), history=hist, options=DEPT_TRANSITIONS.get(c["status"], []) if g.user["role"] == "DEPARTMENT" else [])
    if g.user["role"] == "ADMIN":
        out["departments"] = [dict(d) for d in q("SELECT id,name,dtype,area FROM departments ORDER BY dtype, area")]
        out["complaint"]["dept_id"] = c["dept_id"]
    return jsonify(out)

# ----------------------------------------------------------------- admin
@app.route("/api/admin/registration-requests", methods=["GET"])
@role_required("ADMIN")
def admin_registration_requests():
    rows = q("""SELECT id,role,name,email,department_name,dtype,area,created_at
                FROM registration_requests WHERE status='PENDING' ORDER BY created_at""")
    return jsonify(items=[dict(r) for r in rows])

@app.route("/api/admin/registration-requests/<int:rid>/approve", methods=["POST"])
@role_required("ADMIN")
def approve_registration_request(rid):
    r = q("SELECT * FROM registration_requests WHERE id=? AND status='PENDING'", (rid,), one=True)
    if not r: return jerr("Request not found or already reviewed.", 404)
    if q("SELECT 1 FROM users WHERE email=?", (r["email"],), one=True):
        db().execute("UPDATE registration_requests SET status='REJECTED',reviewed_by=?,reviewed_at=? WHERE id=?",
                     (g.user["id"],now(),rid)); db().commit()
        return jerr("An account with this email already exists; request rejected.", 400)
    dept_id = None
    if r["role"] == "DEPARTMENT":
        existing = q("SELECT * FROM departments WHERE dtype=? AND lower(area)=lower(?) AND lower(name)=lower(?)",
                      (r["dtype"],r["area"],r["department_name"]), one=True)
        if existing:
            dept_id = existing["id"]
        else:
            coords = SAMPLE_AREAS.get(r["area"], (17.3850,78.4867))
            dept_id = db().execute("INSERT INTO departments(name,dtype,area,lat,lon) VALUES(?,?,?,?,?)",
                                   (r["department_name"],r["dtype"],r["area"],coords[0],coords[1])).lastrowid
    db().execute("INSERT INTO users(name,email,password_hash,role,department_id,created_at) VALUES(?,?,?,?,?,?)",
                 (r["name"],r["email"],r["password_hash"],r["role"],dept_id,now()))
    db().execute("UPDATE registration_requests SET status='APPROVED',reviewed_by=?,reviewed_at=? WHERE id=?",
                 (g.user["id"],now(),rid))
    db().commit()
    return jsonify(ok=True,message="Registration request approved.")

@app.route("/api/admin/registration-requests/<int:rid>/reject", methods=["POST"])
@role_required("ADMIN")
def reject_registration_request(rid):
    r = q("SELECT id FROM registration_requests WHERE id=? AND status='PENDING'", (rid,), one=True)
    if not r: return jerr("Request not found or already reviewed.", 404)
    db().execute("UPDATE registration_requests SET status='REJECTED',reviewed_by=?,reviewed_at=? WHERE id=?",
                 (g.user["id"],now(),rid)); db().commit()
    return jsonify(ok=True,message="Registration request rejected.")

@app.route("/api/admin/users")
@role_required("ADMIN")
def admin_users():
    """Return account directory for the admin only. Never return password hashes or secrets."""
    rows = q("""SELECT u.id, u.name, u.email, u.role, u.created_at,
                      d.name AS department_name, d.dtype AS department_type, d.area AS department_area
               FROM users u LEFT JOIN departments d ON d.id=u.department_id
               ORDER BY CASE u.role WHEN 'CITIZEN' THEN 1 WHEN 'DEPARTMENT' THEN 2 ELSE 3 END,
                        lower(u.name), lower(u.email)""")
    users = []
    for r in rows:
        users.append({
            "id": r["id"], "name": r["name"], "email": r["email"],
            "role": r["role"], "created_at": r["created_at"],
            "department_name": r["department_name"],
            "department_type": r["department_type"],
            "department_area": r["department_area"]
        })
    return jsonify(items=users, counts={
        "CITIZEN": sum(1 for u in users if u["role"] == "CITIZEN"),
        "DEPARTMENT": sum(1 for u in users if u["role"] == "DEPARTMENT"),
        "ADMIN": sum(1 for u in users if u["role"] == "ADMIN")
    })

@app.route("/api/admin/dashboard")
@role_required("ADMIN")
def admin_dashboard():
    a = request.args
    rows = q("SELECT status, COUNT(*) n FROM complaints GROUP BY status")
    stats = dict(total=sum(r["n"] for r in rows), new=count(rows, "Pending Assignment"), assigned=count(rows, "Assigned", "Reopened"),
                 progress=count(rows, "In Progress"), verify=count(rows, "Awaiting Verification"), resolved=count(rows, "Resolved"),
                 high=q("SELECT COUNT(*) n FROM complaints WHERE severity IN ('High','Critical') AND status!='Resolved'", one=True)["n"])
    where, args = [], []
    if a.get("q"): where.append("c.public_id LIKE ?"); args.append(f"%{a['q'].strip()}%")
    for col, key in (("c.category", "category"), ("c.severity", "severity"), ("c.status", "status"), ("c.area", "area"), ("c.dept_id", "dept")):
        if a.get(key): where.append(f"{col}=?"); args.append(a[key])
    order = ("CASE c.severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, c.id DESC"
             if a.get("sort") == "severity" else "c.id DESC")
    items = q("SELECT c.*, u.name citizen_name, d.name dept_name FROM complaints c JOIN users u ON u.id=c.citizen_id "
              "LEFT JOIN departments d ON d.id=c.dept_id" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order, args)
    return jsonify(stats=stats, items=[ser(c) | {"duplicate_of": c["duplicate_of"]} for c in items],
                   departments=[dict(d) for d in q("SELECT id,name,dtype,area FROM departments ORDER BY dtype,area")], areas=SERVICE_LOCALITIES,
                   statuses=["Pending Assignment", "Assigned", "In Progress", "Awaiting Verification", "Resolved", "Reopened"])

@app.route("/api/admin/complaints/<pid>/assign", methods=["POST"])
@role_required("ADMIN")
def admin_assign(pid):
    c = fetch_complaint(pid); f = body()
    # New assignment UI sends work category and service locality separately.
    dtype = (f.get("dtype") or "").strip().upper()
    area = (f.get("area") or "").strip()
    d = None
    if dtype or area:
        if dtype not in DEPT_TYPES:
            return jerr("Choose a valid work category.")
        if area not in SERVICE_LOCALITIES:
            return jerr("Choose a valid Hyderabad or Rangareddy locality.")
        d = q("SELECT * FROM departments WHERE dtype=? AND lower(area)=lower(?) ORDER BY id LIMIT 1", (dtype, area), one=True)
        if not d:
            coords = SAMPLE_AREAS.get(area, (17.3850, 78.4867))
            dept_name = f"{DEPT_TYPES[dtype]} - {area}"
            did = db().execute("INSERT INTO departments(name,dtype,area,lat,lon) VALUES(?,?,?,?,?)", (dept_name, dtype, area, coords[0], coords[1])).lastrowid
            d = q("SELECT * FROM departments WHERE id=?", (did,), one=True)
    else:
        d = q("SELECT * FROM departments WHERE id=?", (f.get("dept_id"),), one=True)
    if not d: return jerr("Select a valid work category and locality.")
    if c["status"] in ("Awaiting Verification", "Resolved"): return jerr("This complaint can no longer be reassigned.")
    remark = (f.get("remark") or "").strip()[:1000]
    new_status = c["status"] if c["dept_id"] == d["id"] and c["status"] in ("In Progress", "Reopened") else "Assigned"
    note = f"{'Reassigned' if c['dept_id'] else 'Assigned'} to {d['name']}."
    if c["suggested_dept_id"] and c["suggested_dept_id"] != d["id"]: note += " (Admin overrode the suggested department.)"
    if remark: note += f" Remark: {remark}"
    db().execute("UPDATE complaints SET dept_id=?, status=?, admin_remark=?, assigned_at=?, updated_at=? WHERE id=?",
                 (d["id"], new_status, remark, now(), now(), c["id"]))
    add_history(c["id"], new_status, note, g.user["name"]); db().commit()
    return jsonify(ok=True, message=f"Complaint assigned to {d['name']}.")

@app.route("/api/admin/complaints/<pid>/severity", methods=["POST"])
@role_required("ADMIN")
def admin_severity(pid):
    c = fetch_complaint(pid); f = body()
    s, note = f.get("severity"), (f.get("note") or "").strip()[:500]
    if s not in SEVERITIES: return jerr("Invalid severity.")
    reason = f"Manually set by admin {g.user['email']} from {c['severity']} to {s}. {note}".strip()
    db().execute("UPDATE complaints SET severity=?, severity_reason=?, severity_overridden=1, updated_at=? WHERE id=?", (s, reason, now(), c["id"]))
    add_history(c["id"], c["status"], f"Severity changed {c['severity']} -> {s}. {note}", g.user["name"]); db().commit()
    return jsonify(ok=True, message="Severity updated.")

@app.route("/api/admin/complaints/<pid>/verify", methods=["POST"])
@role_required("ADMIN")
def admin_verify(pid):
    c = fetch_complaint(pid); f = body()
    if c["status"] != "Awaiting Verification": return jerr("Nothing to verify for this complaint.")
    act, note = f.get("action"), (f.get("note") or "").strip()[:1000]
    if act == "resolve":
        db().execute("UPDATE complaints SET status='Resolved', resolved_at=?, updated_at=? WHERE id=?", (now(), now(), c["id"]))
        add_history(c["id"], "Resolved", f"Resolution verified by admin. {note}", g.user["name"]); msg = "Complaint marked Resolved."
    elif act == "reopen":
        db().execute("UPDATE complaints SET status='Reopened', updated_at=? WHERE id=?", (now(), c["id"]))
        add_history(c["id"], "Reopened", f"Resolution rejected by admin. {note}", g.user["name"]); msg = "Complaint reopened and sent back to the department."
    else:
        return jerr("Invalid action.")
    db().commit()
    return jsonify(ok=True, message=msg)

@app.route("/api/admin/invitations")
@role_required("ADMIN")
def admin_invitations():
    rows = q("SELECT i.id,i.role,i.created_at,i.expires_at,i.used_at,d.name dept_name,u.email created_by_email,w.email used_by_email "
             "FROM invitations i LEFT JOIN departments d ON d.id=i.department_id LEFT JOIN users u ON u.id=i.created_by "
             "LEFT JOIN users w ON w.id=i.used_by ORDER BY i.id DESC LIMIT 50")   # never returns codes or hashes
    out = [dict(r) | {"status": "Used" if r["used_at"] else "Expired" if r["expires_at"] < now() else "Active"} for r in rows]
    return jsonify(items=out)

@app.route("/api/admin/invitations", methods=["POST"])
@role_required("ADMIN")
def admin_create_invitation():
    f = body(); role = f.get("role")
    if role not in ("ADMIN", "DEPARTMENT"): return jerr("Choose Admin or Department.")
    dept_id = None
    if role == "DEPARTMENT":
        d = q("SELECT * FROM departments WHERE id=?", (f.get("department_id"),), one=True)
        if not d: return jerr("Select a valid department.")
        dept_id = d["id"]
    try: days = int(f.get("days") or 7)
    except (TypeError, ValueError): return jerr("Validity must be a number of days.")
    if not 1 <= days <= 30: return jerr("Validity must be between 1 and 30 days.")
    code, exp = create_invitation(role, dept_id, g.user["id"], days)
    return jsonify(ok=True, code=code, expires_at=exp, role=role,
                   department=(d["name"] if dept_id else None), area=(d["area"] if dept_id else None)), 201

# ----------------------------------------------------------------- department
@app.route("/api/dept/dashboard")
@role_required("DEPARTMENT")
def dept_dashboard():
    did, a = g.user["department_id"], request.args
    dept = q("SELECT id,name,area FROM departments WHERE id=?", (did,), one=True)
    rows = q("SELECT status, COUNT(*) n FROM complaints WHERE dept_id=? GROUP BY status", (did,))
    stats = dict(total=sum(r["n"] for r in rows), pending=count(rows, "Assigned", "Reopened"), progress=count(rows, "In Progress", "Awaiting Verification"),
                 resolved=count(rows, "Resolved"),
                 high=q("SELECT COUNT(*) n FROM complaints WHERE dept_id=? AND severity IN ('High','Critical') AND status!='Resolved'", (did,), one=True)["n"])
    where, args = ["c.dept_id=?"], [did]
    if a.get("status"): where.append("c.status=?"); args.append(a["status"])
    if a.get("severity"): where.append("c.severity=?"); args.append(a["severity"])
    items = q("SELECT c.* FROM complaints c WHERE " + " AND ".join(where) +
              " ORDER BY CASE c.severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, c.id DESC", args)
    return jsonify(dept=dict(dept), stats=stats, items=[ser(c) for c in items],
                   statuses=["Assigned", "In Progress", "Awaiting Verification", "Resolved", "Reopened"])

@app.route("/api/dept/complaints/<pid>/update", methods=["POST"])
@role_required("DEPARTMENT")
def dept_update(pid):
    c = fetch_complaint(pid)  # 403 unless assigned to the logged-in department
    new, remark = request.form.get("status", ""), request.form.get("remark", "").strip()[:1000]
    if new not in DEPT_TRANSITIONS.get(c["status"], []): return jerr(f"Invalid status change from '{c['status']}' to '{new}'.")
    try:
        res = save_image(request.files.get("resolution_image")) or c["resolution_image"]
    except ValueError as e:
        return jerr(str(e))
    if new == "Awaiting Verification" and (not res or not remark):
        return jerr("Work remarks and a resolution (after) image are required before requesting verification.")
    db().execute("UPDATE complaints SET status=?, dept_remark=?, resolution_image=?, updated_at=? WHERE id=?",
                 (new, remark or c["dept_remark"], res, now(), c["id"]))
    add_history(c["id"], new, remark or "Status updated by department.", g.user["name"]); db().commit()
    return jsonify(ok=True, message=f"Status updated to {new}.")

@app.after_request
def security_headers(resp):
    resp.headers["Permissions-Policy"] = "geolocation=(self)"   # allow GPS for our own pages only
    return resp

init_db()

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["seed"]:
        for role, email, pw in seed(): print(f"{role:11} {email:42} {pw}")
        print("Seed complete.")
    elif a[:1] == ["departments"]:
        with app.app_context():
            for d in q("SELECT id,name,area FROM departments ORDER BY id"): print(f"{d['id']:3}  {d['name']}  (area: {d['area']})")
    elif a[:1] == ["invite"] and len(a) >= 2 and a[1] in ("admin", "dept"):
        days = int(a[a.index("--days") + 1]) if "--days" in a else 7
        with app.app_context():
            if a[1] == "admin":
                code, exp = create_invitation("ADMIN", None, None, days)
                print(f"Admin invitation code (shown once): {code}\nExpires: {exp}")
            else:
                if len(a) < 3 or not a[2].isdigit() or not q("SELECT 1 FROM departments WHERE id=?", (int(a[2]),), one=True):
                    sys.exit("Usage: python app.py invite dept <department_id> [--days N]   (see: python app.py departments)")
                d = q("SELECT * FROM departments WHERE id=?", (int(a[2]),), one=True)
                code, exp = create_invitation("DEPARTMENT", d["id"], None, days)
                print(f"Department invitation code (shown once): {code}\nDepartment: {d['name']}\nArea: {d['area']}\nExpires: {exp}")
    elif a:
        sys.exit("Usage: python app.py [seed | departments | invite admin [--days N] | invite dept <department_id> [--days N]]")
    else:
        seed()
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
