import os
import json
import lmdb
import time
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session , flash
from werkzeug.security import generate_password_hash, check_password_hash


# Dynamic path setup to ensure your CSS loads
base_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(base_dir, '..')

app = Flask(__name__, 
            static_folder=os.path.join(root_dir, 'static'),
            template_folder=os.path.join(root_dir, 'templates'))

app.secret_key = 'alumni_secure_key' # For secure sessions

# Initialize LMDB
db_path = os.path.join(base_dir, 'alumni_lmdb')
env = lmdb.open(db_path, map_size=10485760)
#jobs database
jobs_db_path = os.path.join(base_dir, 'jobs_lmdb')
jobs_env = lmdb.open(jobs_db_path, map_size=10485760)

@app.route('/')
def index():
    return render_template('homepage.html')

# --- REGISTRATION ---
@app.route('/register')
def register_page():
    return render_template('alumns/alumni_registration_page.html')

# --- LOGIN ROUTES ---
@app.route('/alumni_login') # Synchronized name
def alumni_login_page():
    return render_template('alumns/alumnilogin.html')


@app.route('/faculty_login', methods=['GET'])
def faculty_login_page():
    return render_template('faculty/faculty_login.html')

# 2. This displays the registration page
@app.route('/faculty_register', methods=['GET'])
def faculty_register_page():
    return render_template('faculty/faculty_register.html')

# Ensure this route allows POST if you are submitting the form to it
@app.route('/faculty/post-job', methods=['GET', 'POST'])
def post_job_page():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))
    
    # If the user is submitting the form
    if request.method == 'POST':
        # You can call your processing logic here or redirect to it
        return redirect(url_for('process_job_post'), code=307) # 307 preserves the POST data
        
    return render_template('faculty/job_posting.html')


# --- PORTAL VIEWS ---
@app.route('/dashboard')
def dashboard_view():
    if 'user' not in session:
        return redirect(url_for('index')) # Fixed from 'home' to 'index'
    
    user_data = {}
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            data = json.loads(value.decode('utf-8'))
            if data.get('fullname') == session['user']:
                user_data = data
                break

    # List of fields we want them to fill out
    important_fields = ['email', 'employment_status', 'bio', 'linkedin']
    filled_count = sum(1 for field in important_fields if user_data.get(field))
    
    # Calculate percentage (Base 20% + 20% for each filled field)
    progress_percent = 20 + (filled_count * 20)
    if progress_percent > 100: progress_percent = 100

    return render_template('alumns/dashboard.html', 
                           user=session['user'], 
                           progress=progress_percent)

@app.route('/profile')
def profile_page():
    if 'user' not in session:
        return redirect(url_for('index'))
    
    user_data = {}
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            data = json.loads(value.decode('utf-8'))
            if data.get('fullname') == session['user']:
                user_data = data
                user_data['rollno'] = key.decode('utf-8')
                break
                
    return render_template('alumns/profile.html', user=user_data)



@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user' not in session: return redirect(url_for('index'))
    
    rollno = request.form.get('rollno')
    new_data = {
        'fullname': request.form.get('fullname'),
        'email': request.form.get('email'),
        'employment_status': request.form.get('employment_status'),
        'bio': request.form.get('bio'),
        'linkedin': request.form.get('linkedin'),
        'role': 'alumni',
        'status': 'approved'
    }

    with env.begin(write=True) as txn:
        old_data_raw = txn.get(rollno.encode('utf-8'))
        if old_data_raw:
            old_data = json.loads(old_data_raw.decode('utf-8'))
            new_data['password'] = old_data['password'] # Keep password!
            new_data['username'] = old_data['username']
            txn.put(rollno.encode('utf-8'), json.dumps(new_data).encode('utf-8'))
            session['user'] = new_data['fullname'] # Update session name if changed
    
    flash("Profile updated successfully!", "success")
    return redirect(url_for('dashboard_view'))


