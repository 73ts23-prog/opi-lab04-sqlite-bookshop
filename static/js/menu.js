// Стан мобільної навігації змінюється разом зі станом кнопки.
const toggle = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#main-nav');

function setMenu(open) {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Закрити меню' : 'Відкрити меню');
    navigation.dataset.open = String(open);
}

toggle.addEventListener('click', () => {
    setMenu(toggle.getAttribute('aria-expanded') !== 'true');
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        setMenu(false);
        toggle.focus();
    }
});

// Зміна ширини екрана скидає попередній стан меню.
window.matchMedia('(min-width: 901px)').addEventListener('change', () => setMenu(false));
