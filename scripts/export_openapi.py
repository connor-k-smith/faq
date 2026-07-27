import json
import os
from pathlib import Path

os.environ["FAQ_ENVIRONMENT"] = "test"

from app.main import create_app  # noqa: I001


output = Path(__file__).parent.parent / "frontend" / "openapi.json"
output.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
