import secrets
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


def _generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


if __name__ == '__main__':
    with app.app_context():
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
