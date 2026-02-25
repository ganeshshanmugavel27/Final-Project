from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(80),  unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(256), nullable=False)
    role       = db.Column(db.String(10),  nullable=False)
    avatar     = db.Column(db.String(200), default='default.png')
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

    player_profile = db.relationship('PlayerProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    requirements   = db.relationship('TeamRequirement', backref='user', cascade='all, delete-orphan')
    sent_messages  = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)
    recv_messages  = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy=True)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class PlayerProfile(db.Model):
    __tablename__ = 'player_profiles'

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    sport            = db.Column(db.String(50),  nullable=False)
    position         = db.Column(db.String(50),  nullable=False)
    skills           = db.Column(db.Text,        nullable=False)
    experience_years = db.Column(db.Integer,     default=0)
    bio              = db.Column(db.Text,        default='')
    location         = db.Column(db.String(100), default='')
    profile_views    = db.Column(db.Integer,     default=0)  # NEW: track views
    updated_at       = db.Column(db.DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    achievements = db.relationship('Achievement', backref='player', cascade='all, delete-orphan')
    ratings      = db.relationship('PlayerRating', backref='player', cascade='all, delete-orphan')

    def skills_list(self):
        return [s.strip() for s in self.skills.split(',') if s.strip()]

    def avg_rating(self):
        if not self.ratings:
            return 0
        return round(sum(r.rating for r in self.ratings) / len(self.ratings), 1)

    def __repr__(self):
        return f'<PlayerProfile {self.user.username} - {self.sport}>'


class TeamRequirement(db.Model):
    __tablename__ = 'team_requirements'

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    team_name        = db.Column(db.String(100), nullable=False)
    sport            = db.Column(db.String(50),  nullable=False)
    position         = db.Column(db.String(50),  nullable=False)
    skills_required  = db.Column(db.Text,        nullable=False)
    min_experience   = db.Column(db.Integer,     default=0)
    description      = db.Column(db.Text,        default='')
    location         = db.Column(db.String(100), default='')
    posted_at        = db.Column(db.DateTime,    default=datetime.utcnow)

    def skills_list(self):
        return [s.strip() for s in self.skills_required.split(',') if s.strip()]

    def __repr__(self):
        return f'<TeamRequirement {self.team_name} - {self.position}>'


class Interest(db.Model):
    __tablename__ = 'interests'

    id             = db.Column(db.Integer, primary_key=True)
    player_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey('team_requirements.id'), nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    player      = db.relationship('User', backref='interests')
    requirement = db.relationship('TeamRequirement', backref='interests')

    __table_args__ = (db.UniqueConstraint('player_id', 'requirement_id'),)


class Message(db.Model):
    __tablename__ = 'messages'

    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body        = db.Column(db.Text,    nullable=False)
    is_read     = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


class Achievement(db.Model):
    __tablename__ = 'achievements'

    id          = db.Column(db.Integer, primary_key=True)
    player_id   = db.Column(db.Integer, db.ForeignKey('player_profiles.id'), nullable=False)
    title       = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text,        default='')
    badge_icon  = db.Column(db.String(10),  default='🏅')
    date_earned = db.Column(db.String(20),  default='')
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow)


class PlayerRating(db.Model):
    """Teams rate players — used for leaderboard"""
    __tablename__ = 'player_ratings'

    id         = db.Column(db.Integer, primary_key=True)
    player_id  = db.Column(db.Integer, db.ForeignKey('player_profiles.id'), nullable=False)
    rater_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating     = db.Column(db.Integer, nullable=False)   # 1-5 stars
    review     = db.Column(db.Text,    default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rater = db.relationship('User', backref='given_ratings')

    # One team can rate a player only once
    __table_args__ = (db.UniqueConstraint('player_id', 'rater_id'),)


class ProfileView(db.Model):
    """Track who viewed which profile — for analytics"""
    __tablename__ = 'profile_views'

    id         = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('player_profiles.id'), nullable=False)
    viewer_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    viewed_at  = db.Column(db.DateTime, default=datetime.utcnow)