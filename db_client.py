import pymysql
from typing import Dict
from config import AppConfig

def _connect(cfg: AppConfig, database: str = None, use_write_creds: bool = False):
  """Create a DB connection.

  If `database` provided, use it. If `use_write_creds` is True, use the
  DB_WRITE_* credentials from cfg (falling back to DB_* when empty).
  """
  if use_write_creds:
    host = cfg.DB_WRITE_HOST or cfg.DB_HOST
    user = cfg.DB_WRITE_USER or cfg.DB_USER
    password = cfg.DB_WRITE_PASS or cfg.DB_PASS
    port = cfg.DB_WRITE_PORT or cfg.DB_PORT
    db = database or cfg.DB_WRITE_NAME or cfg.DB_NAME
  else:
    host = cfg.DB_HOST
    user = cfg.DB_USER
    password = cfg.DB_PASS
    port = cfg.DB_PORT
    db = database or cfg.DB_NAME

  return pymysql.connect(
    host=host,
    user=user,
    password=password,
    database=db,
    port=port,
    autocommit=True,
    cursorclass=pymysql.cursors.DictCursor,
  )

def get_threshold(cfg: AppConfig, device_id: int) -> Dict[str, int]:
    sql = """
    SELECT
      JSON_UNQUOTE(JSON_EXTRACT(data_configuration, '$.device_configuration.threshold.n')) AS tn,
      JSON_UNQUOTE(JSON_EXTRACT(data_configuration, '$.device_configuration.threshold.p')) AS tp,
      JSON_UNQUOTE(JSON_EXTRACT(data_configuration, '$.device_configuration.threshold.k')) AS tk
    FROM configurations
    WHERE device_id = %s
      AND is_active = 1
      AND deleted_at IS NULL
    ORDER BY id DESC
    LIMIT 1;
    """
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (device_id,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Threshold tidak ditemukan (cek configurations.is_active=1).")
            return {
                "n": int(row["tn"]) if row["tn"] is not None else 0,
                "p": int(row["tp"]) if row["tp"] is not None else 0,
                "k": int(row["tk"]) if row["tk"] is not None else 0,
            }
    finally:
        conn.close()

def set_current(cfg: AppConfig, device_id: int, n: int, p: int, k: int) -> int:
    sql = """
    UPDATE configurations
    SET data_configuration =
      JSON_SET(
        data_configuration,
        '$.device_configuration.current.n', %s,
        '$.device_configuration.current.p', %s,
        '$.device_configuration.current.k', %s
      ),
      updated_at = NOW()
    WHERE device_id = %s
      AND is_active = 1
      AND deleted_at IS NULL;
    """
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (n, p, k, device_id))
            return cur.rowcount
    finally:
        conn.close()

def log_malnutrisi(cfg: AppConfig, device_id: int, database: str = None) -> int:
    """Insert a malnutrisi event timestamp into pump_nutrisi_log in given database.

    If `database` is None the connection will use cfg.DB_NAME.
    Returns last insert id.
    """
    sql = """
    INSERT INTO pump_nutrisi_log (event_time, device)
    VALUES (NOW(), %s);
    """
    # Use write credentials when logging events (safer to use a write-only user)
    conn = _connect(cfg, database, use_write_creds=True)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (device_id,))
            return cur.lastrowid
    finally:
        conn.close()
