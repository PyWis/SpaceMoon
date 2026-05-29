import random
import string
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify)
from flask_login import login_required, current_user
from app.extensions import db, socketio
from app.models import (GameSession, Team, User, Question, RoundAssignment,
                        Answer, Alliance, BonusLog, AGENCIES, ROLES,
                        MISSION_PHASES)
from app.utils.csv_parser import parse_questions_csv
from app.utils.scoring import calculate_points, calculate_team_bonuses

admin_bp = Blueprint('admin', __name__)


def superadmin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            flash('Accesso riservato al Superadmin.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def _active_session():
    return GameSession.query.filter(
        GameSession.state != 'ended'
    ).order_by(GameSession.created_at.desc()).first()


def _broadcast_state(session):
    """Emit full game state to all connected clients."""
    data = session.to_dict()
    data['teams'] = [t.to_dict() for t in session.teams]
    data['alliances'] = [a.to_dict() for a in session.alliances]
    socketio.emit('game_state', data, room='game_room')


# ─── Dashboard ───────────────────────────────────────────────────────────────

@admin_bp.route('/')
@login_required
@superadmin_required
def index():
    session = _active_session()
    sessions = GameSession.query.order_by(GameSession.created_at.desc()).limit(5).all()
    return render_template('admin/index.html', session=session, sessions=sessions)


# ─── Session management ───────────────────────────────────────────────────────

@admin_bp.route('/session/new', methods=['GET', 'POST'])
@login_required
@superadmin_required
def new_session():
    if request.method == 'POST':
        s = GameSession(
            level_threshold=int(request.form.get('level_threshold', 100)),
            saturn_v_target=int(request.form.get('saturn_v_target', 200)),
            apollo_soyuz_target=int(request.form.get('apollo_soyuz_target', 500)),
            round_duration=int(request.form.get('round_duration', 60)),
        )
        db.session.add(s)
        db.session.commit()
        flash('Sessione creata!', 'success')
        return redirect(url_for('admin.manage_teams', session_id=s.id))
    return render_template('admin/new_session.html')


@admin_bp.route('/session/<int:session_id>/settings', methods=['GET', 'POST'])
@login_required
@superadmin_required
def session_settings(session_id):
    s = db.get_or_404(GameSession, session_id)
    if request.method == 'POST':
        s.level_threshold    = int(request.form.get('level_threshold', s.level_threshold))
        s.saturn_v_target    = int(request.form.get('saturn_v_target', s.saturn_v_target))
        s.apollo_soyuz_target= int(request.form.get('apollo_soyuz_target', s.apollo_soyuz_target))
        s.round_duration     = int(request.form.get('round_duration', s.round_duration))
        db.session.commit()
        flash('Impostazioni aggiornate.', 'success')
    return render_template('admin/session_settings.html', session=s)


# ─── Team management ─────────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/teams', methods=['GET', 'POST'])
@login_required
@superadmin_required
def manage_teams(session_id):
    s = db.get_or_404(GameSession, session_id)
    if request.method == 'POST':
        selected = request.form.getlist('agencies')
        if len(selected) < 2 or len(selected) > 6:
            flash('Seleziona da 2 a 6 squadre.', 'danger')
        else:
            # Remove teams not in selection
            for team in list(s.teams):
                if team.agency_code not in selected:
                    db.session.delete(team)
            existing = {t.agency_code for t in s.teams}
            for code in selected:
                if code not in existing:
                    db.session.add(Team(agency_code=code, session_id=s.id))
            db.session.commit()
            flash('Squadre aggiornate!', 'success')
            return redirect(url_for('admin.manage_users', session_id=s.id))
    return render_template('admin/teams.html', session=s, agencies=AGENCIES)


# ─── User management ─────────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/users', methods=['GET', 'POST'])
@login_required
@superadmin_required
def manage_users(session_id):
    s = db.get_or_404(GameSession, session_id)
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            display = request.form.get('display_name', '').strip()
            team_id = request.form.get('team_id') or None
            role    = request.form.get('role') or None

            # Auto-generate username and password
            username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            while User.query.filter_by(username=username).first():
                username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

            u = User(
                username=username,
                display_name=display or username,
                session_id=s.id,
                team_id=int(team_id) if team_id else None,
                role=role,
            )
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash(f'Utente creato: {username} / {password}', 'success')

        elif action == 'delete':
            uid = request.form.get('user_id')
            u = db.session.get(User, int(uid))
            if u and not u.is_superadmin:
                db.session.delete(u)
                db.session.commit()
                flash('Utente eliminato.', 'success')

        elif action == 'update':
            uid = int(request.form.get('user_id'))
            u = db.session.get(User, uid)
            if u:
                u.display_name = request.form.get('display_name', u.display_name)
                u.team_id = int(request.form.get('team_id')) if request.form.get('team_id') else None
                u.role    = request.form.get('role') or None
                db.session.commit()
                flash('Utente aggiornato.', 'success')

        return redirect(url_for('admin.manage_users', session_id=s.id))

    players = User.query.filter_by(session_id=s.id, is_superadmin=False).all()
    return render_template('admin/users.html', session=s, players=players, roles=ROLES)


@admin_bp.route('/session/<int:session_id>/users/bulk', methods=['POST'])
@login_required
@superadmin_required
def bulk_create_users(session_id):
    s = db.get_or_404(GameSession, session_id)
    count = int(request.form.get('count', 1))
    team_id = request.form.get('team_id') or None
    role    = request.form.get('role') or None
    prefix  = request.form.get('prefix', 'studente').strip()

    created = []
    for i in range(count):
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        while User.query.filter_by(username=username).first():
            username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

        u = User(
            username=username,
            display_name=f'{prefix}{i+1}',
            session_id=s.id,
            team_id=int(team_id) if team_id else None,
            role=role,
        )
        u.set_password(password)
        db.session.add(u)
        created.append({'display_name': u.display_name,
                        'username': username, 'password': password})

    db.session.commit()
    flash(f'{count} utenti creati.', 'success')
    return render_template('admin/bulk_created.html', session=s, created=created)


# ─── Question management ──────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/questions', methods=['GET', 'POST'])
@login_required
@superadmin_required
def manage_questions(session_id):
    s = db.get_or_404(GameSession, session_id)
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            text    = request.form.get('text', '').strip()
            options = [request.form.get(f'option_{i}', '').strip() for i in range(1, 6)]
            options = [o for o in options if o]
            correct = int(request.form.get('correct', 0))
            brole   = request.form.get('bonus_role') or None

            if text and len(options) >= 3 and 0 <= correct < len(options):
                q = Question(text=text, correct_answer=correct,
                             bonus_role=brole, session_id=s.id)
                q.options = options
                db.session.add(q)
                db.session.commit()
                flash('Domanda aggiunta!', 'success')
            else:
                flash('Dati domanda non validi.', 'danger')

        elif action == 'delete':
            qid = request.form.get('question_id')
            q = db.session.get(Question, int(qid))
            if q and q.session_id == s.id:
                db.session.delete(q)
                db.session.commit()
                flash('Domanda eliminata.', 'success')

        return redirect(url_for('admin.manage_questions', session_id=s.id))

    questions = Question.query.filter_by(session_id=s.id).all()
    return render_template('admin/questions.html', session=s, questions=questions, roles=ROLES)


@admin_bp.route('/session/<int:session_id>/questions/import', methods=['POST'])
@login_required
@superadmin_required
def import_questions(session_id):
    s = db.get_or_404(GameSession, session_id)
    f = request.files.get('csv_file')
    if not f or not f.filename.endswith('.csv'):
        flash('Carica un file CSV valido.', 'danger')
        return redirect(url_for('admin.manage_questions', session_id=s.id))

    content = f.read().decode('utf-8-sig')
    parsed  = parse_questions_csv(content)
    if not parsed:
        flash('Nessuna domanda valida trovata nel CSV.', 'danger')
        return redirect(url_for('admin.manage_questions', session_id=s.id))

    for qd in parsed:
        q = Question(
            text=qd['text'],
            correct_answer=qd['correct_answer'],
            bonus_role=qd['bonus_role'],
            session_id=s.id,
        )
        q.options = qd['options']
        db.session.add(q)
    db.session.commit()
    flash(f'{len(parsed)} domande importate!', 'success')
    return redirect(url_for('admin.manage_questions', session_id=s.id))


# ─── Game Control ─────────────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/control')
@login_required
@superadmin_required
def game_control(session_id):
    s = db.get_or_404(GameSession, session_id)
    players = User.query.filter_by(session_id=s.id, is_superadmin=False).all()
    questions_count = Question.query.filter_by(session_id=s.id).count()
    time_left = 0
    if s.round_active and s.round_start_time:
        elapsed = (datetime.utcnow() - s.round_start_time).total_seconds()
        time_left = int(max(0, s.round_duration - elapsed))
    return render_template('admin/game_control.html', session=s,
                           players=players, questions_count=questions_count,
                           mission_phases=MISSION_PHASES, time_left=time_left)


@admin_bp.route('/session/<int:session_id>/start', methods=['POST'])
@login_required
@superadmin_required
def start_game(session_id):
    s = db.get_or_404(GameSession, session_id)
    if s.state != 'setup':
        flash('Il gioco è già avviato.', 'warning')
        return redirect(url_for('admin.game_control', session_id=s.id))
    if len(s.teams) < 2:
        flash('Servono almeno 2 squadre.', 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))
    if Question.query.filter_by(session_id=s.id).count() == 0:
        flash('Aggiungi almeno una domanda prima di iniziare.', 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))

    s.state = 'phase_a'
    db.session.commit()
    _broadcast_state(s)
    flash('Fase A avviata — Costruzione Saturn V!', 'success')
    return redirect(url_for('admin.game_control', session_id=s.id))


