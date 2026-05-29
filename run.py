import os
import secrets
import sqlite3
import string

try:
    import eventlet
    eventlet.monkey_patch()
    _async_mode = 'eventlet'
except ImportError:
    _async_mode = 'threading'

from app import create_app, socketio
from app.extensions import db
from app.models import User

app = create_app(async_mode=_async_mode)


def _migrate_db():
    """Add new columns to existing SQLite DB (idempotent)."""
    db_path = os.path.join(os.path.dirname(__file__), 'spacemoon.db')
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    c    = conn.cursor()
    migrations = [
        ('game_sessions', 'auto_advance',        'INTEGER NOT NULL DEFAULT 1'),
        ('game_sessions', 'between_round_delay',  'INTEGER NOT NULL DEFAULT 10'),
        ('game_sessions', 'paused',               'INTEGER NOT NULL DEFAULT 0'),
        ('game_sessions', 'auto_advance_gen',     'INTEGER NOT NULL DEFAULT 0'),
    ]
    for tbl, col, defn in migrations:
        try:
            c.execute(f'ALTER TABLE {tbl} ADD COLUMN {col} {defn}')
            print(f'  📋 DB migrated: {tbl}.{col}')
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()


def _generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


if __name__ == '__main__':
    with app.app_context():
        _migrate_db()
        db.create_all()
        admin = User.query.filter_by(is_superadmin=True).first()
        if not admin:
            password = _generate_password()
            admin = User(username='admin', display_name='Superadmin', is_superadmin=True)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()

            line = '=' * 50
            print(f'\n{line}')
            print('  SUPERADMIN CREATO')
            print(f'{line}')
            print(f'  Username : admin')
            print(f'  Password : {password}')
            print(f'{line}')
            print('  Conserva queste credenziali in un posto sicuro.')
            print(f'{line}\n')
        else:
            print('\n✅ Superadmin già presente (username: admin)')

    print(f'⚙️  Modalità async : {_async_mode}')
    print('🚀 Server avviato  : http://localhost:5000\n')
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
