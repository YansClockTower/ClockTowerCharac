
设置 Gunicorn + Systemd
/etc/systemd/system/edition_app.service 示例：
```
[Unit]
Description=Gunicorn instance to serve edition_app
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/edition_app
Environment="PATH=/var/www/edition_app/venv/bin"
ExecStart=/var/www/edition_app/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 wsgi:app

[Install]
WantedBy=multi-user.target
```

bash:
```
sudo systemctl daemon-reload
sudo systemctl start edition_app
sudo systemctl enable edition_app
```


To Server:
git push and pull.
run makefile in your server.
