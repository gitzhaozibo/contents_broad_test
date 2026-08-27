FROM python:3.12-slim

# Install nginx and supervisor
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor \
    && rm -rf /var/lib/apt/lists/*

# Remove the Debian default site to avoid conflicting server_name "_"
RUN rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default

WORKDIR /app

# Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Application code and the local content mirror
COPY src/ /app/src/
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY index.html /var/www/html/index.html
COPY health_check.html /var/www/html/health_check.html
COPY content/ /var/www/html/content/
RUN chown -R www-data:www-data /var/www/html/content

# Build-time validation: fail the build on missing files, bad imports or
# invalid nginx config.
RUN test -f /app/src/api.py \
    && test -f /var/www/html/index.html \
    && test -f /var/www/html/health_check.html \
    && python -c "import fastapi, uvicorn, azure.identity, azure.storage.blob" \
    && python -m py_compile /app/src/api.py \
    && nginx -t

# nginx listen / EXPOSE / WEBSITES_PORT must all match (80)
EXPOSE 80

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
