"""Створення та публічний перегляд відгуків без показу email."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models import get_db, save_record

bp = Blueprint('feedback', __name__)


@bp.route('/feedback', methods=['GET', 'POST'])
def index():
    """Зберігає перевірений відгук і показує останні повідомлення."""
    error, status = None, 200
    if request.method == 'POST':
        try:
            save_record('feedback', request.form)
        except ValueError as exception:
            error, status = str(exception), 400
        else:
            flash('Дякуємо! Відгук збережено.', 'success')
            return redirect(url_for('feedback.index'))
    reviews = get_db().execute('SELECT id,name,message,created_at FROM feedback ORDER BY id DESC LIMIT 20').fetchall()
    return render_template('feedback.html', reviews=reviews, error=error, values=request.form), status
