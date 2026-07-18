"""Lambda entrypoint for the chat/memory API, via Mangum ASGI adapter."""
from mangum import Mangum

from app.main import app

handler = Mangum(app)
