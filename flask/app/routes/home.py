from flask import Blueprint, render_template

bp = Blueprint('home', __name__)

@bp.route('/home')
@bp.route('/')
def home_page():
    return render_template('home.html')