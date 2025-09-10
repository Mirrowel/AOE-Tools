from .gui.main_window import App
from .utils.logging import setup_logging

def main():
    setup_logging()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()