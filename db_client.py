import pymysql
from typing import Dict
from config import AppConfig

def _connect(cfg: AppConfig):
    return pymysql.connect(
        host=cfg.DB_HOST,
        user=cfg.DB_USER,
        password=cfg.DB_PASS,
        database=cfg.DB_NAME,
        port=cfg.DB_PORT,
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
