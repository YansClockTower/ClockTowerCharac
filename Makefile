install_app:
    sudo rm -rf /var/www/edition_app
    sudo cp myapp/ /var/www/edition_app -r

run:
    gunicorn wsgi:app --bind 127.0.0.1:8000
