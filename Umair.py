from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, flash
import pyodbc
from azure.storage.blob import BlobServiceClient
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import json
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from textblob import TextBlob
import cv2
import tempfile

app = Flask(__name__)
app.secret_key = 'b9e4f7a1c02d8e93f67a4c5d2e8ab91ff4763a6d85c24550'

AZURE_SQL_SERVER = "umairserver12.database.windows.net"
AZURE_SQL_DATABASE = "umair3211"
AZURE_SQL_USERNAME = "umair"
AZURE_SQL_PASSWORD = "Eng@12345"

AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=umair321;AccountKey=7rtM5kPw42+7VmDCo9URWLAFJjvk0NlX/pHZwJ18CTJob7iusW7PqoM5VaBQIh4bRtctnvZUQG8K+ASt0nEPyA==;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER = "media"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, user_type):
        self.id = id
        self.username = username
        self.user_type = user_type

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, user_type FROM users WHERE id = ?", user_id)
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[2])
    return None

def get_db_connection():
    connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={AZURE_SQL_SERVER};DATABASE={AZURE_SQL_DATABASE};UID={AZURE_SQL_USERNAME};PWD={AZURE_SQL_PASSWORD}'
    return pyodbc.connect(connection_string)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(50) UNIQUE NOT NULL,
            email NVARCHAR(100) UNIQUE NOT NULL,
            password_hash NVARCHAR(255) NOT NULL,
            user_type NVARCHAR(10) NOT NULL,
            created_at DATETIME DEFAULT GETDATE()
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='videos' AND xtype='U')
        CREATE TABLE videos (
            id INT IDENTITY(1,1) PRIMARY KEY,
            title NVARCHAR(200) NOT NULL,
            publisher NVARCHAR(100) NOT NULL,
            producer NVARCHAR(100) NOT NULL,
            genre NVARCHAR(50) NOT NULL,
            age_rating NVARCHAR(10) NOT NULL,
            video_url NVARCHAR(500) NOT NULL,
            thumbnail_url NVARCHAR(500),
            creator_id INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (creator_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ratings' AND xtype='U')
        CREATE TABLE ratings (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            rating INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='comments' AND xtype='U')
        CREATE TABLE comments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            comment NVARCHAR(500) NOT NULL,
            sentiment NVARCHAR(10),
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()

blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

@app.route('/')
def home():
    return render_template_string(HOME_TEMPLATE)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']

        password_hash = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, user_type) VALUES (?, ?, ?, ?)",
                username, email, password_hash, user_type
            )
            conn.commit()
            conn.close()
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username or email already exists!', 'error')

    return render_template_string(REGISTER_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, user_type FROM users WHERE username = ?", username)
        user_data = cursor.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[2], password):
            user = User(user_data[0], user_data[1], user_data[3])
            login_user(user)
            if user.user_type == 'creator':
                return redirect(url_for('creator_dashboard'))
            else:
                return redirect(url_for('consumer_dashboard'))
        else:
            flash('Invalid credentials!', 'error')

    return render_template_string(LOGIN_TEMPLATE)

@app.route('/creator-dashboard')
@login_required
def creator_dashboard():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))
    return render_template_string(CREATOR_DASHBOARD_TEMPLATE)

@app.route('/consumer-dashboard')
@login_required
def consumer_dashboard():
    if current_user.user_type != 'consumer':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                   LEFT JOIN ratings r ON v.id = r.video_id
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.created_at, v.thumbnail_url
                   ORDER BY v.created_at DESC
                   ''')
    videos = cursor.fetchall()

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    # Fetch comments
    comments_dict = {}
    cursor.execute('''
        SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
        FROM comments c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    all_comments = cursor.fetchall()
    for comment in all_comments:
        vid = comment[0]
        if vid not in comments_dict:
            comments_dict[vid] = []
        comments_dict[vid].append({
            'username': comment[1],
            'comment': comment[2],
            'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
            'sentiment': comment[4]
        })

    conn.close()

    return render_template_string(CONSUMER_DASHBOARD_TEMPLATE, videos=videos, user_ratings=user_ratings, comments=comments_dict)

