from datetime import datetime
import json
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager

AGENCIES = {
    'nasa':      {'name': 'NASA',      'flag': '🇺🇸', 'color': '#0B3D91'},
    'esa':       {'name': 'ESA',       'flag': '🇪🇺', 'color': '#003399'},
    'roscosmos': {'name': 'ROSCOSMOS', 'flag': '🇷🇺', 'color': '#CC0000'},
    'jaxa':      {'name': 'JAXA',      'flag': '🇯🇵', 'color': '#BC002D'},
    'csa':       {'name': 'CSA',       'flag': '🇨🇦', 'color': '#FF0000'},
    'cnsa':      {'name': 'CNSA',      'flag': '🇨🇳', 'color': '#EE1C25'},
    'asi':       {'name': 'ASI',       'flag': '🇮🇹', 'color': '#009246'},
    'cnes':      {'name': 'CNES',      'flag': '🇫🇷', 'color': '#0055A4'},
}

ROLES = {
    'capo_progetto':    'Capo Progetto',
    'capo_ingegnere':   'Capo Ingegnere',
    'direttore_lancio': 'Direttore di Lancio',
    'capcom':           'Capcom',
    'astronauta':       'Astronauta',
}

MISSION_PHASES = [
    {'phase': 0, 'name': 'Prelancio',            'emoji': '🛰️'},
    {'phase': 1, 'name': 'Lancio effettuato',     'emoji': '🔥'},
    {'phase': 2, 'name': 'Verso la Luna',         'emoji': '🌌'},
    {'phase': 3, 'name': 'Arrivo sulla Luna',     'emoji': '🌕'},
    {'phase': 4, 'name': 'Ritorno a casa',        'emoji': '🌍'},
    {'phase': 5, 'name': 'Ammaraggio',            'emoji': '🌊'},
]


class GameSession(db.Model):
    __tablename__ = 'game_sessions'

    id                   = db.Column(db.Integer, primary_key=True)
    state                = db.Column(db.String(20), default='setup')
    # phase_a → Saturn V building; phase_b → mission; apollo_soyuz; ended
    level_threshold      = db.Column(db.Integer, default=100)
    saturn_v_target      = db.Column(db.Integer, default=200)
    apollo_soyuz_target  = db.Column(db.Integer, default=500)
    apollo_soyuz_points  = db.Column(db.Integer, default=0)
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)
    current_round        = db.Column(db.Integer, default=0)
    round_active         = db.Column(db.Boolean, default=False)
    round_start_time     = db.Column(db.DateTime)
    round_duration       = db.Column(db.Integer, default=60)  # seconds

    teams     = db.relationship('Team',     backref='session', lazy=True)
    questions = db.relationship('Question', backref='session', lazy=True)
    users     = db.relationship('User',     backref='session', lazy=True)
    alliances = db.relationship('Alliance', backref='session', lazy=True)
    bonuses   = db.relationship('BonusLog', backref='session', lazy=True)

    @property
    def finished_teams_count(self):
        return sum(1 for t in self.teams if t.phase >= 5 and t.launched)

    def to_dict(self):
        return {
            'id':                  self.id,
            'state':               self.state,
            'level_threshold':     self.level_threshold,
            'saturn_v_target':     self.saturn_v_target,
            'apollo_soyuz_target': self.apollo_soyuz_target,
            'apollo_soyuz_points': self.apollo_soyuz_points,
            'current_round':       self.current_round,
            'round_active':        self.round_active,
            'round_start_time':    self.round_start_time.isoformat() if self.round_start_time else None,
            'round_duration':      self.round_duration,
            'finished_teams':      self.finished_teams_count,
        }


class Alliance(db.Model):
    __tablename__ = 'alliances'

    id                 = db.Column(db.Integer, primary_key=True)
    session_id         = db.Column(db.Integer, db.ForeignKey('game_sessions.id'), nullable=False)
    phase              = db.Column(db.Integer, default=-1)  # mirrors team phase
    phase_entry_pooled = db.Column(db.Integer, default=0)   # combined points at phase start

    teams = db.relationship('Team', backref='alliance', lazy=True)

    @property
    def combined_points(self):
        return sum(t.total_points for t in self.teams)

    @property
    def current_phase_progress(self):
        return self.combined_points - self.phase_entry_pooled

    def advance_cost(self, base_cost):
        n = len(self.teams)
        return base_cost * (2 ** (n - 1)) if n > 0 else base_cost

    def to_dict(self):
        return {
            'id':                    self.id,
            'team_ids':              [t.id for t in self.teams],
            'team_names':            [t.name for t in self.teams],
            'combined_points':       self.combined_points,
            'current_phase_progress':self.current_phase_progress,
            'phase':                 self.phase,
        }


