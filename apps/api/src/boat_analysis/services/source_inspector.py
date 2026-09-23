from datetime import UTC, datetime

from sqlalchemy import inspect, text

from ..config import get_settings
from ..database import create_source_engine
from ..schemas import SourceColumn, SourceInspection, SourceTable


def inspect_source() -> SourceInspection:
    settings = get_settings()
    engine = create_source_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            database_name = connection.execute(text("SELECT current_database()")).scalar_one()
            inspector = inspect(connection)
            tables: list[SourceTable] = []
            for table_name in sorted(inspector.get_table_names(schema=settings.source_schema)):
                columns = inspector.get_columns(table_name, schema=settings.source_schema)
                pk = inspector.get_pk_constraint(table_name, schema=settings.source_schema)
                statistics = {
                    row.column_name: row
                    for row in connection.execute(
                        text(
                            """
                            SELECT attname AS column_name, null_frac, n_distinct
                            FROM pg_stats
                            WHERE schemaname = :schema_name AND tablename = :table_name
                            """
                        ),
                        {"schema_name": settings.source_schema, "table_name": table_name},
                    )
                }
                estimated_rows = connection.execute(
                    text(
                        """
                        SELECT GREATEST(c.reltuples::bigint, 0)
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = :schema_name AND c.relname = :table_name
                        """
                    ),
                    {"schema_name": settings.source_schema, "table_name": table_name},
                ).scalar_one_or_none()
                tables.append(
                    SourceTable(
                        schema_name=settings.source_schema,
                        table_name=table_name,
                        estimated_rows=estimated_rows,
                        columns=[
                            SourceColumn(
                                name=column["name"],
                                data_type=str(column["type"]),
                                nullable=column["nullable"],
                                null_fraction=(
                                    float(statistics[column["name"]].null_frac)
                                    if column["name"] in statistics
                                    else None
                                ),
                                distinct_estimate=(
                                    float(statistics[column["name"]].n_distinct)
                                    if column["name"] in statistics
                                    else None
                                ),
                            )
                            for column in columns
                        ],
                        primary_key=pk.get("constrained_columns") or [],
                    )
                )
            return SourceInspection(
                inspected_at=datetime.now(UTC),
                database_name=database_name,
                tables=tables,
            )
    finally:
        engine.dispose()
