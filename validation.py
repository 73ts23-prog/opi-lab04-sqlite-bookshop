"""Перевірка введення перед записом у SQLite."""

from decimal import Decimal, InvalidOperation
import re


def text_value(value, label, minimum=1, maximum=160):
    """Обрізає пробіли й перевіряє допустиму довжину тексту."""
    result = str(value or '').strip()
    if not minimum <= len(result) <= maximum:
        raise ValueError(f'{label}: потрібно від {minimum} до {maximum} символів.')
    return result


def email_value(value):
    """Нормалізує адресу й відхиляє явно некоректний формат."""
    result = text_value(value, 'Email', maximum=254).casefold()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', result):
        raise ValueError('Вкажіть коректний email.')
    return result


def price_cents(value, allow_zero=False):
    """Перетворює грошову суму на копійки без похибок float."""
    try:
        amount = Decimal(str(value).replace(',', '.'))
        if not amount.is_finite() or amount < 0 or amount > 1000000:
            raise ValueError('Ціна має бути від 0 до 1 000 000 грн.')
        cents = amount * 100
        if cents != cents.to_integral_value() or (not allow_zero and cents == 0):
            raise ValueError('Ціна має бути додатною та містити не більше двох десяткових знаків.')
        return int(cents)
    except InvalidOperation as error:
        raise ValueError('Ціна має бути числом.') from error


def whole_number(value, label, minimum=0, maximum=10000):
    """Перевіряє ціле число та його межі."""
    try:
        result = int(str(value))
    except (ValueError, TypeError) as error:
        raise ValueError(f'{label}: потрібно ціле число.') from error
    if not minimum <= result <= maximum:
        raise ValueError(f'{label}: допустимо від {minimum} до {maximum}.')
    return result


def record_values(entity, data):
    """Повертає лише дозволені поля для конкретної таблиці."""
    if entity == 'products':
        color = data.get('color', 'forest')
        if color not in ('clay', 'forest', 'ochre'):
            raise ValueError('Невідомий колір обкладинки.')
        return {
            'title': text_value(data.get('title'), 'Назва'),
            'author': text_value(data.get('author'), 'Автор'),
            'genre': text_value(data.get('genre'), 'Жанр', maximum=80),
            'color': color,
            'price_cents': price_cents(data.get('price')),
            'stock': whole_number(data.get('stock'), 'Залишок'),
            'active': int(data.get('active') == '1'),
        }
    result = {
        'name': text_value(data.get('name'), 'Ім’я', minimum=2, maximum=120),
        'email': email_value(data.get('email')),
    }
    if entity == 'customers':
        result['phone'] = text_value(data.get('phone'), 'Телефон', minimum=0, maximum=25)
    elif entity == 'feedback':
        result['message'] = text_value(data.get('message'), 'Відгук', maximum=2000)
    else:
        raise ValueError('Невідома таблиця.')
    return result