@app.route('/view_jobs')
def view_jobs():
    jobs_list = []
    with jobs_env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            # Only pull keys that start with 'job_'
            if key.decode('utf-8').startswith('job_'):
                jobs_list.append(json.loads(value.decode('utf-8')))
    
    # Sort by newest first
    jobs_list.reverse()
    return render_template('alumns/alumni_jobs.html', jobs=jobs_list)


@app.route('/process_register', methods=['POST'])
def process_register():
    # 1. Capture Form Data
    rollno = request.form.get('rollno', '').strip()
    username = request.form.get('username', '').strip()
    fullname = request.form.get('fullname', '').strip()
    password = request.form.get('password', '').strip()
    email = request.form.get('email', '').strip()
    employment_status = request.form.get('employment_status', 'Not Specified')

    # 2. Validation: Ensure required fields are not empty
    if not rollno or not username or not password:
        flash("Registration failed: Roll Number, Username, and Password are required.", "danger")
        return redirect(url_for('register_page')) # Change to your actual register route name

    with env.begin(write=True) as txn:
        # 3. Check if Roll Number (Primary Key) already exists
        existing_raw = txn.get(rollno.encode('utf-8'))
        
        if existing_raw:
            existing_user = json.loads(existing_raw.decode('utf-8'))
            # If they are already in the system, tell them why they can't register again
            if existing_user.get('status') == 'pending':
                flash(f"Roll Number {rollno} is already awaiting faculty approval.", "warning")
            else:
                flash(f"Roll Number {rollno} is already registered. Please log in.", "info")
            return redirect(url_for('index')) # Redirect to home to show the flash popup

        # 4. Check if Username is taken (requires scanning the database)
        cursor = txn.cursor()
        for key, value in cursor:
            user_check = json.loads(value.decode('utf-8'))
            if user_check.get('username') == username:
                flash("This username is already taken! Please choose another.", "danger")
                return redirect(url_for('register_page'))

        # 5. Security: Hash the password
        hashed_pw = generate_password_hash(password)

        # 6. Prepare Data for Storage
        user_data = {
            'fullname': fullname,
            'username': username,
            'email': email,
            'password': hashed_pw,
            'employment_status': employment_status,
            'status': 'pending',  # CRITICAL: User cannot log in until faculty changes this to 'approved'
            'role': 'alumni'      # Distinguishes from faculty accounts
        }

        # 7. Write to LMDB
        txn.put(rollno.encode('utf-8'), json.dumps(user_data).encode('utf-8'))

    # 8. Success: Flash message and redirect
    flash("Registration Successful! Your account is now pending faculty approval.", "success")
    return redirect(url_for('index')) # Redirect to home/login where base.html will show the popup


@app.route('/verify', methods=['POST'])
def verify():
    username_entered = request.form.get('username')
    password_entered = request.form.get('password')

    if not username_entered or not password_entered:
        flash("Please fill in all fields.", "warning")
        return redirect(url_for('alumni_login_page'))

    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            user_data = json.loads(value.decode('utf-8'))
            
            if user_data.get('username') == username_entered:
                # 1. Check Password
                if check_password_hash(user_data['password'], password_entered):
                    
                    # 2. THE GATEKEEPER: Check if approved
                    if user_data.get('status') == 'pending':
                        flash("Account Pending: A faculty member must approve your registration before you can log in.", "info")
                        return redirect(url_for('alumni_login_page'))
                    
                    # 3. Successful Login
                    session['user'] = user_data['fullname']
                    session['role'] = 'alumni'
                    flash(f"Welcome back, {user_data['fullname']}!", "success")
                    return redirect(url_for('dashboard_view'))
    
    flash("Invalid Credentials. Please check your username and password.", "danger")
    return redirect(url_for('alumni_login_page'))

