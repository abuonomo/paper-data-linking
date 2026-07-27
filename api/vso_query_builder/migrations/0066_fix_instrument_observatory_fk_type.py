"""Fix instrument.observatory_id column type.

Migration 0050 changed Observatory's PK from slug (varchar) to UUID but
when Django replays all migrations on a fresh database (e.g. test DB),
the FK column on Instrument stays varchar.  This migration explicitly
drops dependent constraints/indexes, recasts the column to uuid, and
recreates the unique constraint.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vso_query_builder", "0065_delete_instrumentsourcelookup_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            DECLARE
                con_name text;
                idx_name text;
            BEGIN
                -- Only fix if observatory_id is still varchar
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'vso_query_builder_instrument'
                      AND column_name = 'observatory_id'
                      AND data_type = 'character varying'
                ) THEN
                    -- Drop constraints that reference observatory_id
                    FOR con_name IN
                        SELECT tc.constraint_name
                        FROM information_schema.constraint_column_usage ccu
                        JOIN information_schema.table_constraints tc
                            ON tc.constraint_name = ccu.constraint_name
                            AND tc.table_schema = ccu.table_schema
                        WHERE ccu.table_name = 'vso_query_builder_instrument'
                          AND ccu.column_name = 'observatory_id'
                          AND tc.constraint_type IN ('UNIQUE', 'FOREIGN KEY')
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE vso_query_builder_instrument DROP CONSTRAINT IF EXISTS %I',
                            con_name
                        );
                    END LOOP;

                    -- Drop plain indexes on observatory_id
                    FOR idx_name IN
                        SELECT i.relname
                        FROM pg_index ix
                        JOIN pg_class i ON i.oid = ix.indexrelid
                        JOIN pg_attribute a ON a.attrelid = ix.indrelid
                            AND a.attnum = ANY(ix.indkey)
                        WHERE ix.indrelid = 'vso_query_builder_instrument'::regclass
                          AND a.attname = 'observatory_id'
                          AND NOT ix.indisprimary
                          AND NOT ix.indisunique
                    LOOP
                        EXECUTE format('DROP INDEX IF EXISTS %I', idx_name);
                    END LOOP;

                    -- Recast the column
                    ALTER TABLE vso_query_builder_instrument
                        ALTER COLUMN observatory_id TYPE uuid
                        USING observatory_id::uuid;

                    -- Recreate the unique constraint (observatory, short_name)
                    ALTER TABLE vso_query_builder_instrument
                        ADD CONSTRAINT vso_query_builder_instrument_observatory_short_name_uniq
                        UNIQUE (observatory_id, short_name);

                    -- Recreate FK constraint
                    ALTER TABLE vso_query_builder_instrument
                        ADD CONSTRAINT vso_query_builder_instrument_observatory_id_fk
                        FOREIGN KEY (observatory_id)
                        REFERENCES vso_query_builder_observatory (id)
                        ON DELETE CASCADE
                        DEFERRABLE INITIALLY DEFERRED;

                    -- Recreate standard btree index
                    CREATE INDEX IF NOT EXISTS vso_query_builder_instrument_observatory_id_idx
                        ON vso_query_builder_instrument (observatory_id);
                END IF;
            END
            $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
