class WordPressRouter:
    """The 'wordpress' connection is the source site: read-only, never migrated."""

    def db_for_write(self, model, **hints):
        return "default"

    def allow_migrate(self, db, app_label, **hints):
        return db != "wordpress"
