import json
import os
import sys
from typing import Dict


def resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class Localization:
    def __init__(self, locale_dir: str, default_lang: str = "en"):
        self.locale_dir = locale_dir
        self.default_lang = default_lang
        self.current_lang = default_lang
        self.translations: Dict[str, str] = {}
        self._load_language(self.default_lang)

    def _load_language(self, lang: str):
        """Loads a language file into memory."""
        self.translations = {}
        file_path = os.path.join(self.locale_dir, f"{lang}.json")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.translations = json.load(f)
            self.current_lang = lang
        except (FileNotFoundError, json.JSONDecodeError):
            # Fallback to default language if the selected one fails to load
            if lang != self.default_lang:
                self._load_language(self.default_lang)

    def set_language(self, lang: str):
        """Sets the active language."""
        self._load_language(lang)

    def get(self, key: str, **kwargs) -> str:
        """
        Gets a translated string by its key.
        Supports simple placeholder substitution.
        e.g., get("welcome_message", name="User")
        """
        message = self.translations.get(key, key)
        if kwargs:
            try:
                message = message.format(**kwargs)
            except KeyError:
                # In case a placeholder is missing in the translation string
                pass
        return message

# Global instance to be configured by each application
translator = None

def init_translator(locale_dir: str, default_lang: str = "en"):
    """Initializes the global translator instance."""
    global translator
    resolved_locale_dir = resource_path(locale_dir)
    translator = Localization(resolved_locale_dir, default_lang)
    return translator

def get_translator() -> Localization:
    """Returns the global translator instance."""
    if not translator:
        raise RuntimeError("Translator has not been initialized. Call init_translator() first.")
    return translator
