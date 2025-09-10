from .gui.main_window import App
from .utils.logging import setup_logging

def main():
    setup_logging()
    app = App()
    app.mainloop()

# This block is removed to prevent execution when imported.
# The entry point is now handled by the runner script.