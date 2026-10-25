"""Role registration / login / access-control tests (temp DB).  Run inside backend/:  python test_auth.py"""
import os, tempfile
tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "t.db"); os.environ["UPLOAD_DIR"] = os.path.join(tmp, "up")
import app as A
A.seed(); res = []
def check(name, cond): res.append(bool(cond)); print(("PASS  " if cond else "FAIL  ") + name)

class C:
    def __init__(s): s.c = A.app.test_client(); s.t = s.c.get("/api/me").get_json()["csrf"]
    def get(s, u): return s.c.get(u)
    def j(s, u, d, tok=True): return s.c.post(u, json=d, headers={"X-CSRF-Token": s.t} if tok else {})
    def login(s, path, e, p):
        r = s.j(path, dict(email=e, password=p))
        if r.status_code == 200: s.t = r.get_json()["csrf"]
        return r
def clear_rl(): A._RL.clear()
def code_for(role, dept_id=None):
    with A.app.app_context(): return A.create_invitation(role, dept_id, None, 7)[0]
def row(sql, *a):
    with A.app.app_context(): return A.q(sql, a, one=True)

PW = "Str0ngPassw0rd"
# ---------------------------------------------------------------- citizen
c = C()
check("citizen register 201", c.j("/api/register", dict(name="Ravi", email="ravi@x.com", password="password1", confirm="password1")).status_code == 201)
check("citizen duplicate 400", c.j("/api/register", dict(name="Ravi", email="RAVI@x.com", password="password1", confirm="password1")).status_code == 400)
check("citizen invalid fields 400 with error list", len(c.j("/api/register", dict(name="", email="bad", password="1", confirm="2")).get_json()["errors"]) >= 3)
r = c.login("/api/login", "ravi@x.com", "password1"); check("citizen login -> role CITIZEN", r.status_code == 200 and r.get_json()["role"] == "CITIZEN")
check("citizen reaches citizen API", c.get("/api/citizen/dashboard").status_code == 200)
check("citizen -> admin API 403", c.get("/api/admin/dashboard").status_code == 403)
check("citizen -> dept API 403", c.get("/api/dept/dashboard").status_code == 403)
check("citizen cannot list/create invitations", c.get("/api/admin/invitations").status_code == 403 and c.j("/api/admin/invitations", dict(role="ADMIN")).status_code == 403)
check("citizen cannot self-escalate via role field", c.j("/api/register", dict(name="E", email="e@x.com", password="password1", confirm="password1", role="ADMIN")).status_code == 201 and row("SELECT role FROM users WHERE email='e@x.com'")[0] == "CITIZEN")
check("logout 200", c.j("/api/logout", {}).status_code == 200)
check("after logout citizen API 401", c.get("/api/citizen/dashboard").status_code == 401)

