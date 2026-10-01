from pathlib import Path

import pglast

for f in sorted(Path("samples").glob("*.sql")):
    sql = f.read_text(encoding="utf-8")
    try:
        pglast.parse_sql(sql)
        if f.name == "00_schema.sql":
            print(f"OK  {f.name}  (schema)")
        else:
            pglast.parse_plpgsql(sql)
            print(f"OK  {f.name}  (sql + plpgsql)")
    except Exception as e:
        print(f"ERRO {f.name}: {e}")