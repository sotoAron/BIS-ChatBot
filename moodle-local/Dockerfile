FROM php:8.2-apache

# Instalar dependencias del sistema y extensiones PHP requeridas por Moodle
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libzip-dev \
    libicu-dev \
    libxml2-dev \
    unzip \
    wget \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j$(nproc) gd zip intl mysqli soap opcache bcmath \
    && rm -rf /var/lib/apt/lists/*

# Configuración óptima de PHP para Moodle
RUN { \
    echo 'max_execution_time = 300'; \
    echo 'memory_limit = 512M'; \
    echo 'post_max_size = 128M'; \
    echo 'upload_max_filesize = 128M'; \
    echo 'max_input_vars = 5000'; \
    } > /usr/local/etc/php/conf.d/moodle.ini

# Descargar y extraer Moodle versión 4.4 oficial
WORKDIR /var/www/html
RUN wget https://download.moodle.org/download.php/direct/stable404/moodle-latest-404.tgz \
    && tar -xzf moodle-latest-404.tgz --strip-components=1 \
    && rm moodle-latest-404.tgz \
    && mkdir -p /var/www/moodledata \
    && chown -R www-data:www-data /var/www/html /var/www/moodledata