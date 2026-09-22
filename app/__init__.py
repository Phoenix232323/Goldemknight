"""GoldenKnight dashboard - Flask-applicatie voor de Raspberry Pi."""

from __future__ import annotations

import atexit
import logging
import os
from datetime import timedelta

from flask import Flask

from .config import Config
from .database import close_db, get_db, init_db
from .sampler import SensorSampler
from .security import apply_security_headers, ensure_default_user
from .sensors import SensorReader
from .weather import WeatherService

__version__ = "1.0.0"


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)
    app.config["VERSION"] = __version__
    app.permanent_session_lifetime = timedelta(
        minutes=app.config["SESSION_IDLE_MINUTES"]
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    app.config["INSTANCE_DIR"].mkdir(parents=True, exist_ok=True)
    init_db(app.config["DATABASE_PATH"])

    app.extensions["sensor_reader"] = SensorReader(app.config)
    app.extensions["weather"] = WeatherService(app.config)

    with app.app_context():
        ensure_default_user(get_db())

    from .routes.api import bp as api_bp
    from .routes.auth import bp as auth_bp
    from .routes.pages import bp as pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)

    app.teardown_appcontext(close_db)
    app.after_request(apply_security_headers)

    _start_sampler(app)
    return app


def _start_sampler(app: Flask) -> None:
    """Start de achtergrondthread die metingen wegschrijft.

    Bij `flask run` met automatisch herladen start Werkzeug twee processen; de
    thread hoort alleen in het proces dat de app echt bedient.
    """
    if os.environ.get("GK_DISABLE_SAMPLER", "").lower() in {"1", "true", "ja"}:
        app.logger.info("Meetgeschiedenis staat uit (GK_DISABLE_SAMPLER).")
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    sampler = SensorSampler(
        database_path=app.config["DATABASE_PATH"],
        reader=app.extensions["sensor_reader"],
        interval_seconds=app.config["SAMPLE_INTERVAL_SECONDS"],
        retention_days=app.config["HISTORY_RETENTION_DAYS"],
    )
    sampler.start()
    app.extensions["sampler"] = sampler
    atexit.register(sampler.stop)
