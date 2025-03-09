from app import db, User, app

with app.app_context():
    User.query.delete()
    db.session.commit()
    print("All users have been deleted.")
