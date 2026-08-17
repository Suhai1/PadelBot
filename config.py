"""
Central place for app configuration.

Nothing in this file talks to Flask, the AI model, or the racket data.
Its only job is: read environment variables and hand them back as plain
Python values that other files can import.

Why this matters: if API keys or settings were scattered across app.py,
routes.py, and ai.py, changing one value would mean hunting through
multiple files. Here there is exactly one place to look.
"""

import os

# python-dotenv reads a .env file (if one exists) and copies its contents
# into the real environment variables for this process, as if you had
# typed `export GEMINI_API_KEY=...` in the terminal yourself.
#
# In production you would not have a .env file at all - the hosting
# platform (e.g. Render, Railway) injects real environment variables
# directly, and load_dotenv() just does nothing in that case.
from dotenv import load_dotenv

load_dotenv()


class Config:
    """
    Groups all settings as class attributes so other files can do:

        from config import Config
        Config.GEMINI_API_KEY

    instead of calling os.environ.get(...) all over the codebase.
    """

    # os.environ.get(name, default) reads an environment variable.
    # If GEMINI_API_KEY is not set at all, this becomes None rather than
    # crashing immediately - we deliberately let the app start so error
    # messages about a missing key can be clear and happen where the key
    # is actually used, not as a cryptic import-time failure.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

    # Flask uses this to cryptographically sign session cookies (the
    # cookie that remembers a user's chat history between requests).
    # A default is provided ONLY so the app can run locally without a
    # .env file for a quick smoke test - it is not safe to deploy with
    # this default, which is why the real one belongs in .env.
    FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-insecure-key")

    # Controls Flask's debug mode. Debug mode gives detailed error pages
    # and auto-reloads the server on code changes - useful locally,
    # dangerous in production because those error pages can leak source
    # code and environment details to anyone who triggers an error.
    FLASK_ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = FLASK_ENV == "development"

    # Render (and most hosts) assign a port dynamically and tell the
    # app which one via the PORT environment variable - it is not
    # something we get to pick. Defaulting to 5000 keeps `python app.py`
    # working unchanged for local development, where nothing sets PORT.
    # Note this only matters for app.py's own `app.run()` fallback -
    # the real production process is gunicorn, which reads $PORT
    # directly from the shell in its own start command (see the
    # render.yaml note on that), not through this class. It's defined
    # here anyway so there is still exactly one place that knows how
    # the port is chosen, matching every other setting in this file.
    PORT = int(os.environ.get("PORT", 5000))

    # Path to the racket catalogue CSV, built from this file's own
    # location rather than a relative path like "data/rackets.csv".
    # A relative path breaks depending on which directory you happen to
    # run `python app.py` from; os.path.dirname(__file__) always points
    # at this file's folder regardless of the current working directory.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CATALOGUE_PATH = os.path.join(BASE_DIR, "data", "rackets_catalogue.csv")
