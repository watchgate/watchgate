from flask import Flask, render_template, request, redirect, url_for, session, flash
import subprocess
import requests
import socket
import datetime
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'YOUR_SECRET_KEY'  # Change this to a secure key in production

# Configure SQLAlchemy for SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///watchgate.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Postmark API key and sender email (update these with your actual details)
POSTMARK_API_KEY = '4e753184-c2ff-4bde-895d-eb81c1af4aa4'
POSTMARK_FROM_EMAIL = 'register@watchgate.io'

# Serializer for generating tokens
s = URLSafeTimedSerializer(app.secret_key)

# --- User Model ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plan = db.Column(db.String(50))
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    company = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120))  # This stores the hashed password
    is_verified = db.Column(db.Boolean, default=False)

# --- Asset Model for discovered subdomains and open ports ---
class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255))
    subdomain = db.Column(db.String(255), unique=True)
    ip = db.Column(db.String(50))
    open_ports = db.Column(db.String(255))      # e.g. "80, 443"
    web_services = db.Column(db.String(1000))   # e.g. "http://sub:80, https://sub:443"
    discovered_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

with app.app_context():
    db.create_all()

#############################
#      SETTINGS ROUTE       #
#############################

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not session.get('logged_in'):
        flash("Please login first.")
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash("User not found.")
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Update user info
        user.first_name = request.form.get('first_name')
        user.last_name = request.form.get('last_name')
        user.company = request.form.get('company')
        new_email = request.form.get('email')
        new_password = request.form.get('password')

        if new_email and new_email != user.email:
            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                flash("That email is already taken.")
                return redirect(url_for('settings'))
            user.email = new_email

        if new_password and new_password != "":
            # Hash the new password before saving it
            user.password = generate_password_hash(new_password)
            flash("Your password was updated successfully!")

        db.session.commit()
        flash("Profile updated!")
        return redirect(url_for('settings'))

    return render_template('settings.html', user=user)

@app.route('/update_profile')
def update_profile():
    # Placeholder for update profile functionality
    return "Update Profile functionality coming soon."

@app.route('/subscription')
def subscription():
    # Placeholder for subscription details
    return "Subscription page coming soon."

#############################
#      ANALYTICS ROUTE      #
#############################

@app.route('/analytics')
def analytics():
    # 1. Total Number of Domains scanned
    total_domains = db.session.query(Asset.domain).distinct().count()

    # 2. Total Number of Subdomains discovered
    total_subdomains = db.session.query(Asset.subdomain).count()

    # 3. Total Number of Open Ports discovered
    #    We assume "open_ports" is a comma-separated string of ports. 
    #    We can sum up the total count across all subdomains.
    all_assets = Asset.query.all()
    total_open_ports = 0
    total_web_ports = 0

    for asset in all_assets:
        if asset.open_ports:
            # Split on commas, strip whitespace
            ports = [p.strip() for p in asset.open_ports.split(',')]
            # Filter out any empty entries
            ports = [p for p in ports if p]
            total_open_ports += len(ports)

        # 4. Total number of web ports discovered
        #    We can parse "web_services" similarly if it’s a comma-separated string 
        #    of URLs or something similar.
        if asset.web_services:
            services = [s.strip() for s in asset.web_services.split(',')]
            services = [s for s in services if s]
            total_web_ports += len(services)

    return render_template('analytics.html',
                           total_domains=total_domains,
                           total_subdomains=total_subdomains,
                           total_open_ports=total_open_ports,
                           total_web_ports=total_web_ports)