class Team(db.Model):
    __tablename__ = 'teams'

    id                = db.Column(db.Integer, primary_key=True)
    agency_code       = db.Column(db.String(10), nullable=False)
    session_id        = db.Column(db.Integer, db.ForeignKey('game_sessions.id'), nullable=False)
    alliance_id       = db.Column(db.Integer, db.ForeignKey('alliances.id'))
    total_points      = db.Column(db.Integer, default=0)
    phase             = db.Column(db.Integer, default=-1)  # -1=Phase A, 0-5=mission
    launched          = db.Column(db.Boolean, default=False)
    phase_entry_points= db.Column(db.Integer, default=0)  # total_points when phase started

    members   = db.relationship('User',      backref='team',     lazy=True)
    bonus_logs= db.relationship('BonusLog',  backref='team',     lazy=True)

    @property
    def agency_info(self):
        return AGENCIES.get(self.agency_code, {})

    @property
    def name(self):
        return self.agency_info.get('name', self.agency_code.upper())

    @property
    def flag(self):
        return self.agency_info.get('flag', '🚀')

    @property
    def color(self):
        return self.agency_info.get('color', '#444444')

    @property
    def member_count(self):
        return len(self.members)

    @property
    def capcom_count(self):
        return 2 if self.member_count >= 8 else 1

    @property
    def current_phase_points(self):
        """Points accumulated since entering the current phase."""
        return self.total_points - self.phase_entry_points

    @property
    def saturn_progress(self):
        """Returns 0-100 percentage of Saturn V completion (Phase A)."""
        if not self.session:
            return 0
        target = self.session.saturn_v_target
        return min(100, int(self.total_points * 100 / target)) if target else 0

    @property
    def can_launch(self):
        if self.launched:
            return False
        if not self.session:
            return False
        return self.total_points >= self.session.saturn_v_target

    def to_dict(self):
        return {
            'id':                  self.id,
            'agency_code':         self.agency_code,
            'name':                self.name,
            'flag':                self.flag,
            'color':               self.color,
            'total_points':        self.total_points,
            'phase':               self.phase,
            'launched':            self.launched,
            'current_phase_points':self.current_phase_points,
            'saturn_progress':     self.saturn_progress,
            'can_launch':          self.can_launch,
            'member_count':        self.member_count,
            'alliance_id':         self.alliance_id,
        }


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    display_name  = db.Column(db.String(100))
    is_superadmin = db.Column(db.Boolean, default=False)
    team_id       = db.Column(db.Integer, db.ForeignKey('teams.id'))
    role          = db.Column(db.String(30))
    session_id    = db.Column(db.Integer, db.ForeignKey('game_sessions.id'))

    answers      = db.relationship('Answer',          backref='user', lazy=True)
    assignments  = db.relationship('RoundAssignment', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_display(self):
        return ROLES.get(self.role, self.role or '')

    @property
    def total_personal_points(self):
        return sum(a.points_earned for a in self.answers if a.points_earned)

    def to_dict(self):
        return {
            'id':           self.id,
            'username':     self.username,
            'display_name': self.display_name,
            'role':         self.role,
            'role_display': self.role_display,
            'team_id':      self.team_id,
        }


class Question(db.Model):
    __tablename__ = 'questions'

    id             = db.Column(db.Integer, primary_key=True)
    text           = db.Column(db.Text, nullable=False)
    options_json   = db.Column(db.Text, nullable=False)
    correct_answer = db.Column(db.Integer, nullable=False)  # 0-indexed
    bonus_role     = db.Column(db.String(30))
    session_id     = db.Column(db.Integer, db.ForeignKey('game_sessions.id'))

    answers     = db.relationship('Answer',          backref='question', lazy=True)
    assignments = db.relationship('RoundAssignment', backref='question', lazy=True)

    @property
    def options(self):
        return json.loads(self.options_json) if self.options_json else []

    @options.setter
    def options(self, value):
        self.options_json = json.dumps(value)

    def to_dict(self, reveal=False):
        d = {
            'id':        self.id,
            'text':      self.text,
            'options':   self.options,
            'bonus_role':self.bonus_role,
        }
        if reveal:
            d['correct_answer'] = self.correct_answer
        return d


class RoundAssignment(db.Model):
    __tablename__ = 'round_assignments'

    id            = db.Column(db.Integer, primary_key=True)
    session_id    = db.Column(db.Integer, db.ForeignKey('game_sessions.id'))
    round_number  = db.Column(db.Integer)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'))
    question_id   = db.Column(db.Integer, db.ForeignKey('questions.id'))


class Answer(db.Model):
    __tablename__ = 'answers'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'),     nullable=False)
    question_id  = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    round_number = db.Column(db.Integer)
    answer_given = db.Column(db.Integer)
    is_correct   = db.Column(db.Boolean, default=False)
    time_taken   = db.Column(db.Float)
    points_earned= db.Column(db.Integer, default=0)
    answered_at  = db.Column(db.DateTime, default=datetime.utcnow)


class BonusLog(db.Model):
    __tablename__ = 'bonus_logs'

    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('game_sessions.id'))
    team_id      = db.Column(db.Integer, db.ForeignKey('teams.id'))
    round_number = db.Column(db.Integer)
    bonus_type   = db.Column(db.String(30))  # en_plein | role_bonus
    points       = db.Column(db.Integer, default=10)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
