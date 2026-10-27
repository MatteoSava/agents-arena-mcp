class ArenaError(RuntimeError):
    """A user-facing error: bad input, missing arena, failed git operation."""


class Cancelled(ArenaError):
    """The arena was stopped (Ctrl-C, SIGTERM, or the server shutting down)."""
