import os

from opentelemetry.instrumentation.environment_variables import OTEL_PYTHON_CONFIGURATOR as _OTEL_PYTHON_CONFIGURATOR
from opentelemetry.instrumentation.environment_variables import OTEL_PYTHON_DISTRO as _OTEL_PYTHON_DISTRO

if os.environ.get(_OTEL_PYTHON_DISTRO) is None:
    os.environ.setdefault(_OTEL_PYTHON_DISTRO, "tomodachi")

if os.environ.get(_OTEL_PYTHON_CONFIGURATOR) is None:
    os.environ.setdefault(_OTEL_PYTHON_CONFIGURATOR, "tomodachi")

OTEL_PYTHON_TOMODACHI_EXCLUDED_URLS = "OTEL_PYTHON_TOMODACHI_EXCLUDED_URLS"
