"""Доступ до SQLite, CRUD та атомарне оформлення замовлень."""

from pathlib import Path
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash

from validation import record_values, text_value, whole_number

STATUSES = {'new': 'Нове', 'processing': 'В обробці', 'shipped': 'Відправлено', 'completed': 'Виконано', 'cancelled': 'Скасовано'}
TRANSITIONS = {'new': ('processing', 'cancelled'), 'processing': ('shipped', 'cancelled'), 'shipped': ('completed',), 'completed': (), 'cancelled': ()}
ENTITIES = ('products', 'customers', 'feedback')
SEED_BOOKS = [
    ('Кобзар', 'Тарас Шевченко', 'Поезія', 'clay', 22000, 12),
    ('Лісова пісня', 'Леся Українка', 'Драма-феєрія', 'forest', 18000, 10),
    ('Захар Беркут', 'Іван Франко', 'Історична повість', 'ochre', 24000, 8),
    ('Тіні забутих предків', 'Михайло Коцюбинський', 'Повість', 'forest', 19500, 9),
    ('Кайдашева сім’я', 'Іван Нечуй-Левицький', 'Повість', 'ochre', 21000, 11),
    ('Місто', 'Валер’ян Підмогильний', 'Роман', 'clay', 26000, 7),
]


def get_db():
    """Відкриває одне з’єднання на контекст запиту та вмикає зовнішні ключі."""
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        # Вбудований SQLite LOWER не змінює регістр українських літер.
        g.db.create_function('casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
    return g.db


def close_db(exception=None):
    """Явно закриває з’єднання після завершення запиту."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Створює схему й одноразово додає навчальні книжки та промокод."""
    db = get_db()
    schema = Path(current_app.root_path, 'schema.sql').read_text(encoding='utf-8')
    db.executescript(schema)
    if db.execute('PRAGMA user_version').fetchone()[0] == 0:
        with db:
            db.executemany('INSERT INTO products(title,author,genre,color,price_cents,stock) VALUES (?,?,?,?,?,?)', SEED_BOOKS)
            db.execute('INSERT INTO promos(code,percent) VALUES (?,?)', ('READ10', 10))
            db.execute('PRAGMA user_version = 1')
    # Неруйнівне оновлення БД ранньої версії цієї лабораторної.
    with db:
        if 'version' not in {row['name'] for row in db.execute('PRAGMA table_info(products)')}:
            db.execute('ALTER TABLE products ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
        if db.execute('PRAGMA user_version').fetchone()[0] < 2:
            db.execute('PRAGMA user_version = 2')


def create_admin(username, password):
    """Створює адміністратора з хешем пароля, без стандартного пароля в коді."""
    username = text_value(username, 'Логін', minimum=3, maximum=40)
    if len(password) < 10:
        raise ValueError('Пароль має містити щонайменше 10 символів.')
    try:
        with get_db() as db:
            db.execute('INSERT INTO admins(username,password_hash) VALUES (?,?)', (username, generate_password_hash(password)))
    except sqlite3.IntegrityError as error:
        raise ValueError('Адміністратор із таким логіном уже існує.') from error


def get_record(entity, record_id):
    """Читає запис; назва таблиці береться тільки з дозволеного списку."""
    if entity not in ENTITIES:
        raise ValueError('Невідома таблиця.')
    return get_db().execute(f'SELECT * FROM {entity} WHERE id=?', (record_id,)).fetchone()


def save_record(entity, data, record_id=None):
    """Створює або змінює перевірений запис параметризованим запитом."""
    values = record_values(entity, data)
    columns = list(values)
    try:
        with get_db() as db:
            if record_id is None:
                marks = ','.join('?' for _ in columns)
                cursor = db.execute(f'INSERT INTO {entity}({",".join(columns)}) VALUES ({marks})', list(values.values()))
                return cursor.lastrowid
            assignments = ','.join(f'{name}=?' for name in columns)
            if entity == 'products':
                version = whole_number(data.get('version'), 'Версія запису', 1, 2147483647)
                changed = db.execute(f'UPDATE products SET {assignments},version=version+1 WHERE id=? AND version=?', [*values.values(), record_id, version])
                if changed.rowcount != 1:
                    raise ValueError('Книжку вже змінено або оформлено замовлення. Оновіть сторінку редагування.')
            else:
                db.execute(f'UPDATE {entity} SET {assignments} WHERE id=?', [*values.values(), record_id])
            return record_id
    except sqlite3.IntegrityError as error:
        raise ValueError('Не вдалося зберегти запис. Перевірте, чи не зайнятий цей email.') from error


def delete_record(entity, record_id):
    """Видаляє запис, зберігаючи цілісність історії замовлень."""
    if entity not in ENTITIES:
        raise ValueError('Невідома таблиця.')
    db = get_db()
    with db:
        if entity == 'products':
            # Стабільний ID також зберігає сенс старих кошиків у підписаних cookie.
            db.execute('UPDATE products SET active=0,version=version+1 WHERE id=?', (record_id,))
            return 'Книжку приховано з каталогу; її ID та історію збережено.'
        if entity == 'customers' and db.execute('SELECT 1 FROM orders WHERE customer_id=?', (record_id,)).fetchone():
            raise ValueError('Клієнта із замовленнями не можна видалити.')
        db.execute(f'DELETE FROM {entity} WHERE id=?', (record_id,))
    return 'Запис видалено.'


def find_products(query='', genre='', minimum=None, maximum=None):
    """Шукає активні книжки за назвою, автором, жанром і ціною."""
    clauses, params = ['active=1'], []
    if query:
        clauses.append("instr(casefold(title || ' ' || author), casefold(?)) > 0")
        params.append(query)
    if genre:
        clauses.append('genre=?')
        params.append(genre)
    if minimum is not None:
        clauses.append('price_cents>=?')
        params.append(minimum)
    if maximum is not None:
        clauses.append('price_cents<=?')
        params.append(maximum)
    return get_db().execute('SELECT * FROM products WHERE ' + ' AND '.join(clauses) + ' ORDER BY id', params).fetchall()


def get_promo(code):
    """Повертає лише активний промокод."""
    return get_db().execute('SELECT * FROM promos WHERE code=? AND active=1', (code.strip().upper(),)).fetchone() if code else None


def cart_snapshot(cart, promo_code=''):
    """Рахує актуальні суми та позначає недоступні позиції кошика."""
    items = []
    for product_id, quantity in cart.items():
        product = get_record('products', product_id)
        if product is None:
            product = {'id': product_id, 'title': 'Товар недоступний', 'author': '', 'price_cents': 0, 'stock': 0, 'active': 0}
        items.append({'product': product, 'quantity': quantity, 'line_cents': product['price_cents'] * quantity,
                      'available': bool(product['active'] and product['stock'] >= quantity)})
    subtotal = sum(item['line_cents'] for item in items)
    promo = get_promo(promo_code)
    discount = (subtotal * promo['percent'] + 50) // 100 if promo else 0
    return {'items': items, 'subtotal': subtotal, 'discount': discount, 'total': subtotal - discount,
            'promo': promo, 'available': bool(items) and all(item['available'] for item in items)}


def place_order(cart, customer_data, promo_code, checkout_token):
    """Атомарно записує замовлення, позиції та списання залишків."""
    customer = record_values('customers', customer_data)
    if not cart:
        raise ValueError('Кошик порожній.')
    db = get_db()
    with db:
        # Блокування запису до перевірки залишків захищає від їх подвійного списання.
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id FROM orders WHERE checkout_token=?', (checkout_token,)).fetchone()
        if existing:
            return existing['id']
        snapshot = cart_snapshot(cart, promo_code)
        if not snapshot['available']:
            raise ValueError('Одна з книжок недоступна або її залишок змінився. Оновіть кошик.')
        if promo_code and not snapshot['promo']:
            raise ValueError('Промокод недійсний або вимкнений.')
        db.execute('INSERT INTO customers(name,email,phone) VALUES (?,?,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name,phone=excluded.phone', tuple(customer.values()))
        customer_id = db.execute('SELECT id FROM customers WHERE email=?', (customer['email'],)).fetchone()['id']
        cursor = db.execute('INSERT INTO orders(customer_id,subtotal_cents,discount_cents,total_cents,promo_code,checkout_token) VALUES (?,?,?,?,?,?)',
                            (customer_id, snapshot['subtotal'], snapshot['discount'], snapshot['total'], promo_code.upper(), checkout_token))
        order_id = cursor.lastrowid
        for item in snapshot['items']:
            product, quantity = item['product'], whole_number(item['quantity'], 'Кількість', 1, 99)
            changed = db.execute('UPDATE products SET stock=stock-?,version=version+1 WHERE id=? AND active=1 AND stock>=?', (quantity, product['id'], quantity))
            if changed.rowcount != 1:
                raise ValueError('Залишок змінився. Спробуйте ще раз.')
            db.execute('INSERT INTO order_items(order_id,product_id,title,price_cents,quantity) VALUES (?,?,?,?,?)',
                       (order_id, product['id'], product['title'], product['price_cents'], quantity))
        return order_id


def set_order_status(order_id, status):
    """Змінює статус за дозволеними переходами; скасування повертає запас один раз."""
    db = get_db()
    with db:
        db.execute('BEGIN IMMEDIATE')
        order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not order:
            raise ValueError('Замовлення не знайдено.')
        if status == order['status']:
            return
        if status not in TRANSITIONS[order['status']]:
            raise ValueError('Такий перехід статусу недоступний.')
        if status == 'cancelled':
            for item in db.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?', (order_id,)).fetchall():
                db.execute('UPDATE products SET stock=stock+?,version=version+1 WHERE id=?', (item['quantity'], item['product_id']))
        db.execute('UPDATE orders SET status=? WHERE id=?', (status, order_id))
