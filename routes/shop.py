"""Каталог, кошик, промокоди та оформлення навчальних замовлень."""

import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from models import STATUSES, cart_snapshot, find_products, get_db, get_promo, get_record, place_order
from validation import price_cents, text_value, whole_number

bp = Blueprint('shop', __name__)


def render_cart(error=None, status=200, checkout_values=None):
    """Збирає актуальну суму кошика та дані форми замовлення."""
    snapshot = cart_snapshot(session.get('cart', {}), session.get('promo_code', ''))
    return render_template('cart.html', **snapshot, error=error, values=checkout_values or {}, promo_code=session.get('promo_code', ''), promo_hint=get_promo('READ10')), status


@bp.get('/catalog')
def catalog():
    """Фільтрує книжки параметризованими запитами."""
    error, status = None, 200
    try:
        query = text_value(request.args.get('q'), 'Пошук', 0, 160)
        minimum = price_cents(request.args['min_price'], True) if request.args.get('min_price') else None
        maximum = price_cents(request.args['max_price'], True) if request.args.get('max_price') else None
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError('Мінімальна ціна не може перевищувати максимальну.')
        books = find_products(query, request.args.get('genre', ''), minimum, maximum)
    except ValueError as exception:
        books, error, status = [], str(exception), 400
    genres = [row['genre'] for row in get_db().execute('SELECT DISTINCT genre FROM products WHERE active=1 ORDER BY genre')]
    return render_template('catalog.html', books=books, genres=genres, filters=request.args, error=error), status


@bp.get('/cart')
def cart():
    """Показує кошик і форму оформлення."""
    return render_cart()


@bp.post('/cart/add/<int:product_id>')
def cart_add(product_id):
    """Додає лише доступний товар у допустимій кількості."""
    product = get_record('products', product_id)
    if product is None or not product['active']:
        abort(404)
    cart_data = dict(session.get('cart', {}))
    try:
        quantity = whole_number(request.form.get('quantity'), 'Кількість', 1, 99)
        total = cart_data.get(str(product_id), 0) + quantity
        if total > min(product['stock'], 99):
            raise ValueError('На складі недостатньо книжок для такої кількості.')
    except ValueError as error:
        return render_cart(str(error), 400)
    cart_data[str(product_id)] = total
    session['cart'] = cart_data
    session['checkout_token'] = secrets.token_urlsafe(24)
    flash('Книжку додано до кошика.', 'success')
    return redirect(url_for('shop.cart'))


@bp.post('/cart/update/<int:product_id>')
def cart_update(product_id):
    """Змінює кількість наявної позиції кошика."""
    cart_data = dict(session.get('cart', {}))
    product = get_record('products', product_id)
    if str(product_id) not in cart_data or product is None:
        abort(404)
    try:
        quantity = whole_number(request.form.get('quantity'), 'Кількість', 1, 99)
        if not product['active'] or quantity > product['stock']:
            raise ValueError('Задана кількість недоступна.')
    except ValueError as error:
        return render_cart(str(error), 400)
    cart_data[str(product_id)] = quantity
    session['cart'] = cart_data
    session['checkout_token'] = secrets.token_urlsafe(24)
    return redirect(url_for('shop.cart'))


@bp.post('/cart/remove/<int:product_id>')
def cart_remove(product_id):
    """Прибирає позицію, зокрема товар, якого вже немає в каталозі."""
    cart_data = dict(session.get('cart', {}))
    cart_data.pop(str(product_id), None)
    session['cart'] = cart_data
    session['checkout_token'] = secrets.token_urlsafe(24)
    return redirect(url_for('shop.cart'))


@bp.post('/cart/promo')
def cart_promo():
    """Застосовує активний промокод або прибирає його порожнім введенням."""
    code = request.form.get('code', '').strip().upper()
    if len(code) > 40 or (code and not get_promo(code)):
        return render_cart('Промокод не знайдено або вимкнено.', 400)
    session['promo_code'] = code
    session['checkout_token'] = secrets.token_urlsafe(24)
    return redirect(url_for('shop.cart'))


@bp.post('/checkout')
def checkout():
    """Записує замовлення; суму з форми не приймає."""
    try:
        order_id = place_order(session.get('cart', {}), request.form, session.get('promo_code', ''), session.get('checkout_token') or secrets.token_urlsafe(24))
    except ValueError as error:
        return render_cart(str(error), 400, request.form)
    session['cart'] = {}
    session.pop('promo_code', None)
    session['receipt_orders'] = (session.get('receipt_orders', []) + [order_id])[-20:]
    return redirect(url_for('shop.receipt', order_id=order_id))


@bp.get('/order/<int:order_id>')
def receipt(order_id):
    """Показує квитанцію лише браузеру, який оформив замовлення."""
    if order_id not in session.get('receipt_orders', []):
        abort(404)
    order = get_db().execute('SELECT orders.*,customers.name FROM orders JOIN customers ON customers.id=orders.customer_id WHERE orders.id=?', (order_id,)).fetchone()
    if order is None:
        abort(404)
    items = get_db().execute('SELECT * FROM order_items WHERE order_id=?', (order_id,)).fetchall()
    return render_template('receipt.html', order=order, items=items, statuses=STATUSES)
