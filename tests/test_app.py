"""Перевірки сторінок, навігації та локальних ресурсів Flask-застосунку."""

from html.parser import HTMLParser
import unittest

from support import BaseTestCase


class PageParser(HTMLParser):
    """Збирає посилання та заголовок сторінки для перевірок."""

    def __init__(self):
        """Готує порожні колекції."""
        super().__init__()
        self.links = []
        self.title = ''
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        """Зберігає атрибути посилань та початок title."""
        if tag == 'a':
            self.links.append(dict(attrs))
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        """Позначає завершення title."""
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        """Збирає текст title."""
        if self.in_title:
            self.title += data


class AppTests(BaseTestCase):
    """Перевіряє поведінку навчального сайту."""

    def setUp(self):
        """Створює клієнт без запуску мережевого сервера."""
        super().setUp()
        self.paths = ['/', '/about', '/catalog', '/contacts']

    def test_all_pages_available(self):
        """Чотири сторінки повертають HTML та код 200."""
        for path in self.paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('<h1', response.get_data(as_text=True))

    def test_page_titles_are_unique(self):
        """Назва кожної сторінки відрізняється та містить назву проєкту."""
        titles = []
        for path in self.paths:
            parser = PageParser()
            parser.feed(self.client.get(path).get_data(as_text=True))
            self.assertIn('Читай', parser.title)
            titles.append(parser.title)
        self.assertEqual(len(set(titles)), 4)

    def test_navigation_reaches_all_pages(self):
        """Кожна сторінка містить посилання на всі розділи."""
        for path in self.paths:
            with self.subTest(path=path):
                parser = PageParser()
                parser.feed(self.client.get(path).get_data(as_text=True))
                self.assertTrue(set(self.paths).issubset({a.get('href') for a in parser.links}))

    def test_current_page_is_marked(self):
        """Активне посилання меню відповідає поточному маршруту."""
        for path in self.paths:
            with self.subTest(path=path):
                parser = PageParser()
                parser.feed(self.client.get(path).get_data(as_text=True))
                current = [a['href'] for a in parser.links if a.get('aria-current') == 'page']
                self.assertEqual(current, [path])

    def test_local_styles_and_script(self):
        """CSS та JavaScript доступні з локальної папки static."""
        for path in ['/static/css/style.css', '/static/js/menu.js']:
            with self.subTest(path=path):
                with self.client.get(path) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertGreater(len(response.data), 100)

    def test_unknown_page(self):
        """Невідома адреса повертає 404 із посиланням на головну."""
        response = self.client.get('/missing-page')
        self.assertEqual(response.status_code, 404)
        self.assertIn('Повернутися на головну', response.get_data(as_text=True))

    def test_ukrainian_and_viewport(self):
        """Сторінки мають українську мову та налаштування мобільного масштабу."""
        for path in self.paths:
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('lang="uk"', html)
            self.assertIn('name="viewport"', html)

    def test_catalog_has_book_content(self):
        """Каталог містить назви творів і авторів."""
        html = self.client.get('/catalog').get_data(as_text=True)
        for value in ['Кобзар', 'Лісова пісня', 'Тарас Шевченко', 'Леся Українка']:
            self.assertIn(value, html)


if __name__ == '__main__':
    unittest.main()
