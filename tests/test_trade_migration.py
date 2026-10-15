import importlib.util
import io
import os
os.environ.setdefault('SECRET_KEY', 'isolated-migration-test')
from pathlib import Path
import unittest
from sqlalchemy import create_engine, text, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations

path=Path(__file__).resolve().parents[1]/'migrations/versions/d8f1c3a6e902_trade_marketplace.py'
spec=importlib.util.spec_from_file_location('trade_migration',path)
migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)


class TradeMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_existing_rows_and_visibility_then_downgrade(self):
        engine=create_engine('sqlite://')
        with engine.begin() as connection:
            for table in ['users','groups','members','photos','user_photo_images']:
                connection.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE want_shares (id INTEGER PRIMARY KEY, is_public BOOLEAN NOT NULL)'))
            connection.execute(text('INSERT INTO want_shares VALUES (1, 1), (2, 0)'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                self.assertEqual(connection.execute(text('SELECT id,is_public,want_public FROM want_shares ORDER BY id')).all(),[(1,1,1),(2,0,0)])
                self.assertIn('trade_proposals',inspect(connection).get_table_names())
                self.assertIn('want_members',inspect(connection).get_table_names())
                migration.downgrade()
            self.assertNotIn('trade_proposals',inspect(connection).get_table_names())
            self.assertEqual(connection.execute(text('SELECT * FROM want_shares ORDER BY id')).all(),[(1,1),(2,0)])
        engine.dispose()

    def test_postgres_sql_generation_has_constraints_and_no_legacy_data_deletion(self):
        output=io.StringIO()
        context=MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})
        with Operations.context(context): migration.upgrade()
        sql=output.getvalue()
        self.assertIn('CREATE TABLE trade_listings',sql)
        self.assertIn('ON DELETE SET NULL',sql)
        self.assertNotIn('DROP TABLE',sql)
        self.assertNotIn('DELETE FROM',sql)


if __name__=='__main__': unittest.main()
