# dump_project.py
from pathlib import Path
import sys
import os
from typing import Dict, List, Tuple
from collections import defaultdict

# --- Paths / constants ---
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
FLASK_DIR = PROJECT_ROOT / "flask"
APP_DIR = FLASK_DIR / "app"
SCHEMA_OUTPUT = SCRIPT_DIR / "database_schema.txt"
CODE_OUTPUT = SCRIPT_DIR / "project_files.txt"
MOBILE_OUTPUT = SCRIPT_DIR / "mobile_app_files.txt"
EXTS = {".py", ".html"}

# --- DB connection helpers ---
def _load_env():
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(FLASK_DIR / ".env")
    except Exception:
        pass

def _import_config_uri() -> str | None:
    try:
        sys.path.insert(0, str(FLASK_DIR))
        import config  # type: ignore
        uri = getattr(config, "SQLALCHEMY_DATABASE_URI", None)
        if not uri and hasattr(config, "Config"):
            uri = getattr(config.Config, "SQLALCHEMY_DATABASE_URI", None)
        return uri
    except Exception:
        return None

def _env_mysql_uri() -> Tuple[str | None, str | None]:
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST")
    user = os.getenv("DB_USER") or os.getenv("MYSQL_USER") or os.getenv("DB_USERNAME")
    pwd  = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD")
    name = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or os.getenv("MYSQL_DB")
    port = os.getenv("DB_PORT") or os.getenv("MYSQL_PORT") or "3306"
    if host and user and pwd and name:
        uri = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}"
        return uri, name
    return None, None

def _parse_db_name_from_uri(uri: str) -> str | None:
    try:
        after_slash = uri.split("/", 3)[-1]
        db = after_slash.split("?", 1)[0]
        return db or None
    except Exception:
        return None

def _get_engine_and_dbname():
    _load_env()
    uri = _import_config_uri()
    db_name = None
    if uri:
        db_name = _parse_db_name_from_uri(uri)

    if not uri or not db_name:
        uri2, name2 = _env_mysql_uri()
        if uri2 and name2:
            uri, db_name = uri2, name2

    if not uri or not db_name:
        raise RuntimeError(
            "Could not determine DB connection.\n"
            "Provide SQLALCHEMY_DATABASE_URI in config.py or set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME in .env."
        )

    from sqlalchemy import create_engine  # type: ignore
    engine = create_engine(uri, pool_pre_ping=True)
    return engine, db_name

# --- Schema fetch ---
def fetch_schema(engine, db_name: str) -> Dict[str, Dict]:
    from sqlalchemy import text  # type: ignore
    schema: Dict[str, Dict] = defaultdict(lambda: {"comment": "", "columns": []})

    q_tables = text("""
        SELECT TABLE_NAME, TABLE_COMMENT
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = :db
        ORDER BY TABLE_NAME;
    """)
    q_cols = text("""
        SELECT
            TABLE_NAME,
            COLUMN_NAME,
            DATA_TYPE,
            COLUMN_TYPE,
            IS_NULLABLE,
            COLUMN_KEY,
            COLUMN_DEFAULT,
            EXTRA,
            COLUMN_COMMENT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :db
        ORDER BY TABLE_NAME, ORDINAL_POSITION;
    """)
    q_fks = text("""
        SELECT
            TABLE_NAME,
            COLUMN_NAME,
            REFERENCED_TABLE_NAME,
            REFERENCED_COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = :db
          AND REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY TABLE_NAME, COLUMN_NAME;
    """)

    with engine.connect() as conn:
        for row in conn.execute(q_tables, {"db": db_name}):
            schema[row[0]]["comment"] = row[1] or ""
        for row in conn.execute(q_cols, {"db": db_name}):
            tname, col, dtype, ctype, nullable, ckey, cdef, extra, ccomment = row
            schema[tname]["columns"].append({
                "name": col,
                "data_type": dtype,
                "column_type": ctype,
                "is_nullable": nullable,
                "column_key": ckey,
                "column_default": cdef,
                "extra": extra,
                "comment": ccomment or "",
                "referenced_table": None,
                "referenced_column": None,
            })
        fk_map = {}
        for row in conn.execute(q_fks, {"db": db_name}):
            fk_map[(row[0], row[1])] = (row[2], row[3])
        for tname, tdef in schema.items():
            for col in tdef["columns"]:
                key = (tname, col["name"])
                if key in fk_map:
                    col["referenced_table"], col["referenced_column"] = fk_map[key]

    return schema

# --- Render Markdown ---
def render_schema_markdown(schema: Dict[str, Dict], db_name: str) -> str:
    lines: List[str] = []
    lines.append(f"## Database Schema: `{db_name}`\n")
    if not schema:
        lines.append("[No tables found]\n")
        return "\n".join(lines) + "\n"
    for tname in sorted(schema.keys()):
        lines.append(f"### {tname}")
        if schema[tname]["comment"]:
            lines.append(f"*Comment:* {schema[tname]['comment']}")
        lines.append("")
        header = [
            "Column", "Type", "Data Type", "Nullable", "Key",
            "Default", "Extra", "Comment", "FK → Table.Column"
        ]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for col in schema[tname]["columns"]:
            fk = ""
            if col["referenced_table"] and col["referenced_column"]:
                fk = f"{col['referenced_table']}.{col['referenced_column']}"
            row = [
                col["name"] or "",
                col["column_type"] or "",
                col["data_type"] or "",
                col["is_nullable"] or "",
                col["column_key"] or "",
                "" if col["column_default"] is None else str(col["column_default"]),
                col["extra"] or "",
                col["comment"].replace("\n", " ").strip() if col["comment"] else "",
                fk
            ]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"

