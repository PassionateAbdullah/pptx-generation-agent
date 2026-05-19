from pathlib import Path

from pptx_agent.config import load_settings
from pptx_agent.server import run_server


def main() -> None:
    root = Path(__file__).resolve().parent
    settings = load_settings(root)
    run_server(settings)


if __name__ == "__main__":
    main()

