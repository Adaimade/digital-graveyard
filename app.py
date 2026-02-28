from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai
import os
import datetime
import random
import logging
import re
from whitenoise import WhiteNoise

app = Flask(__name__)

# --- Configuration for Zeabur ---
# Use SECRET_KEY from ENV if available, else fallback to local (insecure) default for dev
app.secret_key = os.environ.get('SECRET_KEY', 'digital_rip_secret_key_local_dev')

# Setup Static Files for Gunicorn/Zeabur using Whitenoise
# Use absolute path to static folder to avoid relative path confusion
static_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
app.wsgi_app = WhiteNoise(app.wsgi_app, root=static_root, prefix='static/')

# Detect if we are on Zeabur (PostgreSQL) or Local (SQLite)
# Zeabur provides DATABASE_URL env var when PostgreSQL is linked
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1) # SQLAlchemy 1.4+ fix

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///graveyard.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)

db = SQLAlchemy(app)

# --- Gemini Config ---
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
        app.logger.info("Gemini API configured.")
    except Exception as e:
        app.logger.error(f"Gemini Config Error: {e}")
else:
    app.logger.warning("GEMINI_API_KEY not set. Using philosophical fallback mode.")

# --- Philosophical Fallback Database (50 Quotes) ---
PHILOSOPHICAL_QUOTES = [
    "\"What we call the beginning is often the end. And to make an end is to make a beginning. The end is where we start from.\" — T.S. Eliot, *Little Gidding*",
    "\"Everything that has a beginning has an ending. Make your peace with that and all will be well.\" — Jack Kornfield, *Buddha's Little Instruction Book*",
    "\"To live is to suffer, to survive is to find some meaning in the suffering.\" — Friedrich Nietzsche",
    "\"Life is a series of natural and spontaneous changes. Don't resist them; that only creates sorrow. Let reality be reality.\" — Lao Tzu",
    "\"The only way to deal with an unfree world is to become so absolutely free that your very existence is an act of rebellion.\" — Albert Camus",
    "\"We are what we repeatedly do. Excellence, then, is not an act, but a habit.\" — Aristotle",
    "\"He who has a why to live can bear almost any how.\" — Friedrich Nietzsche",
    "\"Man is condemned to be free; because once thrown into the world, he is responsible for everything he does.\" — Jean-Paul Sartre",
    "\"It is not death that a man should fear, but he should fear never beginning to live.\" — Marcus Aurelius, *Meditations*",
    "\"Out of your vulnerabilities will come your strength.\" — Sigmund Freud",
    "\"The unexamined life is not worth living.\" — Socrates",
    "\"I think, therefore I am.\" — René Descartes, *Discourse on the Method*",
    "\"God is dead. God remains dead. And we have killed him.\" — Friedrich Nietzsche, *The Gay Science*",
    "\"Hell is other people.\" — Jean-Paul Sartre, *No Exit*",
    "\"Happiness is not an ideal of reason, but of imagination.\" — Immanuel Kant",
    "\"No man's knowledge here can go beyond his experience.\" — John Locke",
    "\"Liberty consists in doing what one desires.\" — John Stuart Mill, *On Liberty*",
    "\"Even while they teach, men learn.\" — Seneca the Younger",
    "\"There is only one way to happiness and that is to cease worrying about things which are beyond the power of our will.\" — Epictetus",
    "\"The mind is furnished with ideas by experience alone.\" — John Locke",
    "\"Life must be understood backward. But it must be lived forward.\" — Søren Kierkegaard",
    "\"Science is organized knowledge. Wisdom is organized life.\" — Immanuel Kant",
    "\"He who thinks great thoughts, often makes great errors.\" — Martin Heidegger",
    "\"We live in the best of all possible worlds.\" — Gottfried Wilhelm Leibniz",
    "\"What doesn't kill us makes us stronger.\" — Friedrich Nietzsche",
    "\"Whereof one cannot speak, thereof one must be silent.\" — Ludwig Wittgenstein, *Tractatus Logico-Philosophicus*",
    "\"Entities should not be multiplied unnecessarily.\" — William of Ockham",
    "\"The life of man (in a state of nature) is solitary, poor, nasty, brutish, and short.\" — Thomas Hobbes, *Leviathan*",
    "\"Man is born free, and everywhere he is in chains.\" — Jean-Jacques Rousseau, *The Social Contract*",
    "\"I can control my passions and emotions if I can understand their nature.\" — Spinoza",
    "\"Philosophers have hitherto only interpreted the world in various ways; the point is to change it.\" — Karl Marx",
    "\"It is wrong always, everywhere, and for anyone, to believe anything upon insufficient evidence.\" — W.K. Clifford",
    "\"Virtue is nothing else than right reason.\" — Seneca the Younger",
    "\"Freedom is the right to tell people what they do not want to hear.\" — George Orwell",
    "\"In everything, there is a share of everything.\" — Anaxagoras",
    "\"A man who has not passed through the inferno of his passions has never overcome them.\" — Carl Jung",
    "\"We are too late for the gods and too early for Being.\" — Martin Heidegger",
    "\"The function of prayer is not to influence God, but rather to change the nature of the one who prays.\" — Søren Kierkegaard",
    "\"Man is the measure of all things.\" — Protagoras",
    "\"One cannot step twice into the same river.\" — Heraclitus",
    "\"The more I read, the more I acquire, the more certain I am that I know nothing.\" — Voltaire",
    "\"To be is to be perceived.\" — George Berkeley",
    "\"Happiness is the highest good.\" — Aristotle, *Nicomachean Ethics*",
    "\"If you would be a real seeker after truth, it is necessary that at least once in your life you doubt, as far as possible, all things.\" — René Descartes",
    "\"We are condemned to be free.\" — Jean-Paul Sartre",
    "\"The brave man is he who overcomes not only his enemies but his pleasures.\" — Democritus",
    "\"Good and evil are one.\" — Heraclitus",
    "\"The energy of the mind is the essence of life.\" — Aristotle",
    "\"All that we are is the result of what we have thought.\" — Buddha",
    "\"The soul becomes dyed with the color of its thoughts.\" — Marcus Aurelius"
]

