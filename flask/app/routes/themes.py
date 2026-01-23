from flask import Blueprint, render_template

bp = Blueprint("themes", __name__)

@bp.route("/themes")
def themes_showcase():
    return render_template("themes_showcase.html")

