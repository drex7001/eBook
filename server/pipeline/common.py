TRANSLATABLE_TEXT = {"heading", "paragraph", "list_item", "caption", "footnote"}


class Paused(Exception):
    """Raised inside a job when the user pressed pause; the job stops cleanly and can resume later."""