# Fixed route to allow POST data from your form
@app.route('/process_faculty_register', methods=['POST'])
def process_faculty_register():
    email = request.form.get('email')
    
    # Domain Lock: Only @vec.edu.in allowed
    if not email or not email.endswith('@vec.edu.in'):
        return "Registration Error: Faculty must use @vec.edu.in email.", 403

    fullname = request.form.get('fullname')
    password = request.form.get('password')
    role = request.form.get('role', 'faculty') 

    
    hashed_pw = generate_password_hash(password)
    
    user_data = {
        'fullname': fullname,
        'email': email,
        'password': hashed_pw,
        'role': role
    }

    with env.begin(write=True) as txn:
        # Prevent AttributeErrors by ensuring email isn't None
        if txn.get(email.encode('utf-8')):
            return "Error: This faculty email is already registered.", 400
        
        txn.put(email.encode('utf-8'), json.dumps(user_data).encode('utf-8'))

    return redirect(url_for('faculty_login_page'))


@app.route('/faculty_verify', methods=['POST'])
def faculty_verify():
    email = request.form.get('email')
    password = request.form.get('password')

    with env.begin() as txn:
        user_bytes = txn.get(email.encode('utf-8'))
        if user_bytes:
            user_data = json.loads(user_bytes.decode('utf-8'))
            if check_password_hash(user_data['password'], password):
                session['user'] = user_data['fullname']
                session['role'] = 'faculty'
                return redirect(url_for('faculty_dashboard'))
    
    flash("Invalid Credentials", "danger")
    return redirect(url_for('faculty_login_page'))


@app.route('/directory')
def alumni_directory():
    if 'user' not in session: return redirect(url_for('index'))
    
    alumni_list = []
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            data = json.loads(value.decode('utf-8'))
            # Filter out faculty to keep directory exclusive to alumni
            if data.get('role') != 'faculty':
                alumni_list.append({
                    'rollno': key.decode('utf-8'),
                    'fullname': data.get('fullname'),
                    'status': data.get('employment_status', 'Not Specified')
                })
    return render_template('alumns/directory.html', alumni=alumni_list)

@app.route('/faculty_dashboard')
def faculty_dashboard():
    # Ensure only faculty can access this page
    if 'user' not in session or session.get('role') != 'faculty':
        return redirect(url_for('index'))
    
    alumni_list = []
    alumni_count = 0
    job_count = 0

    # 1. Count Alumni and build the list
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            data = json.loads(value.decode('utf-8'))
            # Filter for alumni only
            if data.get('role') != 'faculty':
                alumni_count += 1
                alumni_list.append({
                    'rollno': key.decode('utf-8'),
                    'username': data.get('username'),
                    'fullname': data.get('fullname'),
                    'status': data.get('employment_status', 'Not Specified')
                })

    # 2. Count Total Job Postings
    with jobs_env.begin() as txn:
        # Use stat() to get the number of entries in the database efficiently
        job_count = txn.stat()['entries']
                
    # Pass counts to the template
    return render_template('faculty/faculty_dashboard.html', 
                           alumni=alumni_list, 
                           total_alumni=alumni_count, 
                           total_jobs=job_count)

@app.route('/process_job_post', methods=['POST'])
def process_job_post():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))

    # 1. Generate a Unique ID using milliseconds for precision
    job_id = str(int(time.time() * 1000)) 

    # 2. Extract data safely using .get() to prevent 'KeyError'
    # Note: These keys now match the 'name' attributes in your HTML form
    title = request.form.get('title')
    company = request.form.get('company')
    
    # Simple validation: if title or company is missing, don't crash, just redirect
    if not title or not company:
        flash("Error: Job Title and Company are required fields.", "danger")
        return redirect(url_for('post_job_page'))

    job_data = {
        'id': job_id,
        'title': title,
        'company': company,
        'location': request.form.get('location', 'Not Specified'),
        'job_type': request.form.get('job_type', 'Full-time'),
        'description': request.form.get('description', ''),
        'requirements': request.form.get('requirements', ''),
        'salary_range': request.form.get('salary_range', 'Negotiable'),
        'contact_email': request.form.get('contact_email', ''),
        'poster_name': session.get('user', 'Faculty Administrator'),
        'posted_by': session.get('ansa_user_id'),
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'deadline': request.form.get('deadline', 'No Deadline'),
        'is_active': True
    }

    # 3. Store in LMDB with a clear prefix
    try:
        with jobs_env.begin(write=True) as txn:
            job_key = f"job_{job_id}".encode('utf-8')
            txn.put(job_key, json.dumps(job_data).encode('utf-8'))
        
        flash("Job Opportunity Broadcasted Successfully!", "success")
    except Exception as e:
        flash(f"Database Error: {str(e)}", "danger")

    return redirect(url_for('faculty_dashboard'))

