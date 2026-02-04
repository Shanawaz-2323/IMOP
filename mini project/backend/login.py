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

@app.route('/')
def home():
    return render_template('homepage.html')

# --- REGISTRATION ---
@app.route('/register')
def register_page():
    return render_template('registrationpage.html')

@app.route('/process_register', methods=['POST'])
def process_register():
    rollno = request.form.get('rollno')
    username = request.form.get('username')
    fullname = request.form.get('fullname')
    password = request.form.get('password')

    if not rollno or not username:
        return "Missing required fields.", 400

    with env.begin(write=True) as txn:
        # 1. Check if Roll Number (the Key) already exists
        if txn.get(rollno.encode('utf-8')):
            return "This Roll Number is already registered! <a href='/alumni_login'>Please loginn</a>"

        # 2. Check if Username already exists (Scanning values)
        cursor = txn.cursor()
        for key, value in cursor:
            existing_data = json.loads(value.decode('utf-8'))
            if existing_data.get('username') == username:
                return "Username already taken! <a href='/register'>Choose another</a>"

        # 3. If no duplicates, Hash and Save
        hashed_pw = generate_password_hash(password)
        user_data = {
            'fullname': fullname,
            'username': username,
            'password': hashed_pw
        }
        
        txn.put(rollno.encode('utf-8'), json.dumps(user_data).encode('utf-8'))

    return redirect(url_for('alumni_login_page'))

# --- LOGIN ROUTES ---
@app.route('/alumni_login') # Synchronized name
def alumni_login_page():
    return render_template('aluminilogin.html')

@app.route('/college_login')
def college_login_page():
    return render_template('college_login.html')

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

# --- PORTAL VIEWS ---
@app.route('/dashboard')
def dashboard_view():
    if 'user' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html', user=session['user'])

@app.route('/directory')
def alumni_directory():
    if 'user' not in session:
        return redirect(url_for('home'))
    
    all_alumni = []
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor:
            roll = key.decode('utf-8')
            data = json.loads(value.decode('utf-8'))
            # Pass dictionary to fix 'receiver' UndefinedError
            all_alumni.append({'fullname': data['fullname'], 'rollno': roll})
            
    return render_template('directory.html', alumni=all_alumni)
@app.route('/logout')
def logout():
    # Remove the user's name from the session
    session.clear() 
    # Redirect back to the home page or login page
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)