@admin_bp.route('/session/<int:session_id>/round/start', methods=['POST'])
@login_required
@superadmin_required
def start_round(session_id):
    s = db.get_or_404(GameSession, session_id)
    if s.state not in ('phase_a', 'phase_b', 'apollo_soyuz'):
        flash('Impossibile avviare un round ora.', 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))
    if s.round_active:
        flash('Un round è già in corso.', 'warning')
        return redirect(url_for('admin.game_control', session_id=s.id))

    players = User.query.filter_by(session_id=s.id, is_superadmin=False).all()
    if not players:
        flash('Nessun giocatore registrato.', 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))

    questions = Question.query.filter_by(session_id=s.id).all()
    if not questions:
        flash('Nessuna domanda disponibile.', 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))

    s.current_round += 1
    s.round_active = True
    s.round_start_time = datetime.utcnow()
    db.session.flush()

    # Assign random questions — teammates get different questions when possible
    q_pool = list(questions)
    random.shuffle(q_pool)

    team_assigned: dict[int, set] = {}  # team_id → set of question_ids already assigned
    for player in players:
        team_assigned.setdefault(player.team_id, set())

    for player in players:
        tid = player.team_id
        # Prefer questions not yet assigned to this team in this round
        preferred = [q for q in q_pool if q.id not in team_assigned[tid]]
        pick = random.choice(preferred if preferred else q_pool)
        team_assigned[tid].add(pick.id)

        ra = RoundAssignment(
            session_id=s.id,
            round_number=s.current_round,
            user_id=player.id,
            question_id=pick.id,
        )
        db.session.add(ra)

    db.session.commit()

    # Broadcast round start with per-player question data
    round_end_time = s.round_start_time.timestamp() + s.round_duration
    socketio.emit('round_start', {
        'round': s.current_round,
        'end_time': round_end_time,
        'duration': s.round_duration,
    }, room='game_room')

    # Push personalised question to each connected player
    assignments = RoundAssignment.query.filter_by(
        session_id=s.id, round_number=s.current_round
    ).all()
    for ra in assignments:
        q = db.session.get(Question, ra.question_id)
        socketio.emit('your_question', {
            'round': s.current_round,
            'question': q.to_dict(),
            'end_time': round_end_time,
        }, room=f'user_{ra.user_id}')

    flash(f'Round {s.current_round} avviato!', 'success')
    return redirect(url_for('admin.game_control', session_id=s.id))