# --- Input Sanitization ---
def sanitize_input(text):
    if not text:
        return ""
    # Allow letters, numbers, whitespace, and common punctuation (,.!?-&()[]{})
    # Also allow Chinese/CJK characters (\u4e00-\u9fa5)
    # This is safer than strict alphanumeric but still prevents HTML/JS injection
    text = re.sub(r'[<>]', '', text) # Strip < > to prevent HTML tags
    return text.strip()

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    custom_id = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    last_project_date = db.Column(db.Date, nullable=True)
    daily_project_count = db.Column(db.Integer, default=0)
    
    last_action_date = db.Column(db.Date, nullable=True)
    daily_action_count = db.Column(db.Integer, default=0)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    original_function = db.Column(db.Text, nullable=False)
    birth_date = db.Column(db.String(20), nullable=False)
    death_date = db.Column(db.String(20), default=datetime.datetime.now().strftime("%Y-%m-%d"))
    eulogy = db.Column(db.Text, nullable=True)
    prayers = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('projects', lazy=True))

# --- Routes ---
@app.route('/')
def index():
    try:
        projects = Project.query.order_by(Project.prayers.desc(), Project.id.desc()).all()
    except Exception:
        projects = []
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
        # Sanitize Inputs
        custom_id = sanitize_input(request.form['custom_id'])
        email = request.form.get('email', '').strip() # Email needs @ and ., so don't sanitize too aggressively here, but check format
        
        # Admin Registration Check
        if custom_id == "ADAIMADE":
             new_user = User(custom_id=custom_id, email=None, is_admin=True)
        else:
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
        custom_id = sanitize_input(request.form['custom_id'])
        email = request.form.get('email', '').strip()
        
        if custom_id == "ADAIMADE":
            user = User.query.filter_by(custom_id=custom_id).first()
        else:
            user = User.query.filter_by(email=email, custom_id=custom_id).first()
            
        if user:
            session['user_id'] = user.id
            flash('Welcome back, mourner.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have left the graveyard.', 'info')
    return redirect(url_for('index'))

@app.route('/add', methods=['GET', 'POST'])
def add_project():
    if 'user_id' not in session:
        flash('Login required.', 'warning')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    # Safety Check: If user ID in session doesn't exist in DB anymore (e.g. after DB reset)
    if not user:
        session.pop('user_id', None)
        flash('Session expired or invalid. Please login again.', 'error')
        return redirect(url_for('login'))

    today = datetime.date.today()
    
    if not user.is_admin:
        if user.last_project_date == today and user.daily_project_count >= 1:
             flash('Daily limit reached. Come back tomorrow.', 'error')
             return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Sanitize Inputs
        title = sanitize_input(request.form['title'])
        original_function = sanitize_input(request.form['function'])
        description = sanitize_input(request.form.get('description', ''))
        birth_date = request.form['birth_date']
        death_date = request.form.get('death_date', datetime.datetime.now().strftime("%Y-%m-%d"))

        # Generate Eulogy
        eulogy = "The spirits were silent..."
        
        if API_KEY:
            try:
                prompt = f"Write a short, poetic, 8-bit style eulogy for a software project named '{title}'. It was born on {birth_date} and died on {death_date}. Its original function was: '{original_function}'. The tone should be somber but respectful, like a pixel art game over screen. Keep it under 100 words. Use emojis like 🕯️, 🕊️, 💀."
                
                # Try different models if one fails (Priority: Gemini 2.0 Flash -> 1.5 Flash -> Pro)
                models_to_try = ['gemini-2.0-flash', 'gemini-2.0-flash-exp', 'gemini-1.5-flash', 'gemini-pro']
                response = None
                for m_name in models_to_try:
                    try:
                        model = genai.GenerativeModel(m_name)
                        response = model.generate_content(prompt)
                        if response and response.text:
                            eulogy = response.text
                            break
                    except Exception:
                        continue
                
                if not response:
                    raise Exception("AI failed")

            except Exception as e:
                app.logger.error(f"AI Generation Failed: {e}")
                eulogy = random.choice(PHILOSOPHICAL_QUOTES)
        else:
            # Fallback to Philosophical Quotes directly if no API Key
            eulogy = random.choice(PHILOSOPHICAL_QUOTES)

        new_project = Project(
            title=title,
            original_function=original_function,
            birth_date=birth_date,
            death_date=death_date,
            description=description,
            eulogy=eulogy,
            user_id=user.id
        )
        
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
    
    if not user.is_admin:
        if user.last_action_date != today:
            user.last_action_date = today
            user.daily_action_count = 0
            
        if user.daily_action_count >= 5:
            flash('Daily prayer limit reached.', 'error')
            return redirect(url_for('index'))
            
        user.daily_action_count += 1
        
    project = Project.query.get_or_404(project_id)
    project.prayers += 1
    db.session.commit()
    flash(f'You prayed for {project.title}.', 'success')
    return redirect(url_for('index'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
