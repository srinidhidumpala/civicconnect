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
