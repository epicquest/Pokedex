# 🧬 Pokédex

A web-based Pokédex built with Django. Browse and explore Pokémon with a clean, minimal interface and Django-powered backend.

🔗 **Live Demo**: [https://pokedex-o9f1.onrender.com/](https://pokedex-o9f1.onrender.com/)

---

## Features

- Django-powered backend with clean URL routing
- Dynamic Pokémon data display
- Responsive, minimal frontend styling
- Deployed on Render

---

## Tech Stack

- Python 3.x
- Django 4.x
- HTML/CSS (or Bootstrap/Tailwind, if used)
- Gunicorn (for WSGI)
- Render (for hosting)

---

### Local Development

## install dependencies

- pip install -r requirements.txt

## sync db
python manage.py migrate
python manage.py sync_pokemon

## run server
python manage.py runserver or gunicorn pokedexsite.wsgi
