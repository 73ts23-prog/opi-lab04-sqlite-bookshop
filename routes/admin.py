"""Адміністративні маршрути з перевіркою входу та CSRF-захистом."""

from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from models import ENTITIES, STATUSES, TRANSITIONS, delete_record, get_db, get_record, save_record, set_order_status

bp = Blueprint('admin', __name__, url_prefix='/admin')
LABELS = {'products': 'Товари', 'customers': 'Клієнти', 'feedback': 'Відгуки'}
FIELDS = {
    'products': [('title', 'Назва', 'text'), ('author', 'Автор', 'text'), ('genre', 'Жанр', 'text'), ('price', 'Ціна, грн', 'text'), ('stock', 'Залишок', 'number')],
    'customers': [('name', 'Ім’я', 'text'), ('email', 'Email', 'email'), ('phone', 'Телефон', 'text')],
    'feedback': [('name', 'Ім’я', 'text'), ('email', 'Email', 'email'), ('message', 'Відгук', 'textarea')],
}


def login_required(view):
    """Дозволяє виконання лише за наявності адміністратора в БД."""
    @wraps(view)
    def protected(*args, **kwargs):
        """Перевіряє підписану сесію перед кожним адміністративним запитом."""
        admin_id = session.get('admin_id')
        if not admin_id or not get_db().execute('SELECT id FROM admins WHERE id=?', (admin_id,)).fetchone():
            return redirect(url_for('admin.login'))
        return view(*args, **kwargs)
    return protected


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Перевіряє хеш пароля й створює адміністративну сесію."""
    error, status = None, 200
    if request.method == 'POST':
        admin = get_db().execute('SELECT * FROM admins WHERE username=?', (request.form.get('username', ''),)).fetchone()
        if admin and check_password_hash(admin['password_hash'], request.form.get('password', '')):
            session.clear()
            session['admin_id'] = admin['id']
            return redirect(url_for('admin.dashboard'))
        error, status = 'Неправильний логін або пароль.', 401
    return render_template('admin/login.html', error=error), status


@bp.post('/logout')
def logout():
    """Завершує сесію адміністратора."""
    session.clear()
    return redirect(url_for('home'))


@bp.get('')
@login_required
def dashboard():
    """Показує кількість записів у навчальній базі."""
    counts = {table: get_db().execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('products', 'customers', 'feedback', 'orders')}
    return render_template('admin/dashboard.html', counts=counts)


@bp.get('/<entity>')
@login_required
def records(entity):
    """Показує записи лише дозволеної адміністративної таблиці."""
    if entity not in ENTITIES:
        abort(404)
    rows = get_db().execute(f'SELECT * FROM {entity} ORDER BY id DESC').fetchall()
    return render_template('admin/records.html', rows=rows, entity=entity, label=LABELS[entity])


@bp.route('/<entity>/new', defaults={'record_id': None}, methods=['GET', 'POST'])
@bp.route('/<entity>/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_record(entity, record_id):
    """Виконує створення та зміну товарів, клієнтів і відгуків."""
    if entity not in ENTITIES:
        abort(404)
    record = get_record(entity, record_id) if record_id is not None else None
    if record_id is not None and record is None:
        abort(404)
    values = dict(record) if record else {'stock': 1, 'active': 1, 'color': 'forest'}
    if entity == 'products' and record:
        values['price'] = f"{record['price_cents'] // 100}.{record['price_cents'] % 100:02d}"
    error, status = None, 200
    if request.method == 'POST':
        values = dict(request.form)
        values['active'] = request.form.get('active', '0')
        try:
            save_record(entity, request.form, record_id)
        except ValueError as exception:
            error, status = str(exception), 400
        else:
            flash('Зміни збережено.', 'success')
            return redirect(url_for('admin.records', entity=entity))
    return render_template('admin/form.html', entity=entity, label=LABELS[entity], fields=FIELDS[entity], values=values, error=error, editing=record_id is not None), status


@bp.post('/<entity>/<int:record_id>/delete')
@login_required
def remove_record(entity, record_id):
    """Видаляє запис POST-запитом або пояснює обмеження зв’язків."""
    if entity not in ENTITIES or get_record(entity, record_id) is None:
        abort(404)
    try:
        message = delete_record(entity, record_id)
    except ValueError as error:
        flash(str(error), 'error')
    else:
        flash(message, 'success')
    return redirect(url_for('admin.records', entity=entity))


@bp.get('/orders')
@login_required
def orders():
    """Читає замовлення разом з іменами клієнтів."""
    rows = get_db().execute('SELECT orders.*,customers.name FROM orders JOIN customers ON customers.id=orders.customer_id ORDER BY orders.id DESC').fetchall()
    return render_template('admin/orders.html', rows=rows, statuses=STATUSES)


@bp.get('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    """Показує позиції замовлення окремим GET-маршрутом."""
    return render_order(order_id)


@bp.post('/orders/<int:order_id>/status')
@login_required
def order_status(order_id):
    """Змінює статус POST-запитом і повертає на сторінку перегляду."""
    try:
        set_order_status(order_id, request.form.get('status', ''))
    except ValueError as error:
        return render_order(order_id, str(error), 400)
    flash('Статус збережено.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


def render_order(order_id, error=None, status=200):
    """Готує сторінку замовлення, зокрема після помилкового введення."""
    db = get_db()
    order = db.execute('SELECT orders.*,customers.name,customers.email,customers.phone FROM orders JOIN customers ON customers.id=orders.customer_id WHERE orders.id=?', (order_id,)).fetchone()
    if order is None:
        abort(404)
    items = db.execute('SELECT * FROM order_items WHERE order_id=?', (order_id,)).fetchall()
    return render_template('admin/order.html', order=order, items=items, statuses=STATUSES, allowed=(order['status'], *TRANSITIONS[order['status']]), error=error), status


@bp.get('/promos')
@login_required
def promos():
    """Показує навчальні промокоди та їхній стан."""
    return render_template('admin/promos.html', rows=get_db().execute('SELECT * FROM promos ORDER BY id').fetchall())


@bp.post('/promos/<int:promo_id>/toggle')
@login_required
def promo_toggle(promo_id):
    """Вмикає або вимикає наявний промокод."""
    db = get_db()
    if not db.execute('SELECT id FROM promos WHERE id=?', (promo_id,)).fetchone():
        abort(404)
    with db:
        db.execute('UPDATE promos SET active=1-active WHERE id=?', (promo_id,))
    return redirect(url_for('admin.promos'))