@app.route('/upload-video', methods=['POST'])
@login_required
def upload_video():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))

    title = request.form['title']
    publisher = request.form['publisher']
    producer = request.form['producer']
    genre = request.form['genre']
    age_rating = request.form['age_rating']
    video_file = request.files['video']

    if video_file:
        filename = secure_filename(video_file.filename)
        blob_name = f"{uuid.uuid4()}_{filename}"

        try:
            # Save video to temp file
            with tempfile.NamedTemporaryFile(delete=False) as temp_video:
                video_file.save(temp_video.name)
                temp_video_path = temp_video.name

            # Upload video
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_STORAGE_CONTAINER,
                blob=blob_name
            )
            with open(temp_video_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)
            video_url = blob_client.url

            # Generate thumbnail
            thumbnail_url = None
            cap = cv2.VideoCapture(temp_video_path)
            success, frame = cap.read()
            if success:
                thumbnail_blob_name = f"{uuid.uuid4()}_thumb.jpg"
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_thumb:
                    cv2.imwrite(temp_thumb.name, frame)
                    temp_thumb_path = temp_thumb.name

                blob_client_thumb = blob_service_client.get_blob_client(
                    container=AZURE_STORAGE_CONTAINER,
                    blob=thumbnail_blob_name
                )
                with open(temp_thumb_path, "rb") as f:
                    blob_client_thumb.upload_blob(f, overwrite=True)
                thumbnail_url = blob_client_thumb.url

                os.unlink(temp_thumb_path)

            cap.release()
            os.unlink(temp_video_path)

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (title, publisher, producer, genre, age_rating, video_url, thumbnail_url, creator_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                title, publisher, producer, genre, age_rating, video_url, thumbnail_url, current_user.id
            )
            conn.commit()
            conn.close()

            flash('Video uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'error')

    return redirect(url_for('creator_dashboard'))

@app.route('/rate-video', methods=['POST'])
@login_required
def rate_video():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    rating = data['rating']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM ratings WHERE video_id = ? AND user_id = ?", video_id, current_user.id)
    existing = cursor.fetchone()

    if existing:
        cursor.execute("UPDATE ratings SET rating = ? WHERE video_id = ? AND user_id = ?",
                       rating, video_id, current_user.id)
    else:
        cursor.execute("INSERT INTO ratings (video_id, user_id, rating) VALUES (?, ?, ?)",
                       video_id, current_user.id, rating)

    conn.commit()

    # Fetch new average
    cursor.execute("SELECT AVG(CAST(rating AS FLOAT)) FROM ratings WHERE video_id = ?", video_id)
    new_avg = cursor.fetchone()[0]

    conn.close()

    return jsonify({'success': True, 'avg_rating': new_avg})

@app.route('/add-comment', methods=['POST'])
@login_required
def add_comment():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    comment_text = data['comment']

    # Perform sentiment analysis
    blob = TextBlob(comment_text)
    polarity = blob.sentiment.polarity
    if polarity > 0:
        sentiment = 'positive'
    elif polarity < 0:
        sentiment = 'negative'
    else:
        sentiment = 'neutral'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comments (video_id, user_id, comment, sentiment) VALUES (?, ?, ?, ?)",
                   video_id, current_user.id, comment_text, sentiment)
    conn.commit()
    conn.close()

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'comment': {'username': current_user.username, 'comment': comment_text, 'created_at': created_at, 'sentiment': sentiment}})

