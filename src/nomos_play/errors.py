"""Shared rejection codes for catalog, desktop control and HTTP transport."""


class TableError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)
