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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(is_superadmin=True).first():
            admin = User(username='admin', display_name='Superadmin', is_superadmin=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Superadmin creato — login: admin / admin123")

    print(f"⚙️  Modalità async: {_async_mode}")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
