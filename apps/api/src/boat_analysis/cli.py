import argparse
import json
from datetime import date

from .services.importer import run_import
from .services.source_inspector import inspect_source


def main() -> None:
    parser = argparse.ArgumentParser(description="Boat analysis administration")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("inspect-source", help="Inspect source PostgreSQL schema")
    import_parser = subcommands.add_parser("import-source", help="Import data using source mapping")
    import_parser.add_argument(
        "--date-from",
        type=date.fromisoformat,
        help="Only import races on or after this date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    if args.command == "inspect-source":
        print(json.dumps(inspect_source().model_dump(mode="json"), ensure_ascii=False, indent=2))
    elif args.command == "import-source":
        batch = run_import(args.date_from)
        print(
            json.dumps(
                {
                    "batch_id": str(batch.id),
                    "status": batch.status.value,
                    "rows_read": batch.rows_read,
                    "rows_written": batch.rows_written,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