#############################
#      MAIN APPLICATION     #
#############################

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/pricing')
def pricing():
    return render_template('pricing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        email = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            if not user.is_verified:
                flash("Please verify your email before signing in.")
                return redirect(url_for('login'))
            session['logged_in'] = True
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials. Please try again.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

def run_subfinder(domain):
    """
    Runs subfinder and stores discovered subdomains in the Asset model.
    """
    try:
        cmd = ["subfinder", "-d", domain, "-silent", "-s", "crtsh,alienvault,threatcrowd,github"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            return f"Error running subfinder: {result.stderr}"
        subdomains = result.stdout.strip().splitlines()

        resolved = []
        for sub in subdomains:
            try:
                ip = socket.gethostbyname(sub)
            except Exception:
                ip = "N/A"
            asset = Asset.query.filter_by(subdomain=sub).first()
            if asset:
                asset.ip = ip
            else:
                asset = Asset(domain=domain, subdomain=sub, ip=ip, open_ports=None, web_services=None)
                db.session.add(asset)
            resolved.append({
                "subdomain": sub,
                "ip": ip,
                "ports": asset.open_ports,
                "web_services": asset.web_services
            })
        db.session.commit()
        return resolved
    except Exception as e:
        return f"Exception occurred while running subfinder: {e}"

def parse_nmap_output(nmap_output, subdomain):
    """
    Parse nmap output from '-Pn -sV' to extract open ports and identify
    whether the service is http or ssl/http.
    Returns (open_ports_list, web_services_list)
    """
    open_ports = []
    web_services = []
    lines = nmap_output.splitlines()
    header_found = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "PORT" in line and "STATE" in line and "SERVICE" in line:
            header_found = True
            continue

        if header_found:
            parts = line.split()
            if len(parts) < 3:
                continue
            port_proto = parts[0]  # e.g. "80/tcp"
            state = parts[1]       # e.g. "open"
            service = parts[2]     # e.g. "http" or "ssl/http"
            if state.lower() == "open":
                port_num = port_proto.split("/")[0]
                open_ports.append(port_num)
                if "http" in service.lower():
                    if "ssl" in service.lower():
                        url = f"https://{subdomain}:{port_num}"
                        web_services.append(url)
                    else:
                        url = f"http://{subdomain}:{port_num}"
                        web_services.append(url)
    return open_ports, web_services

def run_nmap(target):
    """
    Runs Nmap with optimized flags to quickly return all open ports and
    attempt to identify services (including HTTP/HTTPS).
    Uses flags: -Pn (no ping), -n (no DNS resolution), -T4 (aggressive timing), and -sV (service detection).
    """
    try:
        cmd = ["nmap", "-Pn", "-n", "-T4", "-sV", target]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            return f"Error running nmap: {result.stderr}"
        open_ports, web_services = parse_nmap_output(result.stdout, target)
        return (open_ports, web_services)
    except Exception as e:
        return f"Exception occurred while running nmap: {e}"

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('logged_in'):
        flash("Please login first.")
        return redirect(url_for('login'))

    error = None
    scan_results = None
    subdomains = None
    scan_type = None

    if request.method == "POST":
        target = request.form.get("target")
        scan_type = request.form.get("scan_type")
        session['last_target'] = target
        if target:
            if scan_type == "subfinder":
                subdomains = run_subfinder(target)
            elif scan_type == "nmap":
                result = run_nmap(target)
                if isinstance(result, str):
                    scan_results = result
                else:
                    open_ports, web_services = result
                    scan_results = {"ports": open_ports, "web_services": web_services}
            elif scan_type == "both":
                subdomains = run_subfinder(target)
                for item in subdomains:
                    sub = item['subdomain']
                    result = run_nmap(sub)
                    if isinstance(result, str):
                        item['ports'] = result
                        item['web_services'] = None
                    else:
                        open_ports, web_services = result
                        ports_str = ", ".join(open_ports) if open_ports else ""
                        webs_str = ", ".join(web_services) if web_services else ""
                        asset = Asset.query.filter_by(subdomain=sub).first()
                        if asset:
                            asset.open_ports = ports_str
                            asset.web_services = webs_str
                            db.session.commit()
                        item['ports'] = ports_str
                        item['web_services'] = webs_str
            else:
                error = "Invalid scan type selected."
        else:
            error = "Please enter a target domain or IP."
    else:
        target = session.get('last_target')
        if target:
            assets = Asset.query.filter_by(domain=target).all()
            subdomains = []
            for asset in assets:
                subdomains.append({
                    "subdomain": asset.subdomain,
                    "ip": asset.ip,
                    "ports": asset.open_ports if asset.open_ports else "",
                    "web_services": asset.web_services if asset.web_services else ""
                })
    return render_template('dashboard.html', 
                           scan_results=scan_results, 
                           subdomains=subdomains,
                           error=error,
                           scan_type=scan_type)

@app.route('/nmap_scan')
def nmap_scan():
    subdomain = request.args.get('subdomain')
    if not subdomain:
        return redirect(url_for('dashboard'))
    result = run_nmap(subdomain)
    if isinstance(result, str):
        return redirect(url_for('dashboard'))
    else:
        open_ports, web_services = result
        ports_str = ", ".join(open_ports) if open_ports else ""
        webs_str = ", ".join(web_services) if web_services else ""
        asset = Asset.query.filter_by(subdomain=subdomain).first()
        if asset:
            asset.open_ports = ports_str
            asset.web_services = webs_str
            db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/stop_scan')
def stop_scan():
    # For now, clear the last target to cancel any ongoing scan.
    session.pop('last_target', None)
    flash("Scan stopped.")
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    plan = request.args.get('plan', 'community')
    if request.method == "POST":
        plan = request.form.get("plan", "community")
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        company = request.form.get("company")
        email = request.form.get("email")
        password = request.form.get("password")
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("An account with that email already exists. Please sign in.")
            return redirect(url_for('login'))
        hashed_password = generate_password_hash(password)
        new_user = User(plan=plan, first_name=first_name, last_name=last_name,
                        company=company, email=email, password=hashed_password, is_verified=False)
        db.session.add(new_user)
        db.session.commit()
        token = s.dumps(email, salt='email-confirm')
        send_verification_email(email, token)
        flash("Account created! Please check your email to verify your account before signing in.")
        return redirect(url_for('login'))
    return render_template('register.html', plan=plan)

@app.route('/verify/<token>')
def verify(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600)
    except SignatureExpired:
        flash("The verification link has expired. Please register again.")
        return redirect(url_for('register'))
    except BadSignature:
        flash("Invalid verification token.")
        return redirect(url_for('register'))
    user = User.query.filter_by(email=email).first()
    if user:
        user.is_verified = True
        db.session.commit()
        flash("Email verified successfully! You can now sign in.")
    else:
        flash("User not found. Please register again.")
    return redirect(url_for('login'))

def send_verification_email(user_email, token):
    verify_url = url_for('verify', token=token, _external=True)
    html_body = f'''
    <p>Thank you for registering with WatchGate. Please verify your email by clicking the button below:</p>
    <a href="{verify_url}" style="display: inline-block; padding: 10px 20px; background-color: #007BFF; color: white; text-decoration: none;">Verify</a>
    '''
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": POSTMARK_API_KEY
    }
    data = {
        "From": POSTMARK_FROM_EMAIL,
        "To": user_email,
        "Subject": "Verify your WatchGate account",
        "HtmlBody": html_body
    }
    response = requests.post("https://api.postmarkapp.com/email", json=data, headers=headers)
    if response.status_code == 200:
        app.logger.info(f"Verification email sent to {user_email}")
    else:
        app.logger.error(f"Failed to send email: {response.status_code} - {response.text}")
    return response.status_code, response.text

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = s.dumps(email, salt='password-reset')
            send_password_reset_email(email, token)
            flash("A password reset email has been sent. Please check your inbox.")
        else:
            flash("Email not found. Please check your email or register a new account.")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

def send_password_reset_email(user_email, token):
    reset_url = url_for('reset_password', token=token, _external=True)
    html_body = f'''
    <p>You requested a password reset for your WatchGate account. Click the button below to reset your password:</p>
    <a href="{reset_url}" style="display: inline-block; padding: 10px 20px; background-color: #007BFF; color: white; text-decoration: none;">Reset Password</a>
    '''
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": POSTMARK_API_KEY
    }
    data = {
        "From": POSTMARK_FROM_EMAIL,
        "To": user_email,
        "Subject": "Reset your WatchGate password",
        "HtmlBody": html_body
    }
    response = requests.post("https://api.postmarkapp.com/email", json=data, headers=headers)
    if response.status_code == 200:
        app.logger.info(f"Password reset email sent to {user_email}")
    else:
        app.logger.error(f"Failed to send password reset email: {response.status_code} - {response.text}")
    return response.status_code, response.text

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset', max_age=3600)
    except SignatureExpired:
        flash("The password reset link has expired. Please try again.")
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("Invalid password reset token.")
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user:
            # Hash the new password before storing it
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash("Your password has been reset successfully! Please sign in.")
            return redirect(url_for('login'))
        else:
            flash("User not found.")
            return redirect(url_for('register'))
    
    return render_template('reset_password.html', token=token)

@app.route('/verify_all')
def verify_all():
    users = User.query.all()
    for user in users:
        user.is_verified = True
    db.session.commit()
    flash("All users have been verified for testing purposes.")
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
