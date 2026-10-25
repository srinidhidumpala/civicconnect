// Shared frontend helpers. The frontend talks to the backend ONLY through /api/* (JSON over fetch).
let CSRF = null, ME = null, CFG = {};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const slug = s => String(s).toLowerCase().replace(/ /g, '-');
const statusBadge = s => `<span class="badge st-${slug(s)}">${esc(s)}</span>`;
const sevBadge = s => `<span class="badge sv-${slug(s)}">${esc(s)}</span>`;
const HOME = {CITIZEN: 'citizen.html', ADMIN: 'admin.html', DEPARTMENT: 'dept.html'};
const LOGIN_PAGE = {CITIZEN: 'login.html', ADMIN: 'admin-login.html', DEPARTMENT: 'dept-login.html'};

async function api(path, {method = 'GET', body, form} = {}) {
  const opt = {method, headers: {}, credentials: 'same-origin'};
  if (CSRF) opt.headers['X-CSRF-Token'] = CSRF;
  if (form) opt.body = form;
  else if (body) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch('/api' + path, opt); } catch (e) { throw new Error('Cannot reach the server. Is the backend running?'); }
  let d = {}; try { d = await r.json(); } catch (e) {}
  if (!r.ok) { const e = new Error(d.error || 'Request failed'); e.status = r.status; e.errors = d.errors; throw e; }
  return d;
}

function flash(msg, type = 'error') {
  const box = $('flash'); if (!box) return alert(msg);
  box.innerHTML = `<div class="flash ${type}">${esc(msg)}</div>`; window.scrollTo(0, 0);
}

// roles: e.g. 'CITIZEN' or 'ADMIN'. Pass null for public pages.
async function boot(roles) {
  let d;
  try { d = await api('/me'); } catch (e) { document.body.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return false; }
  CSRF = d.csrf; ME = d.user; CFG = d;
  if (roles) {
    if (!ME) { location.href = LOGIN_PAGE[roles.split(',')[0]] || 'index.html'; return false; }
    if (!roles.split(',').includes(ME.role)) { location.href = HOME[ME.role]; return false; }
  }
  renderNav(); return true;
}

function renderNav() {
  let links = '';
  if (!ME) links = `<span class="grp">Citizen: <a href="login.html">Login</a><a href="register.html">Register</a></span>`
    + `<span class="grp">Admin: <a href="admin-login.html">Login</a><a href="admin-register.html">Register</a></span>`
    + `<span class="grp">Department: <a href="dept-login.html">Login</a><a href="dept-register.html">Register</a></span>`;
  else {
    if (ME.role === 'CITIZEN') links = `<a href="citizen.html">Dashboard</a><a href="new-complaint.html">Report Issue</a>`;
    else links = `<a href="${HOME[ME.role]}">Dashboard</a>`;
    links += `<span class="who">${esc(ME.name)} · ${esc(ME.role)}</span><button class="link" id="logoutBtn">Logout</button>`;
  }
  $('nav').innerHTML = `<a class="brand" href="index.html">🏙️ CivicConnect</a><nav>${links}</nav>`;
  const lb = $('logoutBtn');
  if (lb) lb.onclick = async () => { await api('/logout', {method: 'POST'}); location.href = 'index.html'; };
}

const LEAFLET_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const LEAFLET_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// ---------------------------------------------------------------- auth form helpers
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// Shows one or many error messages in the #flash box.
function showErrors(list) {
  const box = $('flash'); if (!box) return alert(list.join('\n'));
  box.innerHTML = list.length === 1 ? `<div class="flash error" role="alert">${esc(list[0])}</div>`
    : `<div class="flash error" role="alert"><b>Please fix the following:</b><ul class="errs">${list.map(m => `<li>${esc(m)}</li>`).join('')}</ul></div>`;
  window.scrollTo(0, 0);
}

// Client-side checks (the server re-validates everything). strict = admin/department password rules.
function checkIdentity(name, email, nameLabel = 'Full name') {
  const e = [];
  if (!name.trim()) e.push(`${nameLabel} is required.`);
  if (!EMAIL_RE.test(email.trim())) e.push('Enter a valid email address.');
  return e;
}
function checkPassword(pw, pw2, strict = false) {
  const e = [], need = strict ? 10 : 8;
  if (pw.length < need) e.push(`Password must be at least ${need} characters.`);
  else if (strict && !(/[A-Za-z]/.test(pw) && /\d/.test(pw))) e.push('Password must contain at least one letter and one number.');
  if (pw !== pw2) e.push('Passwords do not match.');
  return e;
}

// Wires a form to a POST endpoint with validation, loading feedback, success message and redirect.
// o: {form, button, path, collect(), validate(data)->[errors], success(d)->msg, redirect(d)->url, busy}
function authForm(o) {
  const f = $(o.form), b = $(o.button), label = b.textContent;
  f.setAttribute('novalidate', '');
  f.onsubmit = async e => {
    e.preventDefault();
    const data = o.collect(), errs = o.validate ? o.validate(data) : [];
    if (errs.length) return showErrors(errs);
    b.disabled = true; b.textContent = o.busy || 'Please wait…'; flash(o.busy || 'Please wait…', 'warn');
    try {
      const d = await api(o.path, {method: 'POST', body: data});
      if (d.csrf) CSRF = d.csrf;
      flash(o.success(d), 'ok');
      if (o.stay) {
        f.reset();
        b.disabled = false; b.textContent = label;
        return;
      }
      setTimeout(() => { location.href = o.redirect(d); }, 900);     // button stays disabled: no double submit
    } catch (err) {
      b.disabled = false; b.textContent = label;
      showErrors(err.errors && err.errors.length ? err.errors : [err.message]);
    }
  };
}

// Shows "Registration successful" on a login page reached after registering.
function showRegisteredNotice() {
  if (new URLSearchParams(location.search).get('registered')) flash('Registration successful. Please log in.', 'ok');
}
