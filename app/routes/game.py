from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db, socketio
from app.models import (GameSession, RoundAssignment, Answer, Question,
                        MISSION_PHASES, ROLES)
from app.utils.scoring import calculate_points
from flask_socketio import join_room, leave_room

game_bp = Blueprint('game', __name__)


def _get_session():
    if current_user.session_id:
        return db.session.get(GameSession, current_user.session_id)
    return GameSession.query.filter(
        GameSession.state != 'ended'
    ).order_by(GameSession.created_at.desc()).first()


@game_bp.route('/')
@login_required
def player():
    if current_user.is_superadmin:
        return redirect(url_for('admin.index'))
    gs = _get_session()
    if not gs:
        return render_template('game/waiting.html', message='Nessuna sessione di gioco attiva.')

    team = current_user.team
    phase_info = None
    if team and team.launched and 0 <= team.phase < len(MISSION_PHASES):
        phase_info = MISSION_PHASES[team.phase]

    # Current round assignment
    assignment = None
    question   = None
    answer     = None
    time_left  = 0

    if gs.round_active and gs.round_start_time:
        assignment = RoundAssignment.query.filter_by(
            session_id=gs.id,
            round_number=gs.current_round,
            user_id=current_user.id,
        ).first()
        if assignment:
            question = db.session.get(Question, assignment.question_id)
            answer   = Answer.query.filter_by(
                user_id=current_user.id,
                round_number=gs.current_round,
            ).first()
            elapsed   = (datetime.utcnow() - gs.round_start_time).total_seconds()
            time_left = max(0, gs.round_duration - elapsed)

    return render_template('game/player.html',
                           gs=gs,
                           team=team,
                           phase_info=phase_info,
                           assignment=assignment,
                           question=question,
                           answer=answer,
                           time_left=int(time_left),
                           roles=ROLES)


@game_bp.route('/answer', methods=['POST'])
@login_required
def submit_answer():
    if current_user.is_superadmin:
        return jsonify({'error': 'admins cannot answer'}), 400

    gs = _get_session()
    if not gs or not gs.round_active:
        return jsonify({'error': 'No active round'}), 400

    assignment = RoundAssignment.query.filter_by(
        session_id=gs.id,
        round_number=gs.current_round,
        user_id=current_user.id,
    ).first()
    if not assignment:
        return jsonify({'error': 'No question assigned'}), 400

    existing = Answer.query.filter_by(
        user_id=current_user.id,
        round_number=gs.current_round,
    ).first()
    if existing:
        return jsonify({'error': 'Already answered'}), 400

    data        = request.get_json() or {}
    answer_idx  = data.get('answer')
    client_time = data.get('time_taken')  # seconds from client

    # Server-side time calculation
    elapsed = (datetime.utcnow() - gs.round_start_time).total_seconds()
    time_taken = min(elapsed, gs.round_duration + 1)

    q = db.session.get(Question, assignment.question_id)
    is_correct = (answer_idx is not None and answer_idx == q.correct_answer
                  and time_taken <= gs.round_duration)
    points = calculate_points(time_taken, is_correct)

    ans = Answer(
        user_id=current_user.id,
        question_id=q.id,
        round_number=gs.current_round,
        answer_given=answer_idx,
        is_correct=is_correct,
        time_taken=time_taken,
        points_earned=points,
    )
    db.session.add(ans)
    db.session.commit()

    # Notify admin of new answer
    socketio.emit('player_answered', {
        'user_id':   current_user.id,
        'display':   current_user.display_name,
        'team':      current_user.team.name if current_user.team else '?',
        'correct':   is_correct,
        'points':    points,
        'time_taken':round(time_taken, 1),
    }, room='admin_room')

    return jsonify({
        'correct':    is_correct,
        'points':     points,
        'correct_idx':q.correct_answer,
        'time_taken': round(time_taken, 1),
    })


@game_bp.route('/api/state')
@login_required
def api_state():
    gs   = _get_session()
    team = current_user.team
    if not gs:
        return jsonify({'state': 'none'})

    data = gs.to_dict()
    if team:
        data['my_team'] = team.to_dict()

    answered = False
    if gs.round_active:
        ans = Answer.query.filter_by(
            user_id=current_user.id,
            round_number=gs.current_round,
        ).first()
        answered = ans is not None
    data['answered'] = answered
    return jsonify(data)


# ─── SocketIO ─────────────────────────────────────────────────────────────────

@socketio.on('join')
def handle_join(data):
    join_room('game_room')
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        if current_user.is_superadmin:
            join_room('admin_room')


@socketio.on('disconnect')
def handle_disconnect():
    leave_room('game_room')
    if current_user.is_authenticated:
        leave_room(f'user_{current_user.id}')
