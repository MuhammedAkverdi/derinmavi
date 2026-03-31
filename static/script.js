document.addEventListener('DOMContentLoaded', function () {
    const navToggle = document.getElementById('nav-toggle');
    const siteNav = document.getElementById('site-nav');

    if (navToggle && siteNav) {
        navToggle.addEventListener('click', function () {
            const open = siteNav.classList.toggle('open');
            navToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }

    const path = window.location.pathname;
    document.querySelectorAll('#site-nav a').forEach(function (link) {
        const href = link.getAttribute('href');
        if (href === path) {
            link.classList.add('active');
        }
    });

    const contactForm = document.getElementById('contact-form');
    const successMsg = document.getElementById('form-success');
    if (contactForm && successMsg) {
        contactForm.addEventListener('submit', function (event) {
            event.preventDefault();
            successMsg.style.display = 'block';
            contactForm.reset();
            setTimeout(function () {
                successMsg.style.display = 'none';
            }, 4000);
        });
    }
});