@app.route('/search-videos')
@login_required
def search_videos():
    query = request.args.get('q', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                            LEFT JOIN ratings r ON v.id = r.video_id
                   WHERE v.title LIKE ?
                      OR v.genre LIKE ?
                      OR v.publisher LIKE ?
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.thumbnail_url
                   ''', f'%{query}%', f'%{query}%', f'%{query}%')
    videos = cursor.fetchall()

    video_list = [{
        'id': v[0], 'title': v[1], 'publisher': v[2], 'producer': v[3],
        'genre': v[4], 'age_rating': v[5], 'video_url': v[6], 'avg_rating': v[7], 'thumbnail_url': v[8]
    } for v in videos]

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    for video in video_list:
        video['user_rating'] = user_ratings.get(video['id'], 0)

    # Fetch comments
    comments_dict = {}
    if video_list:
        video_ids = [v['id'] for v in video_list]
        placeholders = ','.join(['?'] * len(video_ids))
        cursor.execute(f'''
            SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.video_id IN ({placeholders})
            ORDER BY c.created_at DESC
        ''', video_ids)
        all_comments = cursor.fetchall()
        for comment in all_comments:
            vid = comment[0]
            if vid not in comments_dict:
                comments_dict[vid] = []
            comments_dict[vid].append({
                'username': comment[1],
                'comment': comment[2],
                'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
                'sentiment': comment[4]
            })

    for video in video_list:
        video['comments'] = comments_dict.get(video['id'], [])

    conn.close()

    return jsonify(video_list)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


HOME_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamBox - Welcome</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: white;
            color: #333;
            line-height: 1.6;
        }

        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            width: 80px;
            height: 100vh;
            background: black;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 0;
            z-index: 100;
        }

        .logo-icon {
            width: 40px;
            height: 40px;
            background: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            color: black;
            margin-bottom: 3rem;
        }

        .main-content {
            margin-left: 80px;
            min-height: 100vh;
            display: grid;
            grid-template-rows: auto 1fr auto;
        }

        .hero-section {
            padding: 8rem 4rem 4rem;
            text-align: right;
            background: linear-gradient(to bottom, #f8f9fa, white);
            border-bottom: 1px solid #eee;
        }

        .hero-title {
            font-size: 4rem;
            font-weight: 300;
            color: black;
            margin-bottom: 1rem;
            letter-spacing: -2px;
        }

        .hero-subtitle {
            font-size: 1.2rem;
            color: #666;
            margin-bottom: 3rem;
            max-width: 500px;
            margin-left: auto;
        }

        .action-buttons {
            display: flex;
            gap: 1rem;
            justify-content: flex-end;
        }

        .btn {
            padding: 1rem 2rem;
            text-decoration: none;
            font-weight: 500;
            border-radius: 8px;
            transition: all 0.2s ease;
            display: inline-block;
        }

        .btn-primary {
            background: black;
            color: white;
            border: 2px solid black;
        }

        .btn-primary:hover {
            background: white;
            color: black;
        }

        .btn-secondary {
            background: white;
            color: black;
            border: 2px solid black;
        }

        .btn-secondary:hover {
            background: black;
            color: white;
        }

        .features-grid {
            padding: 4rem;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
        }

        .feature-card {
            background: #f8f9fa;
            padding: 2rem;
            border-radius: 12px;
            border-left: 4px solid black;
        }

        .feature-number {
            font-size: 2rem;
            font-weight: 300;
            color: black;
            margin-bottom: 1rem;
        }

        .feature-title {
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .feature-desc {
            color: #666;
            font-size: 0.9rem;
        }

        .footer {
            background: black;
            color: white;
            text-align: center;
            padding: 2rem;
        }

        @media (max-width: 768px) {
            .sidebar {
                width: 60px;
            }

            .main-content {
                margin-left: 60px;
            }

            .hero-section {
                padding: 4rem 2rem;
                text-align: center;
            }

            .hero-title {
                font-size: 2.5rem;
            }

            .action-buttons {
                justify-content: center;
                flex-direction: column;
                align-items: center;
            }
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo-icon">S</div>
    </div>

    <div class="main-content">
        <div class="hero-section">
            <h1 class="hero-title">StreamBox</h1>
            <p class="hero-subtitle">Your personal video streaming platform. Upload, share, and discover content in a clean, minimal environment.</p>
            <div class="action-buttons">
                <a href="{{ url_for('login') }}" class="btn btn-primary">Sign In</a>
                <a href="{{ url_for('register') }}" class="btn btn-secondary">Create Account</a>
            </div>
        </div>

        <div class="features-grid">
            <div class="feature-card">
                <div class="feature-number">01</div>
                <div class="feature-title">Upload Content</div>
                <div class="feature-desc">Share your videos with the community through our streamlined upload system</div>
            </div>
            <div class="feature-card">
                <div class="feature-number">02</div>
                <div class="feature-title">Discover Videos</div>
                <div class="feature-desc">Browse and search through a curated collection of user-generated content</div>
            </div>
            <div class="feature-card">
                <div class="feature-number">03</div>
                <div class="feature-title">Rate & Comment</div>
                <div class="feature-desc">Engage with creators through ratings and thoughtful comments</div>
            </div>
        </div>

        <div class="footer">
            <p>&copy; 2024 StreamBox. Clean streaming experience.</p>
        </div>
    </div>
</body>
</html>
'''

REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamBox - Register</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            color: #333;
            min-height: 100vh;
            display: flex;
        }

        .form-section {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }

        .info-section {
            flex: 1;
            background: black;
            color: white;
            padding: 4rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .form-container {
            background: white;
            padding: 3rem;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 400px;
        }

        .form-header {
            text-align: center;
            margin-bottom: 2rem;
        }

        .form-title {
            font-size: 2rem;
            font-weight: 300;
            color: black;
            margin-bottom: 0.5rem;
        }

        .form-subtitle {
            color: #666;
            font-size: 0.9rem;
        }

        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }

        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: #333;
        }

        .form-input, .form-select {
            width: 100%;
            padding: 1rem;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.2s ease;
            background: white;
        }

        .form-input:focus, .form-select:focus {
            outline: none;
            border-color: black;
        }

        .role-options {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-top: 0.5rem;
        }

        .role-option {
            position: relative;
        }

        .role-option input[type="radio"] {
            display: none;
        }

        .role-card {
            padding: 1.5rem;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            background: white;
        }

        .role-card:hover {
            border-color: #999;
        }

        .role-option input[type="radio"]:checked + .role-card {
            border-color: black;
            background: black;
            color: white;
        }

        .submit-btn {
            width: 100%;
            padding: 1rem;
            background: black;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 1rem;
        }

        .submit-btn:hover {
            background: #333;
        }

        .form-footer {
            text-align: center;
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid #eee;
        }

        .form-footer a {
            color: black;
            text-decoration: none;
            font-weight: 500;
        }

        .form-footer a:hover {
            text-decoration: underline;
        }

        .info-content h2 {
            font-size: 3rem;
            font-weight: 300;
            margin-bottom: 2rem;
            letter-spacing: -1px;
        }

        .info-content p {
            font-size: 1.1rem;
            line-height: 1.6;
            margin-bottom: 2rem;
            opacity: 0.9;
        }

        .info-stats {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 2rem;
            margin-top: 3rem;
        }

        .stat-item {
            text-align: center;
        }

        .stat-number {
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }

        .stat-label {
            opacity: 0.7;
            font-size: 0.9rem;
        }

        @media (max-width: 768px) {
            body {
                flex-direction: column;
            }

            .info-section {
                order: -1;
                padding: 2rem;
            }

            .info-content h2 {
                font-size: 2rem;
            }

            .form-container {
                margin: 0;
            }
        }
    </style>
