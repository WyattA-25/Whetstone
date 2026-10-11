"""AWS Lambda entry point: the same FastAPI app, adapted to Lambda Function URL events by Mangum."""
from mangum import Mangum

from .app import app

handler = Mangum(app, lifespan="off")
