# Scripts

Standalone scripts and generated outputs for the Good-Driving-Incentive-Program.

## Scripts

- **update_migrations.py** – Generates a new migration from current SQLAlchemy models (compares models with DB).
  ```bash
  python scripts/update_migrations.py
  python scripts/update_migrations.py -m "Add new column"
  ```
  Outputs: new file in `migrations/versions/`

- **dump_project.py** – Dumps Flask app code, mobile app files, and database schema to text files.
  ```bash
  python scripts/dump_project.py
  ```
  Outputs: `database_schema.txt`, `project_files.txt`, `mobile_app_files.txt`

- **fetch_ebay_categories.py** – Fetches eBay category tree from the Taxonomy API.
  ```bash
  python scripts/fetch_ebay_categories.py
  ```
  Outputs: `ebay_categories_tree.json`, `ebay_categories_flat.json`, etc.

## Output Files

- `project_files.txt` – Flask app code dump
- `mobile_app_files.txt` – Mobile app code dump
- `database_schema.txt` – Database schema
- `ebay_categories_tree.json` – eBay category tree (used by Flask app at runtime)

## Run from project root

All scripts expect to be run from the project root directory.