@admin_bp.route('/session/<int:session_id>/round/end', methods=['POST'])
@login_required
@superadmin_required
def end_round(session_id):
    s = db.get_or_404(GameSession, session_id)
    if not s.round_active:
        flash('Nessun round attivo.', 'warning')
        return redirect(url_for('admin.game_control', session_id=s.id))

    s.round_active = False
    db.session.flush()

    # Process bonuses and phase advancement
    round_results = _process_round_end(s)

    db.session.commit()

    socketio.emit('round_end', round_results, room='game_room')
    _broadcast_state(s)

    flash(f'Round {s.current_round} concluso!', 'success')
    return redirect(url_for('admin.game_control', session_id=s.id))


def _process_round_end(session):
    """Calculate bonuses, update team points, check phase transitions."""
    results = {
        'round': session.current_round,
        'team_results': [],
        'bonuses': [],
    }

    now = datetime.utcnow()

    for team in session.teams:
        members = [m for m in team.members if not m.is_superadmin]
        team_round_points = 0

        # Award points to players who didn't answer (0 pts, timed out)
        assignments = RoundAssignment.query.filter_by(
            session_id=session.id,
            round_number=session.current_round,
        ).filter(RoundAssignment.user_id.in_([m.id for m in members])).all()

        for ra in assignments:
            existing = Answer.query.filter_by(
                user_id=ra.user_id,
                round_number=session.current_round,
            ).first()
            if not existing:
                # Timed out — record 0-point answer
                a = Answer(
                    user_id=ra.user_id,
                    question_id=ra.question_id,
                    round_number=session.current_round,
                    answer_given=None,
                    is_correct=False,
                    time_taken=session.round_duration + 1,
                    points_earned=0,
                )
                db.session.add(a)
            else:
                team_round_points += existing.points_earned

        # Bonuses
        bonuses = calculate_team_bonuses(session, team, session.current_round)
        for btype, bpts in bonuses:
            team_round_points += bpts
            log = BonusLog(
                session_id=session.id,
                team_id=team.id,
                round_number=session.current_round,
                bonus_type=btype,
                points=bpts,
            )
            db.session.add(log)
            results['bonuses'].append({'team': team.name, 'type': btype, 'pts': bpts})

        team.total_points += team_round_points

        # Apollo-Soyuz: points go to shared pool instead
        if session.state == 'apollo_soyuz':
            session.apollo_soyuz_points += team_round_points
            team.total_points -= team_round_points  # don't double-count
            if session.apollo_soyuz_points >= session.apollo_soyuz_target:
                session.state = 'ended'
                socketio.emit('game_won', {
                    'message': 'La Missione Apollo-Soyuz è completata! La classe ha vinto!'
                }, room='game_room')

        # Phase advancement (Phase B only)
        if team.launched and session.state == 'phase_b' and team.phase < 5:
            _check_phase_advance(session, team)

        results['team_results'].append({
            'team_id':   team.id,
            'team_name': team.name,
            'round_pts': team_round_points,
            'total_pts': team.total_points,
            'phase':     team.phase,
        })

    # Check Apollo-Soyuz trigger
    if session.state == 'phase_b':
        finished = sum(1 for t in session.teams if t.phase >= 5)
        if finished >= 2 and session.apollo_soyuz_points == 0:
            session.state = 'apollo_soyuz'
            socketio.emit('apollo_soyuz_start', {
                'target': session.apollo_soyuz_target
            }, room='game_room')

    db.session.flush()
    return results


