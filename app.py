
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, PlayerProfile, TeamRequirement, Interest, Message
from models import Achievement, PlayerRating, ProfileView
from PIL import Image
from datetime import datetime, timedelta
from collections import Counter
import os

app = Flask(__name__)
app.config['SECRET_KEY']                  = 'sportslink-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI']     = 'sqlite:///sportslink.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']              = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH']         = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db.init_app(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

login_manager = LoginManager(app)
login_manager.login_view         = 'login'
login_manager.login_message      = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def unread_count():
    if current_user.is_authenticated:
        return Message.query.filter_by(
            receiver_id=current_user.id, is_read=False).count()
    return 0


@app.context_processor
def inject_globals():
    return dict(unread_count=unread_count())


# ─────────────────────────────────────────────
#  Core Matching Algorithm
# ─────────────────────────────────────────────
def match_players_to_requirement(requirement):
    """
    Weighted Scoring Algorithm:
    sport match   = +3 pts
    position match= +2 pts
    experience    = +1 pt
    per skill     = +1 pt each
    avg rating    = +0 to +2 bonus pts
    """
    players    = PlayerProfile.query.all()
    results    = []
    req_skills = set(s.strip().lower()
                     for s in requirement.skills_required.split(',') if s.strip())

    for player in players:
        score          = 0
        matched_skills = []

        if player.sport.lower()    == requirement.sport.lower():    score += 3
        if player.position.lower() == requirement.position.lower(): score += 2
        if player.experience_years >= requirement.min_experience:   score += 1

        player_skills  = set(s.strip().lower()
                             for s in player.skills.split(',') if s.strip())
        matched_skills = list(req_skills & player_skills)
        score         += len(matched_skills)

        # Bonus: rating boost (max +2)
        avg = player.avg_rating()
        if avg >= 4.5:   score += 2
        elif avg >= 3.5: score += 1

        if score > 0:
            results.append({
                'player':         player,
                'score':          score,
                'matched_skills': matched_skills,
                'total_skills':   len(req_skills)
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


# ─────────────────────────────────────────────
#  AI Recommendation Engine
# ─────────────────────────────────────────────
def ai_recommend_players(requirement, top_n=5):
    """
    AI-style recommendation using multi-factor weighted scoring.
    Factors: skill overlap %, experience fit, rating, profile views,
             interest count (social proof), location bonus.
    Returns top_n players with detailed breakdown.
    """
    players    = PlayerProfile.query.all()
    results    = []
    req_skills = set(s.strip().lower()
                     for s in requirement.skills_required.split(',') if s.strip())

    for player in players:
        ai_score       = 0
        breakdown      = {}
        player_skills  = set(s.strip().lower()
                             for s in player.skills.split(',') if s.strip())
        matched_skills = req_skills & player_skills

        # 1. Skill overlap percentage (0–40 pts)
        if req_skills:
            skill_pct = len(matched_skills) / len(req_skills) * 40
        else:
            skill_pct = 0
        ai_score += skill_pct
        breakdown['skill_match'] = round(skill_pct)

        # 2. Sport match (0 or 20 pts)
        sport_score = 20 if player.sport.lower() == requirement.sport.lower() else 0
        ai_score   += sport_score
        breakdown['sport'] = sport_score

        # 3. Position match (0 or 15 pts)
        pos_score  = 15 if player.position.lower() == requirement.position.lower() else 0
        ai_score  += pos_score
        breakdown['position'] = pos_score

        # 4. Experience fit (0–10 pts)
        if requirement.min_experience > 0:
            exp_ratio = min(player.experience_years / requirement.min_experience, 2)
            exp_score = exp_ratio * 5
        else:
            exp_score = 10 if player.experience_years > 0 else 5
        ai_score += exp_score
        breakdown['experience'] = round(exp_score)

        # 5. Rating score (0–10 pts)
        rating_score = player.avg_rating() * 2
        ai_score    += rating_score
        breakdown['rating'] = round(rating_score)

        # 6. Social proof — interest count (0–5 pts)
        interest_count  = Interest.query.filter_by(player_id=player.user_id).count()
        social_score    = min(interest_count * 1.5, 5)
        ai_score       += social_score
        breakdown['social'] = round(social_score)

        # 7. Location bonus (0 or 5 pts)
        loc_score = 0
        if requirement.location and player.location:
            req_city    = requirement.location.split(',')[0].strip().lower()
            player_city = player.location.split(',')[0].strip().lower()
            if req_city and req_city in player_city:
                loc_score = 5
        ai_score += loc_score
        breakdown['location'] = loc_score

        if ai_score > 10:
            results.append({
                'player':         player,
                'ai_score':       round(ai_score, 1),
                'matched_skills': list(matched_skills),
                'breakdown':      breakdown,
                'confidence':     min(round(ai_score), 100)
            })

    results.sort(key=lambda x: x['ai_score'], reverse=True)
    return results[:top_n]


# ─────────────────────────────────────────────
#  Auth Routes
# ─────────────────────────────────────────────
@app.route('/')
def index():
    player_count = PlayerProfile.query.count()
    team_count   = TeamRequirement.query.count()
    return render_template('index.html',
                           player_count=player_count,
                           team_count=team_count)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email',    '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        role     = request.form.get('role', '')

        errors = []
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if not email or '@' not in email:
            errors.append('Enter a valid email address.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')
        if role not in ('player', 'team'):
            errors.append('Please select a valid role.')
        if User.query.filter_by(username=username).first():
            errors.append('Username already taken.')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')

        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('register.html')

        user = User(username=username, email=email,
                    password=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = request.form.get('email',    '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please fill in all fields.', 'danger')
            return render_template('login.html')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ─────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'player':
        profile        = PlayerProfile.query.filter_by(user_id=current_user.id).first()
        requirements   = TeamRequirement.query.order_by(TeamRequirement.id.desc()).limit(5).all()
        interested_ids = [i.requirement_id for i in
                          Interest.query.filter_by(player_id=current_user.id).all()]
        return render_template('dashboard.html', profile=profile,
                               requirements=requirements,
                               interested_ids=interested_ids)
    else:
        requirements = TeamRequirement.query.filter_by(user_id=current_user.id).all()
        return render_template('dashboard.html', requirements=requirements)


# ─────────────────────────────────────────────
#  Player Profile
# ─────────────────────────────────────────────
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def player_profile():
    if current_user.role != 'player':
        flash('Only players can create profiles.', 'warning')
        return redirect(url_for('dashboard'))

    profile = PlayerProfile.query.filter_by(user_id=current_user.id).first()

    if request.method == 'POST':
        sport      = request.form.get('sport',            '').strip()
        position   = request.form.get('position',         '').strip()
        skills     = request.form.get('skills',           '').strip()
        experience = request.form.get('experience_years', '0').strip()
        bio        = request.form.get('bio',              '').strip()
        location   = request.form.get('location',         '').strip()

        errors = []
        if not sport:    errors.append('Sport is required.')
        if not position: errors.append('Position is required.')
        if not skills:   errors.append('Please list at least one skill.')
        try:
            experience = int(experience)
            if experience < 0: raise ValueError
        except ValueError:
            errors.append('Experience must be a non-negative number.')
            experience = 0

        photo_file = request.files.get('avatar')
        if photo_file and photo_file.filename:
            if allowed_file(photo_file.filename):
                filename = secure_filename(f"user_{current_user.id}_{photo_file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                img = Image.open(photo_file)
                img = img.convert('RGB')
                img.thumbnail((200, 200))
                img.save(filepath)
                current_user.avatar = filename
                db.session.commit()
            else:
                errors.append('Only PNG, JPG, JPEG, GIF files allowed.')

        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('profile.html', profile=profile)

        if profile:
            profile.sport            = sport
            profile.position         = position
            profile.skills           = skills
            profile.experience_years = experience
            profile.bio              = bio
            profile.location         = location
            flash('Profile updated!', 'success')
        else:
            profile = PlayerProfile(user_id=current_user.id, sport=sport,
                                    position=position, skills=skills,
                                    experience_years=experience, bio=bio,
                                    location=location)
            db.session.add(profile)
            flash('Profile created!', 'success')

        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template('profile.html', profile=profile)


# ─────────────────────────────────────────────
#  Achievements
# ─────────────────────────────────────────────
@app.route('/achievement/add', methods=['POST'])
@login_required
def add_achievement():
    profile = PlayerProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        flash('Create your profile first.', 'warning')
        return redirect(url_for('player_profile'))

    title       = request.form.get('title',       '').strip()
    description = request.form.get('description', '').strip()
    badge_icon  = request.form.get('badge_icon',  '🏅').strip()
    date_earned = request.form.get('date_earned', '').strip()

    if not title:
        flash('Achievement title is required.', 'danger')
        return redirect(url_for('player_profile'))

    db.session.add(Achievement(player_id=profile.id, title=title,
                               description=description,
                               badge_icon=badge_icon or '🏅',
                               date_earned=date_earned))
    db.session.commit()
    flash('Achievement added!', 'success')
    return redirect(url_for('player_profile'))


@app.route('/achievement/delete/<int:ach_id>', methods=['POST'])
@login_required
def delete_achievement(ach_id):
    ach     = Achievement.query.get_or_404(ach_id)
    profile = PlayerProfile.query.filter_by(user_id=current_user.id).first()
    if not profile or ach.player_id != profile.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    db.session.delete(ach)
    db.session.commit()
    flash('Achievement removed.', 'info')
    return redirect(url_for('player_profile'))


# ─────────────────────────────────────────────
#  Player Rating
# ─────────────────────────────────────────────
@app.route('/rate-player/<int:player_id>', methods=['POST'])
@login_required
def rate_player(player_id):
    if current_user.role != 'team':
        flash('Only teams can rate players.', 'warning')
        return redirect(url_for('player_detail', player_id=player_id))

    profile = PlayerProfile.query.get_or_404(player_id)
    rating  = int(request.form.get('rating', 0))
    review  = request.form.get('review', '').strip()

    if not 1 <= rating <= 5:
        flash('Rating must be between 1 and 5.', 'danger')
        return redirect(url_for('player_detail', player_id=player_id))

    existing = PlayerRating.query.filter_by(
        player_id=profile.id, rater_id=current_user.id).first()

    if existing:
        existing.rating = rating
        existing.review = review
        flash('Rating updated!', 'success')
    else:
        db.session.add(PlayerRating(player_id=profile.id,
                                    rater_id=current_user.id,
                                    rating=rating, review=review))
        flash('Player rated successfully!', 'success')

    db.session.commit()
    return redirect(url_for('player_detail', player_id=player_id))


# ─────────────────────────────────────────────
#  Team Requirements
# ─────────────────────────────────────────────
@app.route('/post-requirement', methods=['GET', 'POST'])
@login_required
def post_requirement():
    if current_user.role != 'team':
        flash('Only teams can post requirements.', 'warning')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        team_name   = request.form.get('team_name',       '').strip()
        sport       = request.form.get('sport',           '').strip()
        position    = request.form.get('position',        '').strip()
        skills_req  = request.form.get('skills_required', '').strip()
        min_exp     = request.form.get('min_experience',  '0').strip()
        description = request.form.get('description',     '').strip()
        location    = request.form.get('location',        '').strip()

        errors = []
        if not team_name:  errors.append('Team name is required.')
        if not sport:      errors.append('Sport is required.')
        if not position:   errors.append('Position is required.')
        if not skills_req: errors.append('Required skills cannot be empty.')
        try:
            min_exp = int(min_exp)
            if min_exp < 0: raise ValueError
        except ValueError:
            errors.append('Minimum experience must be non-negative.')
            min_exp = 0

        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('post_requirement.html')

        db.session.add(TeamRequirement(
            user_id=current_user.id, team_name=team_name, sport=sport,
            position=position, skills_required=skills_req,
            min_experience=min_exp, description=description, location=location))
        db.session.commit()
        flash('Requirement posted!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('post_requirement.html')


@app.route('/requirement/<int:req_id>')
@login_required
def view_requirement(req_id):
    req     = TeamRequirement.query.get_or_404(req_id)
    matches = match_players_to_requirement(req)

    # AI recommendations
    ai_recs = ai_recommend_players(req, top_n=5)

    already_interested = False
    if current_user.role == 'player':
        already_interested = Interest.query.filter_by(
            player_id=current_user.id, requirement_id=req_id).first() is not None

    interested_players = Interest.query.filter_by(requirement_id=req_id).all()

    return render_template('requirement_detail.html', req=req,
                           matches=matches, ai_recs=ai_recs,
                           already_interested=already_interested,
                           interested_players=interested_players)


@app.route('/requirement/delete/<int:req_id>', methods=['POST'])
@login_required
def delete_requirement(req_id):
    req = TeamRequirement.query.get_or_404(req_id)
    if req.user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    db.session.delete(req)
    db.session.commit()
    flash('Requirement deleted.', 'info')
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────
#  Interest
# ─────────────────────────────────────────────
@app.route('/interest/<int:req_id>', methods=['POST'])
@login_required
def express_interest(req_id):
    if current_user.role != 'player':
        flash('Only players can express interest.', 'warning')
        return redirect(url_for('view_requirement', req_id=req_id))

    profile = PlayerProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        flash('Create your player profile first.', 'warning')
        return redirect(url_for('player_profile'))

    existing = Interest.query.filter_by(
        player_id=current_user.id, requirement_id=req_id).first()
    if existing:
        flash('You already expressed interest.', 'info')
    else:
        db.session.add(Interest(player_id=current_user.id, requirement_id=req_id))
        db.session.commit()
        flash('Interest expressed! The team can now see your profile.', 'success')

    return redirect(url_for('view_requirement', req_id=req_id))


@app.route('/interest/withdraw/<int:req_id>', methods=['POST'])
@login_required
def withdraw_interest(req_id):
    interest = Interest.query.filter_by(
        player_id=current_user.id, requirement_id=req_id).first()
    if interest:
        db.session.delete(interest)
        db.session.commit()
        flash('Interest withdrawn.', 'info')
    return redirect(url_for('view_requirement', req_id=req_id))


# ─────────────────────────────────────────────
#  Messages
# ─────────────────────────────────────────────
@app.route('/messages')
@login_required
def messages():
    sent     = db.session.query(Message.receiver_id).filter_by(sender_id=current_user.id)
    received = db.session.query(Message.sender_id).filter_by(receiver_id=current_user.id)
    contact_ids = set([r[0] for r in sent.all()] + [r[0] for r in received.all()])
    contacts    = User.query.filter(User.id.in_(contact_ids)).all()

    conversations = []
    for contact in contacts:
        last_msg = Message.query.filter(
            db.or_(
                db.and_(Message.sender_id == current_user.id,
                        Message.receiver_id == contact.id),
                db.and_(Message.sender_id == contact.id,
                        Message.receiver_id == current_user.id)
            )).order_by(Message.created_at.desc()).first()

        unread = Message.query.filter_by(
            sender_id=contact.id,
            receiver_id=current_user.id, is_read=False).count()

        conversations.append({
            'contact':  contact,
            'last_msg': last_msg,
            'unread':   unread
        })

    conversations.sort(
        key=lambda x: x['last_msg'].created_at if x['last_msg'] else datetime.min,
        reverse=True)

    return render_template('messages.html', conversations=conversations)


@app.route('/messages/<int:user_id>', methods=['GET', 'POST'])
@login_required
def chat(user_id):
    other_user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        if body:
            db.session.add(Message(sender_id=current_user.id,
                                   receiver_id=user_id, body=body))
            db.session.commit()
        return redirect(url_for('chat', user_id=user_id))

    chat_messages = Message.query.filter(
        db.or_(
            db.and_(Message.sender_id == current_user.id,
                    Message.receiver_id == user_id),
            db.and_(Message.sender_id == user_id,
                    Message.receiver_id == current_user.id)
        )).order_by(Message.created_at.asc()).all()

    Message.query.filter_by(sender_id=user_id,
                             receiver_id=current_user.id,
                             is_read=False).update({'is_read': True})
    db.session.commit()

    return render_template('chat.html', other_user=other_user,
                           chat_messages=chat_messages)


# ─────────────────────────────────────────────
#  Players Browse
# ─────────────────────────────────────────────
@app.route('/players')
@login_required
def view_players():
    sport    = request.args.get('sport',    '').strip()
    position = request.args.get('position', '').strip()
    skill    = request.args.get('skill',    '').strip()
    location = request.args.get('location', '').strip()

    query = PlayerProfile.query
    if sport:    query = query.filter(PlayerProfile.sport.ilike(f'%{sport}%'))
    if position: query = query.filter(PlayerProfile.position.ilike(f'%{position}%'))
    if skill:    query = query.filter(PlayerProfile.skills.ilike(f'%{skill}%'))
    if location: query = query.filter(PlayerProfile.location.ilike(f'%{location}%'))

    players = query.all()
    return render_template('players.html', players=players,
                           filters={'sport': sport, 'position': position,
                                    'skill': skill, 'location': location})


@app.route('/player/<int:player_id>')
@login_required
def player_detail(player_id):
    profile = PlayerProfile.query.get_or_404(player_id)

    # Track profile view
    if current_user.id != profile.user_id:
        existing_view = ProfileView.query.filter_by(
            profile_id=profile.id, viewer_id=current_user.id).first()
        if not existing_view:
            db.session.add(ProfileView(profile_id=profile.id,
                                       viewer_id=current_user.id))
            profile.profile_views += 1
            db.session.commit()

    # Check if current team already rated this player
    existing_rating = None
    if current_user.role == 'team':
        existing_rating = PlayerRating.query.filter_by(
            player_id=profile.id, rater_id=current_user.id).first()

    return render_template('player_detail.html', profile=profile,
                           existing_rating=existing_rating)


# ─────────────────────────────────────────────
#  Requirements Browse
# ─────────────────────────────────────────────
@app.route('/requirements')
@login_required
def view_requirements():
    sport    = request.args.get('sport',    '').strip()
    position = request.args.get('position', '').strip()
    location = request.args.get('location', '').strip()

    query = TeamRequirement.query
    if sport:    query = query.filter(TeamRequirement.sport.ilike(f'%{sport}%'))
    if position: query = query.filter(TeamRequirement.position.ilike(f'%{position}%'))
    if location: query = query.filter(TeamRequirement.location.ilike(f'%{location}%'))

    requirements   = query.order_by(TeamRequirement.id.desc()).all()
    interested_ids = []
    if current_user.role == 'player':
        interested_ids = [i.requirement_id for i in
                          Interest.query.filter_by(player_id=current_user.id).all()]

    return render_template('requirements.html', requirements=requirements,
                           filters={'sport': sport, 'position': position,
                                    'location': location},
                           interested_ids=interested_ids)


# ─────────────────────────────────────────────
#  🏆 Leaderboard
# ─────────────────────────────────────────────
@app.route('/leaderboard')
@login_required
def leaderboard():
    sport_filter = request.args.get('sport', '').strip()

    query = PlayerProfile.query
    if sport_filter:
        query = query.filter(PlayerProfile.sport.ilike(f'%{sport_filter}%'))

    players = query.all()

    # Build leaderboard with composite score
    board = []
    for p in players:
        composite = (
            p.avg_rating() * 20 +           # rating (0-100)
            min(p.experience_years * 3, 30) + # experience (0-30)
            min(p.profile_views * 0.5, 20) +  # popularity (0-20)
            min(len(p.skills_list()) * 2, 20) +# skill count (0-20)
            min(len(p.achievements) * 5, 10)   # achievements (0-10)
        )
        board.append({
            'player':     p,
            'composite':  round(composite, 1),
            'avg_rating': p.avg_rating(),
            'rating_count': len(p.ratings)
        })

    board.sort(key=lambda x: x['composite'], reverse=True)

    # All sports for filter dropdown
    all_sports = list(set(p.sport for p in PlayerProfile.query.all()))

    return render_template('leaderboard.html', board=board,
                           sport_filter=sport_filter, all_sports=all_sports)


# ─────────────────────────────────────────────
#  📊 Analytics Dashboard
# ─────────────────────────────────────────────
@app.route('/analytics')
@login_required
def analytics():
    if current_user.role == 'player':
        profile = PlayerProfile.query.filter_by(user_id=current_user.id).first()
        if not profile:
            flash('Create your profile first.', 'warning')
            return redirect(url_for('player_profile'))

        # Profile views over last 7 days
        views_data = []
        for i in range(6, -1, -1):
            day   = datetime.utcnow() - timedelta(days=i)
            count = ProfileView.query.filter(
                ProfileView.profile_id == profile.id,
                ProfileView.viewed_at >= day.replace(hour=0, minute=0, second=0),
                ProfileView.viewed_at <  day.replace(hour=23, minute=59, second=59)
            ).count()
            views_data.append({'day': day.strftime('%a'), 'count': count})

        # Interest count
        interest_count = Interest.query.filter_by(player_id=current_user.id).count()

        # Match rate — how many openings match this player
        all_reqs     = TeamRequirement.query.all()
        match_count  = sum(1 for r in all_reqs
                           if match_players_to_requirement(r) and
                           any(m['player'].id == profile.id
                               for m in match_players_to_requirement(r)))

        # Rating stats
        avg_rating   = profile.avg_rating()
        rating_count = len(profile.ratings)

        return render_template('analytics.html',
                               profile=profile,
                               views_data=views_data,
                               interest_count=interest_count,
                               match_count=match_count,
                               avg_rating=avg_rating,
                               rating_count=rating_count,
                               total_views=profile.profile_views)

    else:
        # Team analytics
        requirements = TeamRequirement.query.filter_by(user_id=current_user.id).all()

        # Total interests across all openings
        total_interests = sum(len(r.interests) for r in requirements)

        # Interests per opening
        req_interest_data = [
            {'name': r.position, 'count': len(r.interests)}
            for r in requirements
        ]

        # Sport distribution of interested players
        sport_counts = Counter()
        for req in requirements:
            for interest in req.interests:
                p = PlayerProfile.query.filter_by(user_id=interest.player_id).first()
                if p:
                    sport_counts[p.sport] += 1

        sport_data = [{'sport': k, 'count': v}
                      for k, v in sport_counts.most_common()]

        return render_template('analytics.html',
                               requirements=requirements,
                               total_interests=total_interests,
                               req_interest_data=req_interest_data,
                               sport_data=sport_data)


# ─────────────────────────────────────────────
#  🎯 Player Comparison
# ─────────────────────────────────────────────
@app.route('/compare')
@login_required
def compare_players():
    p1_id = request.args.get('p1', type=int)
    p2_id = request.args.get('p2', type=int)

    all_players = PlayerProfile.query.all()
    p1 = PlayerProfile.query.get(p1_id) if p1_id else None
    p2 = PlayerProfile.query.get(p2_id) if p2_id else None

    comparison = None
    if p1 and p2 and p1.id != p2.id:
        # Build comparison data
        p1_skills = set(p1.skills_list())
        p2_skills = set(p2.skills_list())

        comparison = {
            'common_skills':   list(p1_skills & p2_skills),
            'p1_unique_skills': list(p1_skills - p2_skills),
            'p2_unique_skills': list(p2_skills - p1_skills),
            'p1_score': (
                p1.avg_rating() * 20 +
                min(p1.experience_years * 5, 50) +
                min(len(p1.skills_list()) * 3, 30)
            ),
            'p2_score': (
                p2.avg_rating() * 20 +
                min(p2.experience_years * 5, 50) +
                min(len(p2.skills_list()) * 3, 30)
            ),
        }

    return render_template('compare.html',
                           all_players=all_players,
                           p1=p1, p2=p2,
                           comparison=comparison)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os
from werkzeug.utils import secure_filename

# ---------------- APP CONFIG ----------------
app = Flask(__name__)
app.secret_key = "sportslink_secret"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------------- DATABASE ----------------
def get_db():
    return sqlite3.connect("instance/sports.db")

# ---------------- HOME ----------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                (
                    request.form["name"],
                    request.form["email"],
                    request.form["password"],
                    request.form["role"],
                ),
            )
            db.commit()
            flash("Account created successfully", "success")
            return redirect("/login")
        except sqlite3.IntegrityError:
            flash("Email already exists", "error")

    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email=? AND password=?",
            (request.form["email"], request.form["password"]),
        ).fetchone()

        if user:
            session["user_id"] = user[0]
            session["role"] = user[4]

            if user[4] == "player":
                return redirect("/profile")
            else:
                return redirect("/team")

        flash("Invalid email or password", "error")

    return render_template("login.html")

# ---------------- PLAYER PROFILE ----------------
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()

    if request.method == "POST":
        photo_name = None

        # Photo upload
        if "photo" in request.files:
            photo = request.files["photo"]
            if photo.filename != "":
                photo_name = secure_filename(photo.filename)
                photo.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_name))

        # Replace profile
        db.execute("DELETE FROM player_profiles WHERE user_id=?", (session["user_id"],))
        db.execute(
            """
            INSERT INTO player_profiles
            (user_id, sport, role, description, location, skills, photo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                request.form["sport"],
                request.form["role"],
                request.form["description"],
                request.form["location"],
                request.form["skills"],
                photo_name,
            ),
        )
        db.commit()

    profile = db.execute(
        "SELECT * FROM player_profiles WHERE user_id=?",
        (session["user_id"],),
    ).fetchone()

    return render_template("player_profile.html", profile=profile)

# ---------------- SEARCH PLAYERS ----------------
@app.route("/search")
def search_players():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    players = db.execute(
        """
        SELECT users.id, users.name,
               player_profiles.role,
               player_profiles.description,
               player_profiles.location
        FROM users
        JOIN player_profiles ON users.id = player_profiles.user_id
        """
    ).fetchall()

    return render_template("search_players.html", players=players)

# ---------------- CONNECT ----------------
@app.route("/connect/<int:pid>")
def connect(pid):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    db.execute(
        "INSERT INTO connections (sender_id, receiver_id, status) VALUES (?, ?, ?)",
        (session["user_id"], pid, "pending"),
    )
    db.commit()

    return redirect("/connections")

# ---------------- CONNECTIONS ----------------
@app.route("/connections")
def connections():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    conns = db.execute(
        """
        SELECT users.name, connections.status
        FROM connections
        JOIN users ON users.id = connections.sender_id
        WHERE connections.receiver_id=?
        """,
        (session["user_id"],),
    ).fetchall()

    return render_template("connections.html", conns=conns)

# ---------------- TEAM DASHBOARD ----------------
@app.route("/team", methods=["GET", "POST"])
def team_dashboard():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO team_requirements (team_id, role_needed, location) VALUES (?, ?, ?)",
            (
                session["user_id"],
                request.form["role"],
                request.form["location"],
            ),
        )
        db.commit()
        return redirect("/matches")

    return render_template("post_requirement.html")

# ---------------- MATCHED PLAYERS ----------------
@app.route("/matches")
def matches():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    players = db.execute("SELECT * FROM player_profiles").fetchall()

    return render_template("matched_players.html", players=players)

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- RUN SERVER ----------------
if __name__ == "__main__":
    app.run(debug=True)
