import re # Add at the very top of login.py
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room

# 1. Setup paths to find your templates and static folders
base_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(base_dir, '..')

app = Flask(__name__, 
            static_folder=os.path.join(root_dir, 'static'), 
            template_folder=os.path.join(root_dir, 'templates'))

# Required for session management
app.secret_key = 'alumni_secure_key'

# --- NAVIGATION ROUTES ---

@app.route('/')
def home():
    # Renders the professional landing page
    return render_template('homepage.html')

@app.route('/login_page')
def login_page():
    # Renders the login form
    return render_template('loginpage.html')

@app.route('/register')
def register_page():
    # Renders the registration form
    return render_template('registrationpage.html')

# --- LOGIC ROUTES ---

@app.route('/verify', methods=['POST'])
# --- LOGIC ROUTES ---

@app.route('/verify', methods=['POST'])
def verify_credentials():
    uname = request.form.get('username')
    upswd = request.form.get('password')

    conn = sqlite3.connect('alumni.db')
    cursor = conn.cursor()
    # Look for the user in the database
    cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (uname, upswd))
    user = cursor.fetchone()
    conn.close()

    if user:
        session['user'] = uname
        # Points to the dashboard function name
        return redirect(url_for('dashboard_view'))
    else:
        return "Invalid Credentials. <a href='/login_page'>Try again</a>"

@app.route('/dashboard') # Fixed: added slash
def dashboard_view():
    if 'user' in session:
        # Pass session['user'] to the 'user_name' placeholder in HTML
        return render_template('dashboard.html', user_name=session['user'])
    return redirect(url_for('login_page'))

@app.route('/logout')
def logout():
    session.pop('user', None) # Clear the session
    return redirect(url_for('home'))

@app.route('/process_register', methods=['POST'])
def process_register():
    roll_no = request.form.get('rollno').upper()
    fullname = request.form.get('fullname')
    uname = request.form.get('username')
    upswd = request.form.get('password')

    # 1. Verify Roll Number Pattern
    roll_pattern = r"^23UK1A05(0[1-9]|[1-6][0-9]|70)$"
    if not re.match(roll_pattern, roll_no):
        return "Invalid Roll Number. Only 23UK1A0501-70 allowed. <a href='/register'>Back</a>"

    # 2. Store in Database
    try:
        conn = sqlite3.connect('alumni.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (rollno, fullname, username, password) VALUES (?, ?, ?, ?)", 
                       (roll_no, fullname, uname, upswd))
        conn.commit()
        conn.close()
        return redirect(url_for('login_page'))
    except sqlite3.IntegrityError:
        return "Username or Roll Number already registered. <a href='/register'>Back</a>"

def init_db():
    conn = sqlite3.connect('alumni.db')
    cursor = conn.cursor()
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            rollno TEXT PRIMARY KEY,
            fullname TEXT,
            username TEXT UNIQUE,
            password TEXT
        )
    ''')
    # Fix for OperationalError: Create messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            receiver TEXT,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


@app.route('/directory') # Ensure the leading slash is here
def alumni_directory():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    
    # Fetch alumni data from your database
    conn = sqlite3.connect('alumni.db')
    cursor = conn.cursor()
    cursor.execute("SELECT fullname, rollno FROM users")
    all_alumni = cursor.fetchall()
    conn.close()
    
    # Render the directory template and pass the data
    return render_template('directory.html', alumni=all_alumni)

# Route to display the chat interface
@app.route('/chat/<receiver>')
def chat_room(receiver):
    if 'user' not in session:
        return redirect(url_for('login_page'))
    
    sender = session['user']
    
    # Fetch conversation history between sender and receiver
    conn = sqlite3.connect('alumni.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM messages 
        WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?) 
        ORDER BY timestamp ASC
    """, (sender, receiver, receiver, sender))
    history = cursor.fetchall()
    conn.close()
    
    return render_template('chat.html', receiver=receiver, history=history)

# Route to process and save sent messages
@app.route('/send_message/<receiver>', methods=['POST'])
def send_message(receiver):
    if 'user' not in session:
        return redirect(url_for('login_page'))
    
    sender = session['user']
    msg_text = request.form.get('message')
    
    if msg_text:
        conn = sqlite3.connect('alumni.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)", 
                       (sender, receiver, msg_text))
        conn.commit()
        conn.close()
        
    return redirect(url_for('chat_room', receiver=receiver))

@app.route('/career')
def career_center():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    return render_template('career.html')

socketio = SocketIO(app)
@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    print(f"{username} has entered the room: {room}")

@socketio.on('message')
def handle_message(data):
    sender = data['sender']
    receiver = data['receiver']
    msg_content = data['message']
    room = data['room']

    # Save to database
    conn = sqlite3.connect('alumni.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)", 
                   (sender, receiver, msg_content))
    conn.commit()
    conn.close()

    # Broadcast to everyone in the room
    emit('receive_message', data, room=room)

# Ensure this runs at the very bottom of your script
if __name__ == '__main__':
    init_db()
    app.run(debug=True)