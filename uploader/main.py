import logging
from tkinterdnd2 import TkinterDnD
from .gui.main_window import App
from .utils.logging import setup_logging

if __name__ == "__main__":
    setup_logging()

    # Create tkinterdnd2-aware root window (hidden - it's just for enabling dnd)
    root = TkinterDnD.Tk()
    root.withdraw()  # Hide the root window

    # Create our main application window as a child of the root
    app = App(master=root)

    # Start the main event loop
    app.mainloop()
