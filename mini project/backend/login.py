import os
import json
import lmdb
from flask import Flask, render_template, request, redirect, url_for, session
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
def home():
    return render_template('homepage.html')

# --- REGISTRATION ---
@app.route('/register')
def register_page():
    return render_template('alumni_registration_page.html')

# --- LOGIN ROUTES ---
@app.route('/alumni_login') # Synchronized name
def alumni_login_page():
    return render_template('alumnilogin.html')

@app.route('/college_login')
def college_login_page():
    return render_template('college_login.html')


@app.route('/faculty_login')
def faculty_login_page():
    return render_template('faculty_login.html')

@app.route('/faculty_register')
def faculty_register_page():
    return render_template('faculty_register.html')



# --- PORTAL VIEWS ---
@app.route('/dashboard')
def dashboard_view():
    if 'user' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html', user=session['user'])

@app.route('/faculty/post-job')
def post_job_page():
    """Renders the job posting form. Fixed BuildError by matching template name."""
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))
    return render_template('job_posting.html')

@app.route('/career-options')
def view_jobs():
    """Fetches jobs from jobs_env and displays them to alumni."""
    if 'user' not in session:
        return redirect(url_for('alumni_login_page'))
    
    jobs_list = []
    # Open the jobs database you initialized
    with jobs_env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            # Decode the stored JSON data
            job_data = json.loads(value.decode('utf-8'))
            jobs_list.append(job_data)
            
    # Reverse the list so the newest jobs appear first
    return render_template('alumni_jobs.html', jobs=jobs_list[::-1])


@app.route('/process_register', methods=['POST'])
def process_register():
    rollno = request.form.get('rollno')
    username = request.form.get('username')
    fullname = request.form.get('fullname')
    password = request.form.get('password')
    employment_status = request.form.get('employment_status')

    if not employment_status:
        employment_status = "Not Specified"

    if not rollno or not username:
        return "Missing required fields.", 400

    with env.begin(write=True) as txn:
        #Checking if the Roll Number exists
        if txn.get(rollno.encode('utf-8')):
            return "This Roll Number is already registered! <a href='/alumni_login'>Please loginn</a>"

        # Checking if Username already exists
        cursor = txn.cursor()
        for key, value in cursor:
            existing_data = json.loads(value.decode('utf-8'))
            if existing_data.get('username') == username:
                return "Username already taken! <a href='/register'>Choose another</a>"

        # If no duplicates, Hash and Save
        hashed_pw = generate_password_hash(password)
        user_data = {
            'fullname': request.form.get('fullname'),
            'username': request.form.get('username'),
            'email': request.form.get('email'),
            'password': hashed_pw,
            'employment_status': employment_status  # New Field added to DB
        }
        txn.put(rollno.encode('utf-8'), json.dumps(user_data).encode('utf-8'))

    return redirect(url_for('alumni_login_page'))



@app.route('/verify', methods=['POST'])
def verify():
    # Make sure these match your login form 'name' attributes exactly
    username_entered = request.form.get('username')
    password_entered = request.form.get('password')

    if not username_entered or not password_entered:
        return "Please fill in all fields."

    with env.begin() as txn:
        cursor = txn.cursor()
        # Iterate through LMDB because username is inside the value, not the key
        for key, value in cursor:
            user_data = json.loads(value.decode('utf-8'))
            
            # Check if this record matches the username
            if user_data.get('username') == username_entered:
                # Use check_password_hash to compare with the stored hash key
                if check_password_hash(user_data['password'], password_entered):
                    session['user'] = user_data['fullname']
                    return redirect(url_for('dashboard_view'))
    
    # If the loop finishes without a return, the credentials didn't match
    return "Invalid Credentials. <a href='/alumni_login'>Try again</a>"

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

    # 1. Domain Enforcement
    if not email.endswith('@vec.edu.in'):
        return "Access Denied: Faculty must use @vec.edu.in domain."

    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            user_data = json.loads(value.decode('utf-8'))
            # 2. Credential & Role Check
            if user_data.get('email') == email:
                if check_password_hash(user_data['password'], password):
                    # We can store a 'role' in the user_data during registration
                    if user_data.get('role') == 'faculty':
                        session['user'] = user_data['fullname']
                        session['role'] = 'faculty'
                        return redirect(url_for('faculty_dashboard'))
                    else:
                        return "Unauthorized: This is the Faculty portal."
                        
    return "Invalid Faculty Credentials."

@app.route('/directory')
def alumni_directory():
    if 'user' not in session: return redirect(url_for('home'))
    
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
    return render_template('directory.html', alumni=alumni_list)

@app.route('/faculty_dashboard')
def faculty_dashboard():
    # Ensure only faculty can access this page
    if 'user' not in session or session.get('role') != 'faculty':
        return redirect(url_for('home'))
    
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
    return render_template('faculty_dashboard.html', 
                           alumni=alumni_list, 
                           total_alumni=alumni_count, 
                           total_jobs=job_count)

@app.route('/process_job_post', methods=['POST'])
def process_job_post():
    """Handles the actual saving of job data to LMDB."""
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login_page'))

    # Extract data from form fields
    title = request.form.get('job_title')
    description = request.form.get('job_description')
    
    # Identify the faculty poster from the session
    poster_name = session.get('user', 'Faculty Administrator')

    job_data = {
        'title': title,
        'description': description,
        'poster_name': poster_name
    }

    # Store in the jobs database using Title as the key
    with jobs_env.begin(write=True) as txn:
        txn.put(title.encode('utf-8'), json.dumps(job_data).encode('utf-8'))

    return redirect(url_for('faculty_dashboard'))

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
                
    return render_template('faculty_directory.html', alumni=alumni_list)

@app.route('/logout')
def logout():
    # Remove the user's name from the session
    session.clear() 
    # Redirect back to the home page or login page
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)