# ---------------------------------------------------------------- admin
a = C()
check("admin register w/o code 403", a.j("/api/admin/register", dict(name="Ann", email="ann@city.gov", password=PW, confirm=PW)).status_code == 403)
check("admin register wrong code 403", a.j("/api/admin/register", dict(name="Ann", email="ann@city.gov", password=PW, confirm=PW, code="AAAAA-AAAAA-AAAAA-AAAAA")).status_code == 403)
check("no admin created by failures", row("SELECT 1 FROM users WHERE email='ann@city.gov'") is None)
code = code_for("ADMIN")
check("admin weak password 400", a.j("/api/admin/register", dict(name="Ann", email="ann@city.gov", password="short", confirm="short", code=code)).status_code == 400)
check("admin password mismatch 400", a.j("/api/admin/register", dict(name="Ann", email="ann@city.gov", password=PW, confirm=PW + "x", code=code)).status_code == 400)
check("admin bad email 400", a.j("/api/admin/register", dict(name="Ann", email="nope", password=PW, confirm=PW, code=code)).status_code == 400)
check("code NOT consumed by failed validation", row("SELECT used_at FROM invitations WHERE role='ADMIN' ORDER BY id DESC LIMIT 1")[0] is None)
check("admin register with valid code 201", a.j("/api/admin/register", dict(name="Ann", email="ann@city.gov", password=PW, confirm=PW, code=code.lower())).status_code == 201)
check("admin stored with role ADMIN + hashed pw", (lambda u: u["role"] == "ADMIN" and u["password_hash"] != PW and u["password_hash"].startswith(("scrypt", "pbkdf2")))(row("SELECT * FROM users WHERE email='ann@city.gov'")))
check("code is stored hashed, not plain", row("SELECT 1 FROM invitations WHERE code_hash=?", code) is None and row("SELECT 1 FROM invitations WHERE code_hash=?", A.hash_code(code)) is not None)
check("used code cannot be reused 403", a.j("/api/admin/register", dict(name="Bob", email="bob@city.gov", password=PW, confirm=PW, code=code)).status_code == 403)
code2 = code_for("ADMIN")
check("duplicate admin email 400", a.j("/api/admin/register", dict(name="Ann2", email="ann@city.gov", password=PW, confirm=PW, code=code2)).status_code == 400)
check("duplicate attempt did not burn the code", row("SELECT used_at FROM invitations WHERE role='ADMIN' ORDER BY id DESC LIMIT 1")[0] is None)
check("department code cannot create an admin", a.j("/api/admin/register", dict(name="X", email="x@city.gov", password=PW, confirm=PW, code=code_for("DEPARTMENT", 1))).status_code == 403)
exp = code_for("ADMIN")
with A.app.app_context(): A.db().execute("UPDATE invitations SET expires_at='2000-01-01 00:00:00' WHERE code_hash=?", (A.hash_code(exp),)); A.db().commit()
check("expired code 403", a.j("/api/admin/register", dict(name="X", email="x@city.gov", password=PW, confirm=PW, code=exp)).status_code == 403)
check("admin invalid password 401", a.login("/api/admin/login", "ann@city.gov", "wrong").status_code == 401)
check("unknown email 401 (same message)", a.login("/api/admin/login", "ghost@x.com", "wrong").get_json()["error"] == "Invalid email or password.")
check("citizen creds rejected at admin login 401", a.login("/api/admin/login", "ravi@x.com", "password1").status_code == 401)
check("admin creds rejected at citizen login 401", a.login("/api/login", "ann@city.gov", PW).status_code == 401)
check("admin creds rejected at dept login 401", a.login("/api/dept/login", "ann@city.gov", PW).status_code == 401)
r = a.login("/api/admin/login", "ann@city.gov", PW); check("admin login -> role ADMIN", r.status_code == 200 and r.get_json()["role"] == "ADMIN")
check("admin reaches admin API", a.get("/api/admin/dashboard").status_code == 200)
check("admin -> citizen API 403", a.get("/api/citizen/dashboard").status_code == 403)
check("admin -> dept API 403", a.get("/api/dept/dashboard").status_code == 403)

# invitations issued by an authorised admin
r = a.j("/api/admin/invitations", dict(role="ADMIN")); check("admin creates admin invite", r.status_code == 201 and len(r.get_json()["code"]) == 23)
check("dept invite needs valid department", a.j("/api/admin/invitations", dict(role="DEPARTMENT", department_id=9999)).status_code == 400)
check("invalid role invite rejected", a.j("/api/admin/invitations", dict(role="CITIZEN")).status_code == 400)
check("invite days out of range rejected", a.j("/api/admin/invitations", dict(role="ADMIN", days=99)).status_code == 400)
lst = a.get("/api/admin/invitations").get_json()["items"]
check("invitation list never exposes codes/hashes", lst and all("code" not in i and "code_hash" not in i for i in lst))

# ---------------------------------------------------------------- department
with A.app.app_context(): D = {d["name"]: d for d in A.q("SELECT * FROM departments")}
road_m, road_h = D["Road/PWD Department - Moinabad"], D["Road/PWD Department - Himayatnagar"]
p = C(); dcode = a.j("/api/admin/invitations", dict(role="DEPARTMENT", department_id=road_m["id"])).get_json()["code"]
base = dict(department_name="Road/PWD Department", name="Sita", email="sita@pwd.gov", area="Moinabad", password=PW, confirm=PW)
check("dept register w/o code 403", p.j("/api/dept/register", {**base, "code": ""}).status_code == 403)
check("admin code cannot create dept user 403", p.j("/api/dept/register", {**base, "code": code_for("ADMIN")}).status_code == 403)
check("wrong department name 400", p.j("/api/dept/register", {**base, "code": dcode, "department_name": "Fire Department"}).status_code == 400)
check("wrong area 400", p.j("/api/dept/register", {**base, "code": dcode, "area": "Himayatnagar"}).status_code == 400)
check("missing dept fields 400", p.j("/api/dept/register", {**base, "code": dcode, "department_name": "", "area": ""}).status_code == 400)
check("dept weak password 400", p.j("/api/dept/register", {**base, "code": dcode, "password": "abc", "confirm": "abc"}).status_code == 400)
check("code not burned by failed validation", row("SELECT used_at FROM invitations WHERE code_hash=?", A.hash_code(dcode))[0] is None)
check("dept register with authorised code 201", p.j("/api/dept/register", {**base, "code": dcode}).status_code == 201)
u = row("SELECT * FROM users WHERE email='sita@pwd.gov'")
check("dept user bound to the invited department with role DEPARTMENT", u["role"] == "DEPARTMENT" and u["department_id"] == road_m["id"] and u["password_hash"] != PW)
check("dept code single use", p.j("/api/dept/register", {**base, "code": dcode, "email": "other@pwd.gov"}).status_code == 403)
dcode2 = a.j("/api/admin/invitations", dict(role="DEPARTMENT", department_id=road_m["id"])).get_json()["code"]
check("duplicate dept email 400", p.j("/api/dept/register", {**base, "code": dcode2}).status_code == 400)
check("dept invalid login 401", p.login("/api/dept/login", "sita@pwd.gov", "wrong").status_code == 401)
check("citizen creds rejected at dept login", p.login("/api/dept/login", "ravi@x.com", "password1").status_code == 401)
r = p.login("/api/dept/login", "sita@pwd.gov", PW); check("dept login -> role DEPARTMENT", r.status_code == 200 and r.get_json()["role"] == "DEPARTMENT")
check("dept reaches dept API with own dept", p.get("/api/dept/dashboard").get_json()["dept"]["id"] == road_m["id"])
check("dept -> admin API 403", p.get("/api/admin/dashboard").status_code == 403 and p.get("/api/admin/invitations").status_code == 403)
check("dept -> citizen API 403", p.get("/api/citizen/dashboard").status_code == 403)
check("dept cannot create invitations", p.j("/api/admin/invitations", dict(role="ADMIN")).status_code == 403)