# --- Code dump ---
def dump_code_blocks(out):
    count = 0
    # include files in app/ recursively
    for p in sorted(APP_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in EXTS:
            rel = p.relative_to(FLASK_DIR).as_posix()
            lang = "python" if p.suffix.lower() == ".py" else "html"
            out.write(f"\n\n===== {rel} =====\n\n```{lang}\n")
            out.write(p.read_text(encoding="utf-8", errors="replace"))
            out.write("\n```\n")
            count += 1
    # include top-level flask .py files (config, run, etc.)
    for p in sorted(FLASK_DIR.glob("*.py")):
        if p.name != "dump_project.py":
            rel = p.relative_to(FLASK_DIR).as_posix()
            out.write(f"\n\n===== {rel} =====\n\n```python\n")
            out.write(p.read_text(encoding="utf-8", errors="replace"))
            out.write("\n```\n")
            count += 1

    return count

def dump_mobile_files():
    """Dump mobile app files separately"""
    mobile_app_dir = PROJECT_ROOT / "mobileApplication" / "app" / "src" / "main"

    if not mobile_app_dir.exists():
        print(f"[WARNING] Mobile app directory not found at: {mobile_app_dir}")
        return 0

    count = 0

    # Mobile Kotlin source files
    mobile_kotlin_dir = mobile_app_dir / "java" / "com" / "example" / "driverrewards"
    if mobile_kotlin_dir.exists():
        with MOBILE_OUTPUT.open("w", encoding="utf-8") as out:
            out.write("# Mobile Application Files\n\n")

            for p in sorted(mobile_kotlin_dir.rglob("*.kt")):
                rel = p.relative_to(PROJECT_ROOT).as_posix()
                out.write(f"\n\n===== {rel} =====\n\n```kotlin\n")
                out.write(p.read_text(encoding="utf-8", errors="replace"))
                out.write("\n```\n")
                count += 1

            # Mobile XML layout files
            mobile_res_dir = mobile_app_dir / "res"
            important_dirs = ["layout", "menu", "navigation", "xml", "values"]

            for dir_name in important_dirs:
                xml_dir = mobile_res_dir / dir_name
                if xml_dir.exists():
                    for p in sorted(xml_dir.rglob("*.xml")):
                        rel = p.relative_to(PROJECT_ROOT).as_posix()
                        out.write(f"\n\n===== {rel} =====\n\n```xml\n")
                        out.write(p.read_text(encoding="utf-8", errors="replace"))
                        out.write("\n```\n")
                        count += 1

            # Mobile drawable XML files
            drawable_dir = mobile_res_dir / "drawable"
            if drawable_dir.exists():
                for p in sorted(drawable_dir.rglob("*.xml")):
                    rel = p.relative_to(PROJECT_ROOT).as_posix()
                    out.write(f"\n\n===== {rel} =====\n\n```xml\n")
                    out.write(p.read_text(encoding="utf-8", errors="replace"))
                    out.write("\n```\n")
                    count += 1

            # Mobile gradle files (build configuration)
            mobile_gradle_files = [
                PROJECT_ROOT / "mobileApplication" / "build.gradle.kts",
                PROJECT_ROOT / "mobileApplication" / "app" / "build.gradle.kts",
                PROJECT_ROOT / "mobileApplication" / "settings.gradle.kts",
                PROJECT_ROOT / "mobileApplication" / "gradle" / "libs.versions.toml",
            ]

            for gradle_file in mobile_gradle_files:
                if gradle_file.exists():
                    rel = gradle_file.relative_to(PROJECT_ROOT).as_posix()
                    lang = "toml" if gradle_file.suffix == ".toml" else "kotlin"
                    out.write(f"\n\n===== {rel} =====\n\n```{lang}\n")
                    out.write(gradle_file.read_text(encoding="utf-8", errors="replace"))
                    out.write("\n```\n")
                    count += 1

    return count

def main():
    if not APP_DIR.exists():
        print(f"[ERROR] app folder not found at: {APP_DIR}")
        sys.exit(1)

    # Write database schema to separate file
    try:
        engine, db_name = _get_engine_and_dbname()
        schema = fetch_schema(engine, db_name)
        schema_md = render_schema_markdown(schema, db_name)
    except Exception as e:
        schema_md = f"## Database Schema\n\n[Error introspecting database: {e}]\n\n"

    with SCHEMA_OUTPUT.open("w", encoding="utf-8") as out:
        out.write(schema_md)

    print(f"Wrote database schema to {SCHEMA_OUTPUT}")

    # Write Flask app file contents to separate file
    with CODE_OUTPUT.open("w", encoding="utf-8") as out:
        out.write("# Flask Application Files\n\n")
        count = dump_code_blocks(out)

    print(f"Wrote {count} Flask files to {CODE_OUTPUT}")

    # Write mobile app files to separate file
    mobile_count = dump_mobile_files()
    if mobile_count > 0:
        print(f"Wrote {mobile_count} mobile app files to {MOBILE_OUTPUT}")
    else:
        print(f"No mobile app files found")

if __name__ == "__main__":
    main()
