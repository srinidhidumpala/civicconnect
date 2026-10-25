# AI-Based Smart Civic Complaint System

    civic-complaint-system/
    ├── backend/    Flask JSON API + SQLite + image storage + business rules (severity, routing, duplicates)
    │   ├── app.py  all /api/* routes, database schema, security
    │   ├── ai.py   optional YOLOv8 hook (honest fallback if no weights)
    │   ├── test_flow.py   52 end-to-end + security checks (complaint workflow)
    │   ├── test_auth.py   71 checks for role registration / login / access control
    │   ├── instance/ (database)   uploads/ (images)   model/ (put best.pt here)
    └── frontend/   plain HTML + CSS + JavaScript (Leaflet maps); talks to the backend ONLY via fetch('/api/...')
        ├── index, citizen, new-complaint, complaint, admin, dept (.html)
        ├── login, register              (Citizen)
        ├── admin-login, admin-register  (Admin)
        ├── dept-login, dept-register    (Department)
        ├── staff-login.html             (old URL; just links to the two separate logins)
        ├── css/style.css
        └── js/app.js  (shared helpers: api(), auth guard, navbar)

## Run (Windows, PowerShell or CMD)
    cd backend
    python -m venv venv
    venv\Scripts\activate          (PowerShell may need: Set-ExecutionPolicy -Scope Process RemoteSigned)
    pip install -r requirements.txt
    python app.py seed        # creates departments, the first admin, demo department logins (safe to re-run)
    python app.py             # open http://localhost:5000

The backend also serves the `frontend/` folder, so frontend and backend share one origin
(this keeps login cookies and CSRF protection simple and safe). There is no separate frontend server to start.
Existing databases are upgraded automatically (a new `invitations` table is added; users and complaints are untouched).

## Pages and roles
| Role | Register | Login | Dashboard after login |
|---|---|---|---|
| Citizen | /register.html | /login.html | /citizen.html |
| Admin | /admin-register.html (creates an account immediately in demo mode) | /admin-login.html | /admin.html |
| Department | /dept-register.html (creates an account immediately) | /dept-login.html | /dept.html |

Each login endpoint accepts only its own role (a citizen cannot log in on the admin page, etc.). The role is never
taken from the request: it is stored from the invitation (admin/department) or fixed to CITIZEN (citizen registration).
Authorization is enforced on the server for every `/api/*` route; the frontend redirects are only a convenience.

## How admin and department accounts are created securely
Admin and department registration forms do not ask applicants to type invitation codes. In this demo build, successful registration immediately creates the corresponding account, hashes the password, and allows sign-in using the chosen email and password. Department accounts are linked to a department record and area. The old registration-request approval endpoints remain for compatibility with earlier demo data, but newly registered accounts do not wait for approval.

**How to approve your new registrations:**
1. Start the backend with `python app.py` from the `backend` folder.
2. Open `http://localhost:5000/admin-login.html`.
3. Sign in with the bootstrap admin credentials listed below (unless you configured custom credentials before the first seed).
4. Admin and Department accounts created through the registration forms can sign in immediately; no approval step is required for those new accounts.
5. Approve the Admin and Department requests. They can then sign in using the exact email and password they used during registration.

If the bootstrap admin account does not exist in your database, stop the server and run `python app.py seed` from the `backend` folder. The default demo credentials are `admin@civic.demo` / `Admin@123`. For a local demo only, if you have forgotten a previously customized bootstrap password, use a clean database only if you are comfortable losing existing demo records; otherwise reset the password through a controlled administrator process. Do not reset a live production database.

For the initial administrator, bootstrap the database from the command line. Do not expose a public self-service path that grants unrestricted administrator privileges.

**First admin (bootstrap).** `python app.py seed` creates one admin. Set your own credentials *before* the first seed:

    set ADMIN_EMAIL=you@city.gov
    set ADMIN_PASSWORD=A-long-unique-Passw0rd
    python app.py seed

(Without these it creates the demo admin `admin@civic.demo` / `Admin@123`. Change or delete it for any real deployment;
also delete the demo `*@civic.demo` department users, whose password is `Dept@123`.)

The Admin Dashboard still contains an optional legacy invitation generator for controlled account provisioning. **Security warning:** unrestricted public Admin self-registration gives any visitor administrator privileges and is not safe for a real public production deployment. This immediate-access behavior is intended for a local college demo only. Before publishing, restore an administrator-controlled process for creating Admin accounts and verify Department organizations. Also replace demo credentials, configure HTTPS and `COOKIE_SECURE=1`, set a strong `SECRET_KEY`, and deploy behind a production WSGI server rather than Flask's development server.

**Department scope.** A department user is attached to one `departments` row (type + area, e.g. "Road/PWD Department -
Moinabad") and only sees/updates complaints whose `dept_id` is that department. The area is therefore the department's
own area; an admin may still assign a complaint to any department (the existing override feature).

## Demo accounts
| Role | Email | Password |
|---|---|---|
| Admin (/admin-login.html) | admin@civic.demo | Admin@123 |
| Road/PWD Moinabad (/dept-login.html) | road.moinabad@civic.demo | Dept@123 |
| Road/PWD Himayatnagar | road.himayatnagar@civic.demo | Dept@123 |
| Others | `<type>.<area>@civic.demo` (road, sanitation, electrical, water, fire, general x moinabad, himayatnagar) | Dept@123 |
Citizens register at /register.html.

## Test
    cd backend
    python test_flow.py     # complaint workflow
    python test_auth.py     # registration / login / role-based access

## Demo tips
- GPS works only on http://localhost or https (phones on plain http://<LAN-IP> block GPS; click the map instead).
- Leaflet and map tiles load from the internet (unpkg + OpenStreetMap).
- Routing demo: click near Moinabad (17.3166, 78.2646) or Himayatnagar (17.4008, 78.4824). Far away -> "Unmapped".
- Reset demo: stop server, delete backend/instance/civic.db and backend/uploads/*, run `python app.py seed`.

## API summary (backend)
GET /api/me · POST /api/register /api/login (citizen) /api/logout
POST /api/admin/register /api/admin/login · POST /api/dept/register /api/dept/login
GET|POST /api/admin/invitations (admin only; list / create one-time codes) · GET /api/citizen/dashboard · POST /api/complaints · GET /api/complaints/<id>
GET /api/admin/dashboard · POST /api/admin/complaints/<id>/{assign,severity,verify}
GET /api/dept/dashboard · POST /api/dept/complaints/<id>/update · GET /api/media/<file>


## Latest project updates

- The Admin dashboard no longer displays the **Registration invitations** panel.
- Citizen, Admin, and Department dashboards display the signed-in account profile. Department profiles include the linked department and service locality.
- Department registration now uses separate category and locality dropdowns. The backend links accounts to the matching department category + locality, rather than trusting a manually typed department name.
- The complaint form includes a separate locality dropdown with 100 Hyderabad and Rangareddy localities. The selected locality is stored with the complaint and used to prefer a matching department when one exists.
- The department dashboard filters assigned complaints by the exact department record. If an older account was registered under the wrong category/locality, register a fresh account using the correct category and locality, then assign the complaint to that matching department in Admin.
- The supplied YOLO training notebook is included as `projectstage.ipynb` in the project root. Run it in Google Colab with your dataset/Drive paths configured. When training finishes, copy the trained `best.pt` weights to `backend/model/best.pt` (create the `model` folder if needed). The existing `backend/ai.py` automatically loads that file when Ultralytics is installed. Do not commit large private datasets or secrets into the ZIP/repository.

### Locality selection behavior

The locality list is a convenience list for Hyderabad and Rangareddy. It is not an official municipal jurisdiction boundary dataset. GPS coordinates and manually selected map points are still retained for complaint location evidence. A matching department category and locality is preferred for routing; otherwise, the complaint remains available for administrator assignment.


### Admin complaint assignment: separate work and locality selectors
The complaint detail page now has two independent dropdowns for assignment: **Work category** (Road/PWD, Municipal/Sanitation, Electrical, Water/Drainage, Fire & Emergency, General Municipal) and **Service locality** (150 locality names for Hyderabad and Rangareddy areas). Selecting both routes the complaint to the department record matching that category and locality. If no matching department record exists yet, the backend creates the matching department record so a department account registered with the same category and locality can link to it. Locality names are service-area choices for the project, not official jurisdiction boundaries.