@app.route('/view_applications')
def view_pending_requests():
    if session.get('role') != 'faculty':
        return redirect(url_for('index'))

    apps_list = []
    # Identify applications in your jobs_env LMDB
    with jobs_env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            k_str = key.decode('utf-8')
            # Look for keys starting with 'app_' that we created earlier
            if k_str.startswith('app_'):
                apps_list.append(json.loads(value.decode('utf-8')))

    return render_template('faculty/applications.html', applications=apps_list)

@app.route('/apply_job/<job_id>', methods=['GET', 'POST']) # Added GET as a safety net
def apply_job(job_id):
    if 'user' not in session:
        return redirect(url_for('index'))

    # If someone accidentally visits the link via GET, redirect them back to the list
    if request.method == 'GET':
        return redirect(url_for('view_jobs'))

    alumni_name = session.get('user')
    
    # Use the correct jobs_env to avoid the "Job not found" error
    with jobs_env.begin(write=True) as txn:
        job_key = f"job_{job_id}".encode('utf-8')
        job_data_raw = txn.get(job_key)
        
        if not job_data_raw:
            flash("Job not found.", "danger")
            return redirect(url_for('view_jobs'))

        job_info = json.loads(job_data_raw.decode('utf-8'))
        publisher = job_info.get('poster_name', 'Faculty Administrator')

        # 2. Store the Application record (using a unique key)
        app_key = f"app_{job_id}_{alumni_name}".encode('utf-8')
        app_data = {
            'alumni_name': alumni_name,
            'job_id': job_id,
            'job_title': job_info.get('title', 'Unknown Role'),
            'applied_on': datetime.now().strftime("%Y-%m-%d %H:%M"),
            'status': 'Pending'
        }
        txn.put(app_key, json.dumps(app_data).encode('utf-8'))

        # 3. Create a Notification for the Faculty member
        notif_timestamp = datetime.now().timestamp()
        notif_key = f"notif_{publisher}_{notif_timestamp}".encode('utf-8')
        notif_data = {
            'message': f"Alumni {alumni_name} applied for: {job_info.get('title')}",
            'type': 'application',
            'job_id': job_id,
            'from_user': alumni_name,
            'is_read': False,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        txn.put(notif_key, json.dumps(notif_data).encode('utf-8'))

    flash(f"Success! Your application for '{job_info.get('title')}' has been sent.", "success")
    return redirect(url_for('view_jobs'))
    
@app.route('/faculty/manage_applications')
def manage_applications():
    # Fix: ensure we use the correct session key for faculty ID
    current_faculty = session.get('user') 
    publisher_apps = []

    with jobs_env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            k_str = key.decode('utf-8')
            if k_str.startswith('app_'):
                app = json.loads(value.decode('utf-8'))
                
                # Fetch job to verify the faculty owns it
                job_data = txn.get(f"job_{app['job_id']}".encode('utf-8'))
                if job_data:
                    job = json.loads(job_data.decode('utf-8'))
                    
                    # Ensure only the publisher sees this AND only if Pending
                    if job.get('poster_name') == current_faculty:
                        if app.get('status') == 'Pending':
                            app['job_title'] = job['title']
                            publisher_apps.append(app)
    
    return render_template('faculty/applications.html', applications=publisher_apps)

@app.route('/faculty/pending_registrations')
def pending_registrations():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))
    
    pending_users = []
    with env.begin() as txn: # Assuming 'env' is your user database
        cursor = txn.cursor()
        for key, value in cursor:
            user_data = json.loads(value.decode('utf-8'))
            if user_data.get('status') == 'pending':
                pending_users.append(user_data)
                
    return render_template('faculty/pending_requests.html', users=pending_users)