def _check_phase_advance(session, team):
    if team.alliance_id:
        alliance = db.session.get(Alliance, team.alliance_id)
        if alliance:
            base = (session.saturn_v_target if not team.launched
                    else session.level_threshold)
            cost = alliance.advance_cost(base)
            if alliance.current_phase_progress >= cost:
                # Advance all alliance teams
                for at in alliance.teams:
                    at.phase = min(at.phase + 1, 5)
                    at.phase_entry_points = at.total_points
                alliance.phase += 1
                alliance.phase_entry_pooled = alliance.combined_points
                _announce_phase(session, alliance.teams)
            return

    # Solo team
    if team.current_phase_points >= session.level_threshold:
        team.phase = min(team.phase + 1, 5)
        team.phase_entry_points = team.total_points
        _announce_phase(session, [team])


def _announce_phase(session, teams):
    for team in teams:
        phase_info = MISSION_PHASES[team.phase] if 0 <= team.phase < len(MISSION_PHASES) else {}
        socketio.emit('phase_update', {
            'team_id':   team.id,
            'team_name': team.name,
            'phase':     team.phase,
            'phase_name':phase_info.get('name', ''),
            'emoji':     phase_info.get('emoji', ''),
        }, room='game_room')


# ─── Launch Saturn V ──────────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/team/<int:team_id>/launch', methods=['POST'])
@login_required
@superadmin_required
def launch_team(session_id, team_id):
    s    = db.get_or_404(GameSession, session_id)
    team = db.get_or_404(Team, team_id)

    if team.launched:
        flash(f'{team.name} ha già lanciato!', 'warning')
    elif not team.can_launch:
        flash(f'{team.name} non ha abbastanza punti per il lancio.', 'danger')
    else:
        team.launched = True
        team.phase = 0
        team.phase_entry_points = team.total_points

        if s.state == 'phase_a':
            # Check if at least one team launched → enter phase_b
            s.state = 'phase_b'

        db.session.commit()
        socketio.emit('launch', {'team_id': team.id, 'team_name': team.name},
                      room='game_room')
        _broadcast_state(s)
        flash(f'🚀 {team.name} ha lanciato il Saturn V!', 'success')

    return redirect(url_for('admin.game_control', session_id=s.id))