# department data isolation: complaint assigned to Moinabad road dept
with A.app.app_context():
    uid = A.q("SELECT id FROM users WHERE email='ravi@x.com'", one=True)[0]; ts = A.now()
    A.db().execute("INSERT INTO complaints(public_id,citizen_id,category,description,image,lat,lon,severity,status,dept_id,created_at,updated_at) VALUES('CMP-T-1',?,?,?,?,?,?,?,?,?,?,?)",
                   (uid, "Pothole", "t", "x.jpg", 17.32, 78.27, "High", "Assigned", road_m["id"], ts, ts)); A.db().commit()
check("owning dept sees complaint", [i["public_id"] for i in p.get("/api/dept/dashboard").get_json()["items"]] == ["CMP-T-1"])
o = C(); oc = a.j("/api/admin/invitations", dict(role="DEPARTMENT", department_id=road_h["id"])).get_json()["code"]
o.j("/api/dept/register", dict(department_name=road_h["name"], name="Hari", email="hari@pwd.gov", area="himayatnagar", password=PW, confirm=PW, code=oc))
o.login("/api/dept/login", "hari@pwd.gov", PW)
check("other dept (full-name + case-insensitive area) registered & sees nothing", o.get("/api/dept/dashboard").get_json()["items"] == [])
check("other dept cannot open complaint 403", o.get("/api/complaints/CMP-T-1").status_code == 403)
check("other dept cannot update complaint 403", o.c.post("/api/dept/complaints/CMP-T-1/update", data=dict(status="In Progress"), headers={"X-CSRF-Token": o.t}).status_code == 403)
check("owning dept can update status", p.c.post("/api/dept/complaints/CMP-T-1/update", data=dict(status="In Progress", remark="on it"), headers={"X-CSRF-Token": p.t}).status_code == 200)
check("admin sees all complaints", len(a.get("/api/admin/dashboard").get_json()["items"]) == 1)

# ---------------------------------------------------------------- session / csrf / throttling
check("logout dept 200 and session ended", p.j("/api/logout", {}).status_code == 200 and p.get("/api/dept/dashboard").status_code == 401)
check("logout admin ends session", a.j("/api/logout", {}).status_code == 200 and a.get("/api/admin/dashboard").status_code == 401)
an = A.app.test_client()
check("anonymous 401 on role APIs", all(an.get(u).status_code == 401 for u in ("/api/admin/dashboard", "/api/dept/dashboard", "/api/citizen/dashboard", "/api/admin/invitations")))
check("CSRF required on admin/dept register + login", all(an.post(u, json={}).status_code == 400 for u in ("/api/admin/register", "/api/dept/register", "/api/admin/login", "/api/dept/login")))
clear_rl(); t = C(); codes = [t.login("/api/admin/login", "ann@city.gov", "bad").status_code for _ in range(11)]
check("login brute-force throttled with 429", codes[:10] == [401] * 10 and codes[10] == 429)
check("even the right password is blocked while throttled", t.login("/api/admin/login", "ann@city.gov", PW).status_code == 429)
clear_rl(); t2 = C(); codes = [t2.j("/api/admin/register", dict(code="AAAAA-AAAAA-AAAAA-AAAAA")).status_code for _ in range(11)]
check("registration-code guessing throttled with 429", codes[10] == 429)
clear_rl()
print(f"\n{sum(res)}/{len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
