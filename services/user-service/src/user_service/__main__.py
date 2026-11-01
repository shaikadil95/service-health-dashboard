from shd_telemetry import configure_logging, configure_telemetry, serve

from . import SERVICE_NAME, __version__
from .app import create_app


def main() -> None:
    telemetry = configure_telemetry(SERVICE_NAME, __version__)
    configure_logging(telemetry)
    serve(create_app(telemetry))


if __name__ == "__main__":
    main()
