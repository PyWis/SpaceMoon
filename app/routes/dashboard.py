from flask import Blueprint, render_template, jsonify
from app.extensions import db
from app.models import GameSession, MISSION_PHASES

dashboard_bp = Blueprint('dashboard', __name__)


def _active_session():
    return GameSession.query.filter(
        GameSession.state != 'ended'
    ).order_by(GameSession.created_at.desc()).first()


@dashboard_bp.route('/')
def lim():
    s = _active_session()
    return render_template('dashboard/lim.html', session=s,
                           mission_phases=MISSION_PHASES)


@dashboard_bp.route('/api/state')
def api_state():
    s = _active_session()
    if not s:
        return jsonify({'state': 'none'})
    data = s.to_dict()
    data['teams']     = [t.to_dict() for t in s.teams]
    data['alliances'] = [a.to_dict() for a in s.alliances]
    return jsonify(data)
