"""End-to-end API test using Flask's test client + temp DB.  Run (inside backend/): python test_flow.py"""
import io, os, re, tempfile
tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "t.db"); os.environ["UPLOAD_DIR"] = os.path.join(tmp, "up")
import app as A
from PIL import Image
A.seed(); res = []
def check(name, cond): res.append(bool(cond)); print(("PASS  " if cond else "FAIL  ") + name)
def img(fmt="PNG", name="x.png"):
    b = io.BytesIO(); Image.new("RGB", (60, 40), (120, 80, 40)).save(b, fmt); b.seek(0); return (b, name)
class C:
    def __init__(s): s.c = A.app.test_client(); s.t = s.c.get("/api/me").get_json()["csrf"]
    def get(s, u): return s.c.get(u)
    def j(s, u, d): return s.c.post(u, json=d, headers={"X-CSRF-Token": s.t})
    def f(s, u, d): return s.c.post(u, data=d, content_type="multipart/form-data", headers={"X-CSRF-Token": s.t})
    def login(s, e, p, portal="citizen"):
        r = s.j({"citizen": "/api/login", "admin": "/api/admin/login", "dept": "/api/dept/login"}[portal], dict(email=e, password=p))
        if r.status_code == 200: s.t = r.get_json()["csrf"]
        return r

cz = C()
check("frontend index served by backend", A.app.test_client().get("/").status_code == 200 and b"CivicConnect" in A.app.test_client().get("/").data)
check("frontend js served", A.app.test_client().get("/js/app.js").status_code == 200)
check("register ok", cz.j("/api/register", dict(name="Ravi", email="ravi@x.com", password="password1", confirm="password1")).status_code == 201)
check("duplicate email rejected", cz.j("/api/register", dict(name="Ravi", email="ravi@x.com", password="password1", confirm="password1")).status_code == 400)
check("invalid registration rejected", cz.j("/api/register", dict(name="", email="bad", password="123", confirm="9")).status_code == 400)
check("role cannot be injected at registration", cz.j("/api/register", dict(name="Evil", email="e@x.com", password="password1", confirm="password1", role="ADMIN")).status_code == 201 and
      A.app.app_context().__enter__() is not None and A.q("SELECT role FROM users WHERE email='e@x.com'", one=True)[0] == "CITIZEN")
check("invalid login 401", cz.login("ravi@x.com", "wrong").status_code == 401)
check("citizen login", cz.login("ravi@x.com", "password1").status_code == 200)
check("empty dashboard", cz.get("/api/citizen/dashboard").get_json()["stats"]["total"] == 0)
form = dict(category="Pothole", description="Deep pothole on main road near school", lat="17.3200", lon="78.2700", submit_key="k1")
check("missing location rejected", cz.f("/api/complaints", dict(category="Pothole", lat="", lon="", image=img())).status_code == 400)
check("unsupported type rejected", cz.f("/api/complaints", {**form, "submit_key": "z", "image": img("GIF", "x.gif")}).status_code == 400)
check("fake image rejected", cz.f("/api/complaints", {**form, "submit_key": "z", "image": (io.BytesIO(b"nope"), "x.png")}).status_code == 400)
r = cz.f("/api/complaints", {**form, "image": img()}); check("complaint created", r.status_code == 201)
pid = r.get_json()["public_id"]; print("      complaint id:", pid)
check("double submit returns same complaint", cz.f("/api/complaints", {**form, "image": img()}).get_json()["public_id"] == pid)
with A.app.app_context():
    row = A.q("SELECT * FROM complaints WHERE public_id=?", (pid,), one=True)
    check("saved with coords, severity, area, status", abs(row["lat"] - 17.32) < 1e-6 and row["severity"] == "Critical" and row["area"] == "Moinabad" and row["status"] == "Pending Assignment")
    check("exactly one row", A.q("SELECT COUNT(*) FROM complaints", one=True)[0] == 1)
dd = cz.get(f"/api/citizen/dashboard").get_json(); check("citizen sees own complaint", dd["items"][0]["public_id"] == pid)
check("citizen payload hides staff fields", "ai_note" not in dd["items"][0] and "citizen_email" not in dd["items"][0])

ad = C(); check("admin blocked on citizen portal", ad.login("admin@civic.demo", "Admin@123").status_code == 401)
check("admin login", ad.login("admin@civic.demo", "Admin@123", "admin").status_code == 200)
check("admin sees complaint", ad.get("/api/admin/dashboard").get_json()["items"][0]["public_id"] == pid)
check("admin filters", len(ad.get("/api/admin/dashboard?category=Pothole&severity=Critical").get_json()["items"]) == 1 and len(ad.get("/api/admin/dashboard?category=Waterlogging").get_json()["items"]) == 0)
det = ad.get(f"/api/complaints/{pid}").get_json()
check("admin detail has suggestion + staff fields", det["complaint"]["sugg_name"] == "Road/PWD Department - Moinabad" and "ai_note" in det["complaint"])
did = next(d["id"] for d in det["departments"] if d["name"] == "Road/PWD Department - Moinabad")
check("severity override", ad.j(f"/api/admin/complaints/{pid}/severity", dict(severity="High", note="checked")).status_code == 200)
check("admin assigns", ad.j(f"/api/admin/complaints/{pid}/assign", dict(dept_id=did, remark="urgent")).status_code == 200)
with A.app.app_context():
    row = A.q("SELECT * FROM complaints WHERE public_id=?", (pid,), one=True)
    check("assignment persisted", row["dept_id"] == did and row["status"] == "Assigned" and row["severity"] == "High" and row["severity_overridden"] == 1)

