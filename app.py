"""Фабрика Flask-застосунку навчальної книгарні «Читай»."""

import os
from pathlib import Path
import secrets

import click
from flask import Flask, render_template, session
from flask_wtf.csrf import CSRFError, CSRFProtect

from models import close_db, create_admin, find_products, get_db, init_db


def create_app(test_config=None):
    """Створює застосунок з окремою БД, CSRF-захистом і маршрутами."""
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / 'db.sqlite'),
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY']:
        secret_file = Path(app.instance_path) / 'secret.key'
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(32), encoding='ascii')
        app.config['SECRET_KEY'] = secret_file.read_text(encoding='ascii').strip()
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)
    CSRFProtect(app)

    from routes.admin import bp as admin_bp
    from routes.feedback import bp as feedback_bp
    from routes.shop import bp as shop_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(shop_bp)

    @app.template_filter('money')
    def money(cents):
        """Форматує цілу кількість копійок як гривні."""
        return f'{cents // 100},{cents % 100:02d} грн'

    @app.context_processor
    def common_context():
        """Додає кількість книжок у кошику до спільного меню."""
        return {'cart_count': sum(session.get('cart', {}).values())}

    @app.get('/')
    def home():
        """Показує перші три активні книжки з бази даних."""
        return render_template('home.html', books=find_products()[:3])

    @app.get('/about')
    def about():
        """Пояснює навчальне призначення книгарні."""
        return render_template('about.html')

    @app.get('/contacts')
    def contacts():
        """Показує автора й посилання на GitHub."""
        return render_template('contacts.html')

    @app.errorhandler(404)
    def not_found(error):
        """Зберігає оформлення сайту для невідомих адрес."""
        return render_template('404.html'), 404

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        """Просить оновити форму з відсутнім або застарілим токеном."""
        return render_template('error.html', message='Форма застаріла або не містить захисного токена. Оновіть сторінку й повторіть дію.'), 400

    @app.cli.command('init-db')
    def init_command():
        """Створює схему, не видаляючи наявні дані."""
        init_db()
        click.echo('Базу даних ініціалізовано; наявні записи збережено.')

    @app.cli.command('create-admin')
    @click.option('--username', default='admin', prompt='Логін')
    @click.password_option(prompt='Пароль (не менше 10 символів)')
    def admin_command(username, password):
        """Створює обліковий запис через приховане введення пароля."""
        try:
            create_admin(username, password)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo('Адміністратора створено.')

    with app.app_context():
        init_db()
    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5004, debug=False)
