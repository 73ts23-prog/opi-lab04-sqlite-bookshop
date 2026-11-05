"""Ізольоване середовище перевірок SQLite та Flask."""

from pathlib import Path
import tempfile
import unittest

from app import create_app
from models import create_admin, get_db


class BaseTestCase(unittest.TestCase):
    """Кожна перевірка отримує окремий тимчасовий файл БД."""

    def setUp(self):
        """Готує застосунок, клієнт і відомі навчальні значення."""
        self.temp = tempfile.TemporaryDirectory()
        self.config = {
            'TESTING': True,
            'DATABASE': str(Path(self.temp.name) / 'test.sqlite'),
            'SECRET_KEY': 'test-only-not-a-real-secret',
            'WTF_CSRF_ENABLED': False,
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        with self.app.app_context():
            create_admin('admin', 'test-password-only')
            db = get_db()
            db.execute('UPDATE products SET price_cents=20005, stock=5 WHERE id=1')
            db.commit()

    def tearDown(self):
        """Прибирає лише власну тимчасову папку перевірки."""
        self.temp.cleanup()

    def login(self):
        """Входить як адміністратор через справжній маршрут."""
        return self.client.post('/admin/login', data={'username': 'admin', 'password': 'test-password-only'})

    def scalar(self, sql, params=()):
        """Читає одне контрольне значення з тестової бази."""
        with self.app.app_context():
            return get_db().execute(sql, params).fetchone()[0]

    def add_to_cart(self, product_id=1, quantity=2):
        """Додає книжку через HTTP, а не змінює кошик вручну."""
        return self.client.post(f'/cart/add/{product_id}', data={'quantity': quantity})

    def checkout(self, **changes):
        """Надсилає навчальні контактні дані покупця."""
        data = {'name': 'Тестовий Покупець', 'email': 'reader@example.com', 'phone': '+380000000000'}
        data.update(changes)
        return self.client.post('/checkout', data=data)
