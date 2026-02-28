from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai
import os
import datetime
import random
import logging

app = Flask(__name__)

# --- Configuration for Zeabur ---
# Use SECRET_KEY from ENV if available, else fallback to local (insecure) default for dev
app.secret_key = os.environ.get('SECRET_KEY', 'digital_rip_secret_key_local_dev')

# Detect if we are on Zeabur (PostgreSQL) or Local (SQLite)
# Zeabur provides DATABASE_URL env var when PostgreSQL is linked
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1) # SQLAlchemy 1.4+ fix

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///graveyard.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Logging for production
gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)

db = SQLAlchemy(app)

# --- Gemini Config ---
# Prefer ENV var, fallback to hardcoded (legacy/local) only if not set
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBkq7O1z_3wNq0oAs2SK-zpykRw9rRjTQg")
if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
        # Attempt to use a stable model or fallback list
        # We will handle model selection dynamically in the generate function
        app.logger.info("Gemini API configured.")
    except Exception as e:
        app.logger.error(f"Gemini Config Error: {e}")

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True) # Admin might not have email
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Track daily limits
    last_project_date = db.Column(db.Date, nullable=True)
    daily_project_count = db.Column(db.Integer, default=0)
    
    last_action_date = db.Column(db.Date, nullable=True) # For likes/flowers
    daily_action_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<User {self.custom_id}>'

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    original_function = db.Column(db.Text, nullable=False)
    birth_date = db.Column(db.String(20), nullable=False)
    death_date = db.Column(db.String(20), default=datetime.datetime.now().strftime("%Y-%m-%d"))
    eulogy = db.Column(db.Text, nullable=True)
    prayers = db.Column(db.Integer, default=0) # Likes/Flowers
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('projects', lazy=True))

    def __repr__(self):
        return f'<Project {self.title}>'

# --- Routes ---
@app.route('/')
def index():
    # Gracefully handle DB not initialized yet
    try:
        projects = Project.query.order_by(Project.prayers.desc(), Project.id.desc()).all()
    except Exception:
        projects = []
        # Auto-create tables if they don't exist (useful for first run on Zeabur)
        with app.app_context():
            db.create_all()
            projects = Project.query.order_by(Project.prayers.desc(), Project.id.desc()).all()

    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    return render_template('index.html', projects=projects, user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        custom_id = request.form['custom_id']
        email = request.form.get('email', '').strip()
        
        # Admin Registration Check
        if custom_id == "ADAIMADE":
             # Special logic for Admin (no email required)
             new_user = User(custom_id=custom_id, email=None, is_admin=True)
        else:
            # Normal User Restrictions
            if len(custom_id) > 12:
                flash('ID must be 12 characters or less.', 'error')
                return redirect(url_for('register'))
            if not email:
                flash('Email is required for mortals.', 'error')
                return redirect(url_for('register'))
            
            existing_user = User.query.filter((User.custom_id == custom_id) | (User.email == email)).first()
            if existing_user:
                flash('ID or Email already exists.', 'error')
                return redirect(url_for('register'))
            
            new_user = User(custom_id=custom_id, email=email, is_admin=False)
            
        try:
            db.session.add(new_user)
            db.session.commit()
            session['user_id'] = new_user.id
            flash('Welcome to the Digital Graveyard.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {str(e)}', 'error')
            return redirect(url_for('register'))
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        custom_id = request.form['custom_id']
        email = request.form.get('email', '').strip()
        
        # Admin Login
        if custom_id == "ADAIMADE":
            user = User.query.filter_by(custom_id=custom_id).first()
        else:
            user = User.query.filter_by(email=email, custom_id=custom_id).first()
            
        if user:
            session['user_id'] = user.id
            flash('Welcome back, mourner.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials. The spirits do not recognize you.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have left the graveyard.', 'info')
    return redirect(url_for('index'))

@app.route('/add', methods=['GET', 'POST'])
def add_project():
    if 'user_id' not in session:
        flash('You must identify yourself to lay a project to rest.', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    today = datetime.date.today()
    
    # Check Daily Limit for adding projects
    if not user.is_admin:
        if user.last_project_date == today and user.daily_project_count >= 1:
             flash('You have already buried a project today. Rest now.', 'error')
             return redirect(url_for('index'))
    
    if request.method == 'POST':
        title = request.form['title']
        original_function = request.form['function']
        birth_date = request.form['birth_date']
        death_date = request.form.get('death_date', datetime.datetime.now().strftime("%Y-%m-%d"))
        description = request.form.get('description', '')

        # Generate Eulogy
        eulogy = "The spirits were silent..."
        
        # Fallback static eulogies
        static_eulogies = [
            "Its logic has returned to the void. May its bytes rest in the cloud. ☁️",
            "A project born of hope, now resting in peace. 01001000 01001001. 🕯️",
            "Silence falls upon the code. Its function is done. 🕊️",
            "Game Over. Insert coin to pay respects. 💀",
            "It compiled successfully in our hearts. 💾"
        ]

        try:
            prompt = f"Write a short, poetic, 8-bit style eulogy for a software project named '{title}'. It was born on {birth_date} and died on {death_date}. Its original function was: '{original_function}'. The tone should be somber but respectful, like a pixel art game over screen. Keep it under 100 words. Use emojis like 🕯️, 🕊️, 💀."
            
            # Try different models if one fails
            models_to_try = ['gemini-pro', 'gemini-1.5-flash']
            response = None
            
            for m_name in models_to_try:
                try:
                    model = genai.GenerativeModel(m_name)
                    response = model.generate_content(prompt)
                    if response and response.text:
                        eulogy = response.text
                        break
                except Exception as inner_e:
                    app.logger.warning(f"Model {m_name} failed: {inner_e}")
                    continue
            
            if not response:
                raise Exception("All models failed")

        except Exception as e:
            app.logger.error(f"AI Generation Failed: {e}")
            eulogy = random.choice(static_eulogies)

        new_project = Project(
            title=title,
            original_function=original_function,
            birth_date=birth_date,
            death_date=death_date,
            description=description,
            eulogy=eulogy,
            user_id=user.id
        )
        
        # Update User Stats
        if user.last_project_date != today:
            user.last_project_date = today
            user.daily_project_count = 0
        user.daily_project_count += 1
        
        db.session.add(new_project)
        db.session.commit()
        flash('Project laid to rest.', 'success')
        return redirect(url_for('index'))

    return render_template('add_project.html')

@app.route('/pray/<int:project_id>', methods=['POST'])
def pray(project_id):
    if 'user_id' not in session:
         flash('Login to pray.', 'warning')
         return redirect(url_for('login'))
         
    user = User.query.get(session['user_id'])
    today = datetime.date.today()
    
    # Check Daily Limit for prayers (likes/flowers)
    if not user.is_admin:
        if user.last_action_date != today:
            user.last_action_date = today
            user.daily_action_count = 0
            
        if user.daily_action_count >= 5:
            flash('You have run out of prayers for today.', 'error')
            return redirect(url_for('index'))
            
        user.daily_action_count += 1
        
    project = Project.query.get_or_404(project_id)
    project.prayers += 1
    db.session.commit()
    flash(f'You prayed for {project.title}.', 'success')
    return redirect(url_for('index'))

# Initialize DB (Auto-migration for simple cases)
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    # Local dev mode
    app.run(debug=True, port=5000)