dp = C(); check("dept blocked on citizen portal", dp.login("road.moinabad@civic.demo", "Dept@123").status_code == 401)
dp.login("road.moinabad@civic.demo", "Dept@123", "dept")
check("assigned dept sees it", dp.get("/api/dept/dashboard").get_json()["items"][0]["public_id"] == pid)
ot = C(); ot.login("road.himayatnagar@civic.demo", "Dept@123", "dept")
check("other dept sees nothing", ot.get("/api/dept/dashboard").get_json()["items"] == [])
check("other dept detail 403", ot.get(f"/api/complaints/{pid}").status_code == 403)
check("other dept update 403", ot.f(f"/api/dept/complaints/{pid}/update", dict(status="In Progress")).status_code == 403)
check("illegal transition rejected", dp.f(f"/api/dept/complaints/{pid}/update", dict(status="Resolved")).status_code == 400)
check("-> In Progress", dp.f(f"/api/dept/complaints/{pid}/update", dict(status="In Progress", remark="Team dispatched")).status_code == 200)
check("verification w/o image rejected", dp.f(f"/api/dept/complaints/{pid}/update", dict(status="Awaiting Verification", remark="Filled")).status_code == 400)
check("-> Awaiting Verification with image", dp.f(f"/api/dept/complaints/{pid}/update", dict(status="Awaiting Verification", remark="Pothole filled", resolution_image=img("JPEG", "a.jpg"))).status_code == 200)

check("admin sees Awaiting Verification", ad.get(f"/api/complaints/{pid}").get_json()["complaint"]["status"] == "Awaiting Verification")
check("admin resolves", ad.j(f"/api/admin/complaints/{pid}/verify", dict(action="resolve", note="ok")).status_code == 200)
cd = cz.get(f"/api/complaints/{pid}").get_json()
check("citizen sees Resolved + evidence + remark", cd["complaint"]["status"] == "Resolved" and cd["complaint"]["resolution_image"] and cd["complaint"]["dept_remark"] == "Pothole filled")
check("history >= 6", len(cd["history"]) >= 6)
check("citizen resolved count 1", cz.get("/api/citizen/dashboard").get_json()["stats"]["resolved"] == 1)
check("resolution image downloadable when logged in", cz.get(cd["complaint"]["resolution_image"]).status_code == 200)

an = A.app.test_client()
check("anon 401 on all dashboards", all(an.get(u).status_code == 401 for u in ("/api/citizen/dashboard", "/api/admin/dashboard", "/api/dept/dashboard")))
check("anon 401 on media", an.get(cd["complaint"]["image"]).status_code == 401)
check("citizen 403 on admin/dept APIs", cz.get("/api/admin/dashboard").status_code == 403 and cz.get("/api/dept/dashboard").status_code == 403)
check("dept 403 on admin API", dp.get("/api/admin/dashboard").status_code == 403)
check("citizen cannot assign", cz.j(f"/api/admin/complaints/{pid}/assign", dict(dept_id=did)).status_code == 403)
c2 = C(); c2.j("/api/register", dict(name="Mina", email="m@x.com", password="password1", confirm="password1")); c2.login("m@x.com", "password1")
check("other citizen cannot view complaint", c2.get(f"/api/complaints/{pid}").status_code == 403)
check("CSRF: POST without token rejected", A.app.test_client().post("/api/login", json=dict(email="a", password="b")).status_code == 400)
with A.app.app_context(): check("password hashed", A.q("SELECT password_hash FROM users WHERE email='ravi@x.com'", one=True)[0].startswith(("scrypt", "pbkdf2")))
cz.f("/api/complaints", {**form, "submit_key": "k2", "image": img()})
with A.app.app_context(): check("not flagged duplicate when earlier one is Resolved", A.q("SELECT duplicate_of FROM complaints ORDER BY id DESC LIMIT 1", one=True)[0] is None)
cz.f("/api/complaints", {**form, "submit_key": "k3", "image": img()})
with A.app.app_context(): check("second open nearby complaint flagged duplicate", A.q("SELECT duplicate_of FROM complaints ORDER BY id DESC LIMIT 1", one=True)[0] is not None)
cz.f("/api/complaints", {**form, "submit_key": "k4", "lat": "28.61", "lon": "77.21", "category": "Garbage Accumulation", "image": img()})
with A.app.app_context():
    r_ = A.q("SELECT area,suggested_dept_id FROM complaints ORDER BY id DESC LIMIT 1", one=True); check("far location -> unmapped, no wrong auto-route", r_[0] is None and r_[1] is None)
print(f"\n{sum(res)}/{len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
