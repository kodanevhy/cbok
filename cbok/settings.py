import configparser
import os
import sys

from cbok.conf import config

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

CONF = configparser.ConfigParser()
CONF.read(os.path.join(BASE_DIR, "cbok.conf"))
for group in config.ALL_GROUPS:
    config.validate_section_strict(CONF, group)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = ')3t5bed8bo61ao(x&%f@z7q@i#zjme34d*ms9&2a)qzw@dl7c)'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = bool(CONF.get("default", "debug"))

ALLOWED_HOSTS = ['*']
CORS_ORIGIN_ALLOW_ALL = True

# Application definition
# WARNING: do not forget to update name in apps.config class,
#          format like: name = 'cbok.alert'
CBoK_APPS = [
    'cbok.bbx.apps.BbxConfig',
    'cbok.user.apps.UserConfig',
    'cbok.alert.apps.AlertConfig',
    'cbok.notification.apps.NotificationConfig',
]
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'django_crontab',
]
INSTALLED_APPS += CBoK_APPS

AUTH_USER_MODEL = 'user.UserProfile'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'cbok.middleware.00_global.GlobalMiddleware',
    'cbok.middleware.01_input.InputMiddleware',
    'cbok.middleware.02_exception.ExcMiddleware',
]

ROOT_URLCONF = 'cbok.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'cbok.wsgi.application'

# If in production, prefer to use ingress
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'cbok'),
        'USER': os.environ.get('DB_USER', CONF.get("database", "user")),
        'PASSWORD': os.environ.get('DB_PASSWORD',
                                   CONF.get("database", "password")),
        'HOST': os.environ.get('DB_HOST', CONF.get("database", "host")),
        'PORT': os.environ.get('DB_PORT', CONF.get("database", "port")),
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_L10N = True

USE_TZ = True

STATIC_URL = '/static/'
# STATICFILES_DIRS = [
#     os.path.join(BASE_DIR, 'static')
# ]

LOG_DIR = CONF.get("default", "log_dir")
if sys.platform == "darwin":
    LOG_DIR = os.path.expanduser("~/Library/Logs/")

os.makedirs(LOG_DIR, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s][%(threadName)s:%(thread)d][%(name)s:%(lineno)d] %(message)s"
        },
        "simple": {
            "format": "%(asctime)s [%(levelname)s][%(filename)s:%(lineno)d] %(message)s"
        }
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "DEBUG",
        },
        "file": {
            "class": "logging.handlers.WatchedFileHandler",
            "filename": os.path.join(LOG_DIR, "cbok.log"),
            "formatter": "standard",
            "level": "DEBUG",
        },
    },

    "root": {
        "handlers": ["console", "file"],
        "level": "DEBUG",
    },

    "loggers": {
        "urllib3": {"level": "WARNING"},
        "urllib3.connectionpool": {"level": "WARNING"},
        "charset_normalizer": {"level": "WARNING"},
        "filelock": {"level": "WARNING"},
        "asyncio": {"level": "WARNING"},
        "openai": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}

Workspace = CONF.get("default", "workspace")

if "email" in CONF.sections():
    EMAIL_HOST = CONF.get("email", "host")
    EMAIL_PORT = CONF.getint("email", "port", fallback=25)
    EMAIL_HOST_USER = CONF.get("email", "host_user")
    EMAIL_HOST_PASSWORD = CONF.get("email", "host_password")
    EMAIL_USE_TLS = CONF.getboolean("email", "use_tls", fallback=False)
    EMAIL_FROM = CONF.get("email", "from")
