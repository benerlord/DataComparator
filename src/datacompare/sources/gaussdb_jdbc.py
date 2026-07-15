"""Placeholder — replaced with full implementation in Task 4."""
from .gaussdb import GaussDBDriver


class JdbcDriver(GaussDBDriver):
    def __init__(self, creds):
        self.creds = creds

    def connect(self):
        raise NotImplementedError

    def close(self):
        pass

    def columns_for(self, query):
        raise NotImplementedError

    def count_for(self, query):
        raise NotImplementedError

    def fetch_chunks(self, query, chunk_size):
        raise NotImplementedError