@app.route('/faculty/directory')
def faculty_alumni_directory():
    """Fetches all alumni for the faculty directory view."""
    if 'user' not in session or session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))
    
    alumni_list = []
    # Open the alumni database
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            data = json.loads(value.decode('utf-8'))
            # Only include alumni, exclude other faculty accounts
            if data.get('role') != 'faculty':
                alumni_list.append({
                    'rollno': key.decode('utf-8'),
                    'fullname': data.get('fullname'),
                    'username': data.get('username'),
                    'email': data.get('email'),
                    'status': data.get('employment_status', 'Not Specified')
                })
                
    return render_template('faculty/faculty_directory.html', alumni_list=alumni_list)

@app.route('/faculty/profile/<rollno>')
def view_alumni_profile(rollno):
    if 'user' not in session or session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))

    alumni_data = None
    with env.begin() as txn:
        # Search for the specific roll number key
        value = txn.get(rollno.encode('utf-8'))
        if value:
            alumni_data = json.loads(value.decode('utf-8'))
            alumni_data['rollno'] = rollno  # Ensure rollno is available for the UI

    if not alumni_data:
        return "Alumni not found", 404

    return render_template('faculty/view_profile.html', alumni=alumni_data)

@app.route('/view_profile/<username>')
def view_profile(username):
    if 'user' not in session:
        return redirect(url_for('index'))

    user_info = None
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            data = json.loads(value.decode('utf-8'))
            # Search specifically for the unique username field
            if data.get('username') == username:
                user_info = data
                user_info['rollno'] = key.decode('utf-8')
                break
        
    if not user_info:
        flash(f"Profile for {username} not found.", "danger")
        return redirect(url_for('manage_applications'))

    # Pass 'user_info' as 'user' to match your existing template
    return render_template('view_profile.html', user=user_info)

@app.route('/faculty/my_posted_jobs')
def my_posted_jobs():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))
    
    current_faculty = session.get('user') # Matches your poster_name logic
    my_jobs = []

    with jobs_env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            k_str = key.decode('utf-8')
            # Look only for job entries, not applications
            if k_str.startswith('job_'):
                job_data = json.loads(value.decode('utf-8'))
                # Filter: Only show jobs posted by this faculty member
                if job_data.get('poster_name') == current_faculty:
                    my_jobs.append(job_data)

    # Sort newest first
    my_jobs.reverse()
    return render_template('faculty/my_jobs.html', jobs=my_jobs)



@app.route('/update_status/<job_id>/<alumni_name>/<status>', methods=['POST'])
def update_app_status(job_id, alumni_name, status):
    app_key = f"app_{job_id}_{alumni_name}".encode('utf-8')
    
    with jobs_env.begin(write=True) as txn:
        app_data_raw = txn.get(app_key)
        if app_data_raw:
            app_data = json.loads(app_data_raw.decode('utf-8'))
            app_data['status'] = status
            txn.put(app_key, json.dumps(app_data).encode('utf-8'))
            flash(f"Application for {alumni_name} marked as {status}.", "success")
        else:
            flash("Application record not found.", "danger")
            
    return redirect(url_for('manage_applications'))

@app.route('/logout')
def logout():
    session.clear() 
    # This also helps clear the 'flashes' internally
    flash("You have been logged out safely.", "info") 
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)