"""MySQL backend for local development against XAMPP's MariaDB 10.4.

Django 5.2 requires MariaDB 10.5+. Production runs MySQL 8, so this backend only relaxes
the version check and turns off the one 10.5 feature Django relies on (RETURNING).
Select it with DATABASE_ENGINE=sst.db_mysql_legacy in .env.
"""
from django.db.backends.mysql import base, features


class DatabaseFeatures(features.DatabaseFeatures):
    can_return_columns_from_insert = False
    can_return_rows_from_bulk_insert = False

    @property
    def minimum_database_version(self):
        return (10, 4) if self.connection.mysql_is_mariadb else (8, 0, 11)


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