</head>
<body>
    <div class="form-section">
        <div class="form-container">
            <div class="form-header">
                <h1 class="form-title">Join StreamBox</h1>
                <p class="form-subtitle">Create your account to get started</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="form-group">
                    <label for="username" class="form-label">Username</label>
                    <input type="text" id="username" name="username" class="form-input" required>
                </div>

                <div class="form-group">
                    <label for="email" class="form-label">Email Address</label>
                    <input type="email" id="email" name="email" class="form-input" required>
                </div>

                <div class="form-group">
                    <label for="password" class="form-label">Password</label>
                    <input type="password" id="password" name="password" class="form-input" required>
                </div>

                <div class="form-group">
                    <label class="form-label">Account Type</label>
                    <div class="role-options">
                        <label class="role-option">
                            <input type="radio" name="user_type" value="creator" required>
                            <div class="role-card">Creator</div>
                        </label>
                        <label class="role-option">
                            <input type="radio" name="user_type" value="consumer" required>
                            <div class="role-card">Viewer</div>
                        </label>
                    </div>
                </div>

                <button type="submit" class="submit-btn">Create Account</button>
            </form>

            <div class="form-footer">
                <a href="{{ url_for('home') }}">Back to Home</a>
            </div>
        </div>
    </div>

    <div class="info-section">
        <div class="info-content">
            <h2>Welcome to the Community</h2>
            <p>StreamBox provides a clean, distraction-free environment for sharing and discovering video content. Join creators and viewers from around the world.</p>
            <p>Choose your role and start your journey with us today.</p>

            <div class="info-stats">
                <div class="stat-item">
                    <div class="stat-number">1K+</div>
                    <div class="stat-label">Active Users</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">5K+</div>
                    <div class="stat-label">Videos Shared</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamBox - Sign In</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: white;
            color: #333;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .login-container {
            display: flex;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 80px rgba(0,0,0,0.1);
            overflow: hidden;
            max-width: 900px;
            width: 100%;
            margin: 2rem;
        }

        .login-form {
            padding: 4rem;
            flex: 1;
            background: #f8f9fa;
        }

        .brand-section {
            padding: 4rem;
            flex: 1;
            background: black;
            color: white;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
        }

        .brand-logo {
            width: 80px;
            height: 80px;
            background: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            font-weight: bold;
            color: black;
            margin-bottom: 2rem;
        }

        .brand-title {
            font-size: 2.5rem;
            font-weight: 300;
            margin-bottom: 1rem;
            letter-spacing: -1px;
        }

        .brand-subtitle {
            opacity: 0.8;
            font-size: 1rem;
            line-height: 1.5;
        }

        .form-header {
            margin-bottom: 3rem;
        }

        .form-title {
            font-size: 2.2rem;
            font-weight: 300;
            color: black;
            margin-bottom: 0.5rem;
        }

        .form-subtitle {
            color: #666;
            font-size: 1rem;
        }

        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            font-size: 0.9rem;
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border-left: 4px solid #28a745;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border-left: 4px solid #dc3545;
        }

        .input-group {
            margin-bottom: 2rem;
        }

        .input-label {
            display: block;
            margin-bottom: 0.8rem;
            font-weight: 500;
            color: #333;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .input-field {
            width: 100%;
            padding: 1.2rem;
            border: none;
            border-bottom: 2px solid #ddd;
            background: transparent;
            font-size: 1rem;
            transition: border-color 0.3s ease;
        }

        .input-field:focus {
            outline: none;
            border-bottom-color: black;
        }

        .login-btn {
            width: 100%;
            padding: 1.2rem;
            background: black;
            color: white;
            border: none;
            border-radius: 50px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 2rem 0;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .login-btn:hover {
            background: #333;
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }

        .form-links {
            text-align: center;
            padding-top: 2rem;
            border-top: 1px solid #ddd;
        }

        .form-links a {
            color: #666;
            text-decoration: none;
            font-size: 0.9rem;
            transition: color 0.2s ease;
        }

        .form-links a:hover {
            color: black;
        }

        @media (max-width: 768px) {
            .login-container {
                flex-direction: column-reverse;
                margin: 1rem;
            }

            .login-form, .brand-section {
                padding: 2rem;
            }

            .brand-section {
                padding: 3rem 2rem 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-form">
            <div class="form-header">
                <h1 class="form-title">Welcome Back</h1>
                <p class="form-subtitle">Sign in to your StreamBox account</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="input-group">
                    <label for="username" class="input-label">Username</label>
                    <input type="text" id="username" name="username" class="input-field" required>
                </div>

                <div class="input-group">
                    <label for="password" class="input-label">Password</label>
                    <input type="password" id="password" name="password" class="input-field" required>
                </div>

                <button type="submit" class="login-btn">Sign In</button>
            </form>

            <div class="form-links">
                <a href="{{ url_for('home') }}">Return to Home</a>
            </div>
        </div>

        <div class="brand-section">
            <div class="brand-logo">S</div>
            <h2 class="brand-title">StreamBox</h2>
            <p class="brand-subtitle">Your personal video streaming platform designed for simplicity and focus.</p>
        </div>
    </div>
</body>
</html>
'''

CREATOR_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamBox - Creator Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
        }

        .top-bar {
            background: white;
            padding: 1rem 2rem;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .dashboard-title {
            font-size: 1.5rem;
            font-weight: 600;
        }

        .user-menu {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .user-name {
            font-weight: 500;
            color: #666;
        }

        .logout-link {
            padding: 0.5rem 1rem;
            background: black;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.9rem;
            transition: background 0.2s ease;
        }

        .logout-link:hover {
            background: #333;
        }

        .dashboard-content {
            max-width: 800px;
            margin: 0 auto;
            padding: 3rem 2rem;
        }

        .upload-card {
            background: white;
            border-radius: 12px;
            padding: 3rem;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            margin-bottom: 2rem;
        }

        .card-header {
            text-align: center;
            margin-bottom: 3rem;
        }

        .card-title {
            font-size: 2rem;
            font-weight: 300;
            margin-bottom: 0.5rem;
        }

        .card-subtitle {
            color: #666;
            font-size: 1rem;
        }

        .alert {
            padding: 1rem 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            font-size: 0.9rem;
        }

        .alert-success {
            background: #d4edda;
            color: #155724;
            border-left: 4px solid #28a745;
        }

        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border-left: 4px solid #dc3545;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
            margin-bottom: 2rem;
        }

        .form-group {
            margin-bottom: 2rem;
        }

        .form-group.full-width {
            grid-column: 1 / -1;
        }

        .form-label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: #333;
            font-size: 0.9rem;
        }

        .form-input, .form-select {
            width: 100%;
            padding: 1rem;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.2s ease;
            background: white;
        }

        .form-input:focus, .form-select:focus {
            outline: none;
            border-color: black;
            box-shadow: 0 0 0 3px rgba(0,0,0,0.1);
        }

        .upload-area {
            border: 3px dashed #ddd;
            border-radius: 12px;
            padding: 4rem 2rem;
            text-align: center;
            background: #fafafa;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-bottom: 2rem;
        }

        .upload-area:hover {
            border-color: black;
            background: #f0f0f0;
        }

        .upload-area.dragover {
            border-color: black;
            background: #f0f0f0;
            transform: scale(1.02);
        }

        .upload-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            color: #999;
        }

        .upload-text {
            font-size: 1.1rem;
            color: #666;
            margin-bottom: 0.5rem;
        }

        .upload-hint {
            font-size: 0.9rem;
            color: #999;
        }

        .file-info {
            background: #e8f5e8;
            border: 1px solid #c3e6cb;
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            color: #155724;
            display: none;
        }

        .progress-container {
            margin: 2rem 0;
            display: none;
        }

        .progress-label {
            font-size: 0.9rem;
            color: #666;
            margin-bottom: 0.5rem;
        }

        .progress-bar {
            width: 100%;
            height: 8px;
            background: #eee;
            border-radius: 4px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background: black;
            width: 0%;
            transition: width 0.3s ease;
        }

        .submit-button {
            width: 100%;
            padding: 1.2rem;
            background: black;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 1rem;
        }

        .submit-button:hover {
            background: #333;
        }

        .submit-button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        #fileInput {
            display: none;
        }

        @media (max-width: 768px) {
            .form-row {
                grid-template-columns: 1fr;
                gap: 1rem;
            }

            .dashboard-content {
                padding: 2rem 1rem;
            }

            .upload-card {
                padding: 2rem 1.5rem;
            }

            .top-bar {
                padding: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="top-bar">
        <div class="dashboard-title">Creator Dashboard</div>
        <div class="user-menu">
            <span class="user-name">{{ current_user.username }}</span>
            <a href="{{ url_for('logout') }}" class="logout-link">Sign Out</a>
        </div>
    </div>

    <div class="dashboard-content">
        <div class="upload-card">
            <div class="card-header">
                <h2 class="card-title">Upload New Video</h2>
                <p class="card-subtitle">Share your content with the StreamBox community</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST" action="{{ url_for('upload_video') }}" enctype="multipart/form-data" id="uploadForm">
                <div class="form-row">
                    <div class="form-group">
                        <label for="title" class="form-label">Video Title</label>
                        <input type="text" id="title" name="title" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label for="publisher" class="form-label">Publisher</label>
                        <input type="text" id="publisher" name="publisher" class="form-input" required>
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="producer" class="form-label">Producer</label>
                        <input type="text" id="producer" name="producer" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label for="genre" class="form-label">Genre</label>
                        <select id="genre" name="genre" class="form-select" required>
                            <option value="">Choose Genre</option>
                            <option value="Action">Action</option>
                            <option value="Comedy">Comedy</option>
                            <option value="Drama">Drama</option>
                            <option value="Horror">Horror</option>
                            <option value="Romance">Romance</option>
                            <option value="Sci-Fi">Sci-Fi</option>
                            <option value="Documentary">Documentary</option>
                            <option value="Animation">Animation</option>
                            <option value="Thriller">Thriller</option>
                            <option value="Adventure">Adventure</option>
                        </select>
                    </div>
                </div>

                <div class="form-group">
                    <label for="age_rating" class="form-label">Age Rating</label>
                    <select id="age_rating" name="age_rating" class="form-select" required>
                        <option value="">Select Rating</option>
                        <option value="G">G - General Audiences</option>
                        <option value="PG">PG - Parental Guidance</option>
                        <option value="PG-13">PG-13 - Parents Strongly Cautioned</option>
                        <option value="R">R - Restricted</option>
                        <option value="NC-17">NC-17 - Adults Only</option>
                        <option value="18">18+ - Adult Content</option>
                    </select>
                </div>

                <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                    <div class="upload-icon">📁</div>
                    <div class="upload-text">Click to select video file</div>
                    <div class="upload-hint">or drag and drop here</div>
                </div>
                
                <input type="file" id="fileInput" name="video" accept="video/*" required>
                <div class="file-info" id="fileInfo"></div>

                <div class="progress-container" id="progressContainer">
                    <div class="progress-label">Uploading...</div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill"></div>
                    </div>
                </div>

                <button type="submit" class="submit-button" id="submitButton">Upload Video</button>
            </form>
        </div>
    </div>

    <script>
        const fileInput = document.getElementById('fileInput');
        const uploadArea = document.querySelector('.upload-area');
        const fileInfo = document.getElementById('fileInfo');
        const uploadForm = document.getElementById('uploadForm');
        const progressContainer = document.getElementById('progressContainer');
        const progressFill = document.getElementById('progressFill');
        const submitButton = document.getElementById('submitButton');

        fileInput.addEventListener('change', handleFileSelect);

        function handleFileSelect(e) {
            const file = e.target.files[0];
            if (file) {
                fileInfo.style.display = 'block';
                fileInfo.innerHTML = `
                    <strong>Selected:</strong> ${file.name}<br>
                    <strong>Size:</strong> ${(file.size / 1024 / 1024).toFixed(2)} MB<br>
                    <strong>Type:</strong> ${file.type}
                `;
                uploadArea.style.borderColor = 'black';
                uploadArea.querySelector('.upload-text').textContent = 'File ready for upload';
            }
        }

        // Drag and drop functionality
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            uploadArea.addEventListener(eventName, () => uploadArea.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, () => uploadArea.classList.remove('dragover'), false);
        });

        uploadArea.addEventListener('drop', handleDrop, false);

        function handleDrop(e) {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                handleFileSelect({ target: { files } });
            }
        }

        uploadForm.addEventListener('submit', function(e) {
            submitButton.textContent = 'Uploading...';
            submitButton.disabled = true;
            progressContainer.style.display = 'block';

            let progress = 0;
            const interval = setInterval(() => {
                progress += Math.random() * 15;
                if (progress > 90) progress = 90;
                progressFill.style.width = progress + '%';
            }, 300);

            setTimeout(() => {
                clearInterval(interval);
                progressFill.style.width = '100%';
            }, 3000);
        });
    </script>
</body>
</html>
'''

CONSUMER_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamBox - Browse Videos</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: white;
            color: #333;
            line-height: 1.6;
        }

        .header {
            background: black;
            color: white;
            padding: 1rem 0;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 2rem;
        }

        .logo {
            font-size: 1.5rem;
            font-weight: bold;
        }

        .search-container {
            flex: 1;
            max-width: 500px;
            position: relative;
        }

        .search-input {
            width: 100%;
            padding: 0.8rem 1rem;
            border: none;
            border-radius: 25px;
            font-size: 1rem;
            outline: none;
        }

        .search-btn {
            position: absolute;
            right: 5px;
            top: 50%;
            transform: translateY(-50%);
            background: black;
            color: white;
            border: none;
            padding: 0.6rem 1.2rem;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9rem;
        }

        .user-info {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .username {
            font-weight: 500;
        }

        .logout-btn {
            background: white;
            color: black;
            padding: 0.5rem 1rem;
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }

        .logout-btn:hover {
            background: #f0f0f0;
        }

        .main-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }

        .page-title {
            font-size: 2.5rem;
            font-weight: 300;
            margin-bottom: 3rem;
            color: black;
        }

        .video-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 3rem;
        }

        .video-card {
            background: #f8f9fa;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: transform 0.2s ease;
        }

        .video-card:hover {
            transform: translateY(-5px);
        }

        .video-header {
            background: black;
            color: white;
            padding: 1rem 1.5rem;
            font-weight: 600;
            font-size: 1.1rem;
        }

        .video-meta {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            padding: 1rem 1.5rem;
            background: white;
            border-bottom: 1px solid #eee;
        }

        .meta-item {
            font-size: 0.9rem;
        }

        .meta-label {
            color: #666;
            font-weight: 500;
            display: block;
        }

        .meta-value {
            color: #333;
            font-weight: 400;
        }

        .video-player {
            width: 100%;
            height: 250px;
            background: black;
        }

        .interaction-section {
            padding: 1.5rem;
            background: white;
        }

        .rating-area {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #eee;
        }

        .star-rating {
            display: flex;
            gap: 0.3rem;
        }

        .star {
            font-size: 1.5rem;
            color: #ddd;
            cursor: pointer;
            transition: color 0.2s ease;
        }

        .star:hover,
        .star.active {
            color: black;
        }

        .rating-info {
            font-size: 0.9rem;
            color: #666;
        }

        .comment-section textarea {
            width: 100%;
            padding: 1rem;
            border: 1px solid #ddd;
            border-radius: 8px;
            resize: vertical;
            min-height: 80px;
            font-family: inherit;
            font-size: 0.9rem;
            margin-bottom: 1rem;
        }

        .comment-section textarea:focus {
            outline: none;
            border-color: black;
        }

        .comment-btn {
            background: black;
            color: white;
            border: none;
            padding: 0.6rem 1.2rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: background 0.2s ease;
        }

        .comment-btn:hover {
            background: #333;
        }

        .comments-list {
            margin-top: 1.5rem;
            max-height: 200px;
            overflow-y: auto;
        }

        .comment {
            padding: 1rem 0;
            border-bottom: 1px solid #f0f0f0;
        }

        .comment:last-child {
            border-bottom: none;
        }

        .comment-author {
            font-weight: 600;
            font-size: 0.9rem;
            color: black;
            margin-bottom: 0.3rem;
        }

        .comment-text {
            color: #666;
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
        }

        .comment-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: #999;
        }

        .sentiment-badge {
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
        }

        .sentiment-positive {
            background: #d4edda;
            color: #155724;
        }

        .sentiment-negative {
            background: #f8d7da;
            color: #721c24;
        }

        .sentiment-neutral {
            background: #e2e3e5;
            color: #495057;
        }

        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: #666;
            background: #f8f9fa;
            border-radius: 12px;
            margin-top: 2rem;
        }

        .empty-state h3 {
            font-size: 1.5rem;
            font-weight: 300;
            margin-bottom: 1rem;
        }

        @media (max-width: 768px) {
            .header-content {
                flex-direction: column;
                gap: 1rem;
            }
            
            .video-grid {
                grid-template-columns: 1fr;
                gap: 2rem;
            }
            
            .main-content {
                padding: 1rem;
            }
            
            .page-title {
                font-size: 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <div class="logo">StreamBox</div>
            <div class="search-container">
                <input type="text" class="search-input" id="searchInput" placeholder="Search videos...">
                <button class="search-btn" onclick="searchVideos()">Search</button>
            </div>
            <div class="user-info">
                <span class="username">{{ current_user.username }}</span>
                <a href="{{ url_for('logout') }}" class="logout-btn">Sign Out</a>
            </div>
        </div>
    </div>

    <div class="main-content">
        <h1 class="page-title">Browse Videos</h1>
        
        <div class="video-grid" id="videoGrid">
            {% if videos %}
                {% for video in videos %}
                <div class="video-card">
                    <div class="video-header">{{ video[1] }}</div>
                    
                    <div class="video-meta">
                        <div class="meta-item">
                            <span class="meta-label">Publisher:</span>
                            <span class="meta-value">{{ video[2] }}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Producer:</span>
                            <span class="meta-value">{{ video[3] }}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Genre:</span>
                            <span class="meta-value">{{ video[4] }}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Rating:</span>
                            <span class="meta-value">{{ video[5] }}</span>
                        </div>
                    </div>

                    <video class="video-player" controls>
                        <source src="{{ video[6] }}" type="video/mp4">
                        Your browser does not support video playback.
                    </video>

                    <div class="interaction-section">
                        <div class="rating-area">
                            <div class="star-rating" data-video-id="{{ video[0] }}">
                                {% set user_rating = user_ratings.get(video[0], 0) %}
                                {% for i in range(1, 6) %}
                                <span class="star {% if i <= user_rating %}active{% endif %}" data-rating="{{ i }}">★</span>
                                {% endfor %}
                            </div>
                            <div class="rating-info">
                                {% if video[7] %}
                                    Average: {{ "%.1f"|format(video[7]) }}/5
                                {% else %}
                                    No ratings yet
                                {% endif %}
                            </div>
                        </div>

                        <div class="comment-section">
                            <textarea placeholder="Share your thoughts..." data-video-id="{{ video[0] }}"></textarea>
                            <button class="comment-btn" onclick="addComment({{ video[0] }})">Post Comment</button>
                            
                            <div class="comments-list">
                                {% if comments[video[0]] %}
                                    {% for comment in comments[video[0]] %}
                                    <div class="comment">
                                        <div class="comment-author">{{ comment.username }}</div>
                                        <div class="comment-text">{{ comment.comment }}</div>
                                        <div class="comment-meta">
                                            <span>{{ comment.created_at }}</span>
                                            <span class="sentiment-badge sentiment-{{ comment.sentiment }}">
                                                {{ comment.sentiment }}
                                            </span>
                                        </div>
                                    </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="comment">
                                        <div class="comment-text">No comments yet. Be the first to share your thoughts!</div>
                                    </div>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state">
                    <h3>No Videos Available</h3>
                    <p>Check back later for new content uploads.</p>
                </div>
            {% endif %}
        </div>
    </div>

    <script>
        // Rating functionality
        document.querySelectorAll('.star-rating').forEach(rating => {
            const stars = rating.querySelectorAll('.star');
            const videoId = rating.dataset.videoId;

            stars.forEach((star, index) => {
                star.addEventListener('click', () => {
                    const ratingValue = index + 1;
                    
                    fetch('/rate-video', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            video_id: videoId,
                            rating: ratingValue
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            stars.forEach((s, i) => {
                                s.classList.toggle('active', i < ratingValue);
                            });
                            
                            const ratingInfo = rating.closest('.rating-area').querySelector('.rating-info');
                            ratingInfo.textContent = data.avg_rating ? 
                                `Average: ${data.avg_rating.toFixed(1)}/5` : 'No ratings yet';
                        }
                    })
                    .catch(error => console.error('Rating error:', error));
                });

                star.addEventListener('mouseenter', () => {
                    stars.forEach((s, i) => {
                        s.style.color = i <= index ? 'black' : '#ddd';
                    });
                });

                rating.addEventListener('mouseleave', () => {
                    stars.forEach(s => {
                        s.style.color = s.classList.contains('active') ? 'black' : '#ddd';
                    });
                });
            });
        });

        // Comment functionality
        function addComment(videoId) {
            const textarea = document.querySelector(`textarea[data-video-id="${videoId}"]`);
            const comment = textarea.value.trim();

            if (!comment) return;

            fetch('/add-comment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_id: videoId,
                    comment: comment
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const commentsList = textarea.closest('.comment-section').querySelector('.comments-list');
                    
                    const newComment = document.createElement('div');
                    newComment.className = 'comment';
                    newComment.innerHTML = `
                        <div class="comment-author">${data.comment.username}</div>
                        <div class="comment-text">${data.comment.comment}</div>
                        <div class="comment-meta">
                            <span>${data.comment.created_at}</span>
                            <span class="sentiment-badge sentiment-${data.comment.sentiment}">
                                ${data.comment.sentiment}
                            </span>
                        </div>
                    `;
                    
                    commentsList.insertBefore(newComment, commentsList.firstChild);
                    textarea.value = '';
                }
            })
            .catch(error => console.error('Comment error:', error));
        }

        // Search functionality
        function searchVideos() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) {
                location.reload();
                return;
            }

            fetch(`/search-videos?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(videos => {
                    const videoGrid = document.getElementById('videoGrid');
                    
                    if (videos.length === 0) {
                        videoGrid.innerHTML = `
                            <div class="empty-state">
                                <h3>No Results Found</h3>
                                <p>Try searching with different keywords.</p>
                            </div>
                        `;
                        return;
                    }

                    videoGrid.innerHTML = videos.map(video => `
                        <div class="video-card">
                            <div class="video-header">${video.title}</div>
                            
                            <div class="video-meta">
                                <div class="meta-item">
                                    <span class="meta-label">Publisher:</span>
                                    <span class="meta-value">${video.publisher}</span>
                                </div>
                                <div class="meta-item">
                                    <span class="meta-label">Producer:</span>
                                    <span class="meta-value">${video.producer}</span>
                                </div>
                                <div class="meta-item">
                                    <span class="meta-label">Genre:</span>
                                    <span class="meta-value">${video.genre}</span>
                                </div>
                                <div class="meta-item">
                                    <span class="meta-label">Rating:</span>
                                    <span class="meta-value">${video.age_rating}</span>
                                </div>
                            </div>

                            <video class="video-player" controls>
                                <source src="${video.video_url}" type="video/mp4">
                                Your browser does not support video playback.
                            </video>

                            <div class="interaction-section">
                                <div class="rating-area">
                                    <div class="star-rating" data-video-id="${video.id}">
                                        ${[1,2,3,4,5].map(i => 
                                            `<span class="star ${i <= (video.user_rating || 0) ? 'active' : ''}" data-rating="${i}">★</span>`
                                        ).join('')}
                                    </div>
                                    <div class="rating-info">
                                        ${video.avg_rating ? `Average: ${video.avg_rating.toFixed(1)}/5` : 'No ratings yet'}
                                    </div>
                                </div>

                                <div class="comment-section">
                                    <textarea placeholder="Share your thoughts..." data-video-id="${video.id}"></textarea>
                                    <button class="comment-btn" onclick="addComment(${video.id})">Post Comment</button>
                                    
                                    <div class="comments-list">
                                        ${video.comments.map(comment => `
                                            <div class="comment">
                                                <div class="comment-author">${comment.username}</div>
                                                <div class="comment-text">${comment.comment}</div>
                                                <div class="comment-meta">
                                                    <span>${comment.created_at}</span>
                                                    <span class="sentiment-badge sentiment-${comment.sentiment}">
                                                        ${comment.sentiment}
                                                    </span>
                                                </div>
                                            </div>
                                        `).join('') || '<div class="comment"><div class="comment-text">No comments yet. Be the first to share your thoughts!</div></div>'}
                                    </div>
                                </div>
                            </div>
                        </div>
                    `).join('');

                    // Re-initialize event listeners
                    initializeRatingListeners();
                })
                .catch(error => console.error('Search error:', error));
        }

        function initializeRatingListeners() {
            document.querySelectorAll('.star-rating').forEach(rating => {
                const stars = rating.querySelectorAll('.star');
                const videoId = rating.dataset.videoId;

                stars.forEach((star, index) => {
                    star.addEventListener('click', () => {
                        const ratingValue = index + 1;
                        
                        fetch('/rate-video', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                video_id: videoId,
                                rating: ratingValue
                            })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                stars.forEach((s, i) => {
                                    s.classList.toggle('active', i < ratingValue);
                                });
                                
                                const ratingInfo = rating.closest('.rating-area').querySelector('.rating-info');
                                ratingInfo.textContent = data.avg_rating ? 
                                    `Average: ${data.avg_rating.toFixed(1)}/5` : 'No ratings yet';
                            }
                        })
                        .catch(error => console.error('Rating error:', error));
                    });

                    star.addEventListener('mouseenter', () => {
                        stars.forEach((s, i) => {
                            s.style.color = i <= index ? 'black' : '#ddd';
                        });
                    });

                    rating.addEventListener('mouseleave', () => {
                        stars.forEach(s => {
                            s.style.color = s.classList.contains('active') ? 'black' : '#ddd';
                        });
                    });
                });
            });
        }

        // Search on Enter key
        document.getElementById('searchInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchVideos();
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)