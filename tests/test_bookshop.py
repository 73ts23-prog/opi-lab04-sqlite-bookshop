"""Перевірки фактичних CRUD-операцій, транзакцій, кошика та захисту."""

import re
import sqlite3

from app import create_app
from models import get_db
from support import BaseTestCase


class BookshopTests(BaseTestCase):
    """Виконує реальні запити до Flask та SQLite."""

    def test_feedback_crud(self):
        """Створення, читання, редагування та видалення відгуку зберігаються в БД."""
        response = self.client.post('/feedback', data={'name': 'Олена', 'email': 'olena@example.com', 'message': 'Зручний каталог книжок.'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM feedback'), 1)
        self.login()
        self.assertIn('Зручний каталог', self.client.get('/admin/feedback').get_data(as_text=True))
        self.client.post('/admin/feedback/1/edit', data={'name': 'Олена', 'email': 'olena@example.com', 'message': 'Відредагований відгук.'})
        self.assertEqual(self.scalar('SELECT message FROM feedback WHERE id=1'), 'Відредагований відгук.')
        self.client.post('/admin/feedback/1/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM feedback'), 0)

    def test_empty_feedback_rejected(self):
        """Порожній відгук не потрапляє в таблицю."""
        response = self.client.post('/feedback', data={'name': 'Олена', 'email': 'olena@example.com', 'message': '  '})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM feedback'), 0)

    def test_feedback_is_escaped(self):
        """Збережений HTML показується як текст, без виконання скрипта."""
        self.client.post('/feedback', data={'name': 'Тест', 'email': 'test@example.com', 'message': '<script>alert(1)</script>'})
        html = self.client.get('/feedback').get_data(as_text=True)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('test@example.com', html)

    def test_admin_requires_login(self):
        """Сторонній відвідувач не бачить адмін-панель і не може змінити товар."""
        response = self.client.get('/admin/products')
        self.assertEqual(response.status_code, 302)
        before = self.scalar('SELECT COUNT(*) FROM products')
        response = self.client.post('/admin/products/new', data={'title': 'Чужий товар'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM products'), before)

    def test_wrong_admin_password(self):
        """Неправильний пароль не відкриває адміністративний доступ."""
        self.assertEqual(self.client.post('/admin/login', data={'username': 'admin', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_product_crud(self):
        """Адміністратор створює, редагує й видаляє товар без замовлень."""
        self.login()
        data = {'title': 'Навчальна книжка', 'author': 'Автор', 'genre': 'Роман', 'color': 'forest', 'price': '123.45', 'stock': '7', 'active': '1'}
        self.assertEqual(self.client.post('/admin/products/new', data=data).status_code, 302)
        product_id = self.scalar('SELECT id FROM products WHERE title=?', ('Навчальна книжка',))
        self.assertEqual(self.scalar('SELECT price_cents FROM products WHERE id=?', (product_id,)), 12345)
        data.update(title='Оновлена книжка', price='150.00')
        self.client.post(f'/admin/products/{product_id}/edit', data=data)
        self.assertEqual(self.scalar('SELECT title FROM products WHERE id=?', (product_id,)), 'Оновлена книжка')
        self.client.post(f'/admin/products/{product_id}/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM products WHERE id=?', (product_id,)), 0)

    def test_invalid_product_price(self):
        """Від’ємна або нескінченна ціна не змінює базу."""
        self.login()
        for price in ['-10', 'NaN', 'Infinity', '12.345']:
            with self.subTest(price=price):
                data = {'title': 'Тест', 'author': 'Автор', 'genre': 'Роман', 'color': 'clay', 'price': price, 'stock': '1', 'active': '1'}
                self.assertEqual(self.client.post('/admin/products/new', data=data).status_code, 400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM products'), 6)

    def test_customer_crud(self):
        """Додаткова таблиця клієнтів керується через адмін-панель."""
        self.login()
        data = {'name': 'Клієнт', 'email': 'CLIENT@example.com', 'phone': ''}
        self.client.post('/admin/customers/new', data=data)
        self.assertEqual(self.scalar('SELECT email FROM customers'), 'client@example.com')
        data.update(name='Новий клієнт', email='new@example.com')
        self.client.post('/admin/customers/1/edit', data=data)
        self.assertEqual(self.scalar('SELECT name FROM customers WHERE id=1'), 'Новий клієнт')
        self.client.post('/admin/customers/1/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM customers'), 0)

    def test_cart_quantity_validation(self):
        """Неможливо додати нуль, від’ємну кількість або більше залишку."""
        for quantity in ['0', '-1', '6', 'abc']:
            with self.subTest(quantity=quantity):
                self.assertEqual(self.add_to_cart(quantity=quantity).status_code, 400)
        with self.client.session_transaction() as state:
            self.assertFalse(state.get('cart'))
        self.add_to_cart(quantity=2)
        self.assertEqual(self.add_to_cart(quantity=4).status_code, 400)
        with self.client.session_transaction() as state:
            self.assertEqual(state['cart']['1'], 2)

    def test_cart_update_and_remove(self):
        """Кількість змінюється, товар можна прибрати з кошика."""
        self.add_to_cart()
        self.client.post('/cart/update/1', data={'quantity': '3'})
        with self.client.session_transaction() as state:
            self.assertEqual(state['cart']['1'], 3)
        self.client.post('/cart/remove/1')
        with self.client.session_transaction() as state:
            self.assertFalse(state.get('cart'))

    def test_order_discount_and_server_totals(self):
        """Сервер рахує копійки сам: 2×20005−4001=36009, і зменшує залишок."""
        self.add_to_cart()
        self.client.post('/cart/promo', data={'code': 'read10'})
        response = self.checkout(total='1', discount_percent='99')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scalar('SELECT subtotal_cents FROM orders'), 40010)
        self.assertEqual(self.scalar('SELECT discount_cents FROM orders'), 4001)
        self.assertEqual(self.scalar('SELECT total_cents FROM orders'), 36009)
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'), 3)
        self.assertEqual(self.scalar('SELECT quantity FROM order_items'), 2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM customers'), 1)
        with self.client.session_transaction() as state:
            self.assertFalse(state.get('cart'))

    def test_stock_failure_rolls_back_order(self):
        """Нестача другої книжки відкочує замовлення, клієнта та списання першої."""
        self.add_to_cart()
        self.add_to_cart(product_id=2, quantity=1)
        with self.app.app_context():
            db = get_db()
            db.execute('UPDATE products SET stock=0 WHERE id=2')
            db.commit()
        self.assertEqual(self.checkout().status_code, 400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM orders'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM customers'), 0)
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'), 5)

    def test_checkout_retry_is_idempotent(self):
        """Повтор старого запиту не створює друге замовлення й не списує запас двічі."""
        self.add_to_cart()
        cookie = self.client.get_cookie('session')
        other = self.app.test_client()
        other.set_cookie('session', cookie.value)
        self.checkout()
        other.post('/checkout', data={'name': 'Тестовий Покупець', 'email': 'reader@example.com', 'phone': ''})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM orders'), 1)
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'), 3)

    def test_cancel_restores_stock_once(self):
        """Скасування повертає залишок лише один раз, термінальний статус не змінюється."""
        self.add_to_cart()
        self.checkout()
        self.login()
        self.client.post('/admin/orders/1/status', data={'status': 'cancelled'})
        self.client.post('/admin/orders/1/status', data={'status': 'cancelled'})
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'), 5)
        self.assertEqual(self.client.post('/admin/orders/1/status', data={'status': 'processing'}).status_code, 400)
        self.assertEqual(self.scalar('SELECT status FROM orders'), 'cancelled')

    def test_order_keeps_product_snapshot(self):
        """Зміна каталогу не переписує ціну й назву вже оформленого замовлення."""
        self.add_to_cart()
        self.checkout()
        self.login()
        self.client.post('/admin/products/1/edit', data={'title': 'Нова назва', 'author': 'Автор', 'genre': 'Поезія', 'color': 'clay', 'price': '999.00', 'stock': '3', 'active': '1'})
        self.assertEqual(self.scalar('SELECT price_cents FROM order_items'), 20005)
        self.assertEqual(self.scalar('SELECT title FROM order_items'), 'Кобзар')
        self.client.post('/admin/products/1/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM order_items'), 1)
        self.assertEqual(self.scalar('SELECT active FROM products WHERE id=1'), 0)

    def test_order_receipt_is_private(self):
        """Інший браузер не отримує квитанцію за вгаданим номером."""
        self.add_to_cart()
        response = self.checkout()
        self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertEqual(self.app.test_client().get(response.location).status_code, 404)

    def test_search_is_unicode_and_parameterized(self):
        """Пошук розуміє український регістр і не виконує SQL із рядка пошуку."""
        html = self.client.get('/catalog?q=КОБЗАР').get_data(as_text=True)
        self.assertIn('Кобзар', html)
        self.assertNotIn('Лісова пісня', html)
        response = self.client.get('/catalog', query_string={'q': "' OR 1=1 --"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM products'), 6)
        self.assertNotIn('book-card', response.get_data(as_text=True))

    def test_price_and_genre_filter(self):
        """Фільтри відбирають книжки за жанром і ціною."""
        html = self.client.get('/catalog?genre=Поезія&min_price=190&max_price=210').get_data(as_text=True)
        self.assertIn('Кобзар', html)
        self.assertNotIn('Лісова пісня', html)
        self.assertEqual(self.client.get('/catalog?min_price=abc').status_code, 400)

    def test_database_foreign_keys_and_close(self):
        """FK відхиляє сирітський запис, а teardown закриває з’єднання."""
        with self.app.app_context():
            db = get_db()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO order_items(order_id,product_id,title,price_cents,quantity) VALUES (999,999,?,100,1)', ('Тест',))
            db.rollback()
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')

    def test_database_persists_after_restart(self):
        """Повторна ініціалізація не знищує записи."""
        self.client.post('/feedback', data={'name': 'Олена', 'email': 'olena@example.com', 'message': 'Збережений відгук.'})
        restarted = create_app(self.config)
        with restarted.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 1)

    def test_csrf_rejects_missing_token(self):
        """POST без CSRF-токена відхиляється, а форма з дійсним токеном працює."""
        protected = create_app({**self.config, 'WTF_CSRF_ENABLED': True})
        client = protected.test_client()
        self.assertEqual(client.post('/admin/login', data={'username': 'admin', 'password': 'test-password-only'}).status_code, 400)
        html = client.get('/admin/login').get_data(as_text=True)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
        response = client.post('/admin/login', data={'username': 'admin', 'password': 'test-password-only', 'csrf_token': token})
        self.assertEqual(response.status_code, 302)

    def test_status_redirect_and_error_form_use_correct_routes(self):
        """Збереження статусу веде на GET-сторінку, помилкова форма не дублює /status."""
        self.add_to_cart()
        self.checkout()
        self.login()
        response = self.client.post('/admin/orders/1/status', data={'status': 'processing'})
        self.assertEqual(response.location, '/admin/orders/1')
        self.assertEqual(self.client.get(response.location).status_code, 200)
        response = self.client.post('/admin/orders/1/status', data={'status': 'new'})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('/status/status', response.get_data(as_text=True))

    def test_customer_with_order_cannot_be_deleted(self):
        """Видалення клієнта не руйнує наявне замовлення."""
        self.add_to_cart()
        self.checkout()
        self.login()
        self.client.post('/admin/customers/1/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM customers'), 1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM orders'), 1)

    def test_disabled_promo_rejected_at_checkout(self):
        """Вимкнення коду після додавання до кошика перевіряється повторно на сервері."""
        self.add_to_cart()
        self.client.post('/cart/promo', data={'code': 'READ10'})
        with self.app.app_context():
            db = get_db()
            db.execute('UPDATE promos SET active=0')
            db.commit()
        self.assertEqual(self.checkout().status_code, 400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM orders'), 0)
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'), 5)

    def test_removed_catalog_is_not_reseeded_on_restart(self):
        """Ініціалізація не повертає товари, які адміністратор видалив."""
        self.login()
        for product_id in range(1, 7):
            self.client.post(f'/admin/products/{product_id}/delete')
        restarted = create_app(self.config)
        with restarted.app_context():
            self.assertEqual(get_db().execute('SELECT COUNT(*) FROM products').fetchone()[0], 0)