# ─── Manual phase advance ─────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/team/<int:team_id>/advance', methods=['POST'])
@login_required
@superadmin_required
def advance_team_phase(session_id, team_id):
    s    = db.get_or_404(GameSession, session_id)
    team = db.get_or_404(Team, team_id)

    if not team.launched or team.phase >= 5:
        flash('Impossibile avanzare questa squadra.', 'warning')
    else:
        team.phase += 1
        team.phase_entry_points = team.total_points
        db.session.commit()
        _announce_phase(s, [team])
        _broadcast_state(s)
        flash(f'{team.name} avanzata a Fase {team.phase}!', 'success')

    return redirect(url_for('admin.game_control', session_id=s.id))


# ─── Alliances ────────────────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/alliance/create', methods=['POST'])
@login_required
@superadmin_required
def create_alliance(session_id):
    s = db.get_or_404(GameSession, session_id)
    team_ids = [int(tid) for tid in request.form.getlist('team_ids')]
    if len(team_ids) < 2:
        flash("Seleziona almeno 2 squadre per formare un'alleanza.", 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))

    teams = [db.session.get(Team, tid) for tid in team_ids]
    teams = [t for t in teams if t and not t.launched and t.session_id == s.id]
    if len(teams) < 2:
        flash('Le squadre selezionate non sono idonee.', 'danger')
        return redirect(url_for('admin.game_control', session_id=s.id))

    # Remove existing alliances for these teams
    for t in teams:
        t.alliance_id = None

    alliance = Alliance(
        session_id=s.id,
        phase=-1,
        phase_entry_pooled=sum(t.total_points for t in teams),
    )
    db.session.add(alliance)
    db.session.flush()
    for t in teams:
        t.alliance_id = alliance.id

    db.session.commit()
    socketio.emit('alliance_formed', alliance.to_dict(), room='game_room')
    _broadcast_state(s)
    names = ', '.join(t.name for t in teams)
    flash(f"Alleanza formata: {names}!", 'success')
    return redirect(url_for('admin.game_control', session_id=s.id))


# ─── Apollo-Soyuz manual advance ──────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/apollo-soyuz/add', methods=['POST'])
@login_required
@superadmin_required
def apollo_soyuz_add(session_id):
    s   = db.get_or_404(GameSession, session_id)
    pts = int(request.form.get('points', 0))
    if s.state == 'apollo_soyuz':
        s.apollo_soyuz_points = min(s.apollo_soyuz_target,
                                    s.apollo_soyuz_points + pts)
        db.session.commit()
        socketio.emit('apollo_soyuz_update', {
            'points': s.apollo_soyuz_points,
            'target': s.apollo_soyuz_target,
        }, room='game_room')
    return redirect(url_for('admin.game_control', session_id=s.id))


# ─── API endpoints ────────────────────────────────────────────────────────────

@admin_bp.route('/session/<int:session_id>/api/state')
@login_required
@superadmin_required
def api_state(session_id):
    s = db.get_or_404(GameSession, session_id)
    data = s.to_dict()
    data['teams'] = [t.to_dict() for t in s.teams]
    data['alliances'] = [a.to_dict() for a in s.alliances]
    players = User.query.filter_by(session_id=s.id, is_superadmin=False).all()
    data['answered_count'] = 0
    data['total_players'] = len(players)
    if s.round_active:
        data['answered_count'] = Answer.query.filter_by(
            round_number=s.current_round
        ).filter(Answer.user_id.in_([p.id for p in players])).count()
    return jsonify(data)


@admin_bp.route('/session/<int:session_id>/api/round-answers')
@login_required
@superadmin_required
def api_round_answers(session_id):
    s = db.get_or_404(GameSession, session_id)
    players = User.query.filter_by(session_id=s.id, is_superadmin=False).all()
    pid_set = {p.id for p in players}

    assignments = RoundAssignment.query.filter_by(
        session_id=s.id, round_number=s.current_round
    ).all()

    answers = {
        a.user_id: a for a in
        Answer.query.filter_by(round_number=s.current_round)
        .filter(Answer.user_id.in_(pid_set)).all()
    }

    result = []
    for ra in assignments:
        user = db.session.get(User, ra.user_id)
        ans  = answers.get(ra.user_id)
        result.append({
            'user':       user.display_name if user else '?',
            'team':       user.team.name if user and user.team else '?',
            'answered':   ans is not None,
            'correct':    ans.is_correct if ans else False,
            'points':     ans.points_earned if ans else 0,
            'time_taken': ans.time_taken if ans else None,
        })

    return jsonify({'answers': result,
                    'total': len(result),
                    'answered': sum(1 for r in result if r['answered'])})
