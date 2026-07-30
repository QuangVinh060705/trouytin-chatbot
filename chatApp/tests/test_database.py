import unittest

from core.database import _from_dotnet_connection_string


class DatabaseConfigTests(unittest.TestCase):
    def test_converts_npgsql_connection_string(self):
        dsn = _from_dotnet_connection_string(
            "Host=db;Port=5432;Database=postgres;Username=app;"
            "Password=p@ss;SSL Mode=Require"
        )
        self.assertIn("host='db'", dsn)
        self.assertIn("port='5432'", dsn)
        self.assertIn("dbname='postgres'", dsn)
        self.assertIn("user='app'", dsn)
        self.assertIn("password='p@ss'", dsn)
        self.assertIn("sslmode='require'", dsn)


if __name__ == "__main__":
    unittest.main()
