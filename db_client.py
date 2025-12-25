# db_client.py
import pymysql
from typing import Dict
from config import AppConfig


def _connect(cfg: AppConfig):
    """
    Membuat koneksi MySQL.
    Catatan: error 'Temporary failure in name resolution' biasanya dari cfg.DB_HOST (DNS/hostname),
    bukan dari JSON path.
    """
    return pymysql.connect(
        host=cfg.DB_HOST,
        user=cfg.DB_USER,
        password=cfg.DB_PASS,
        database=cfg.DB_NAME,
        # port=cfg.DB_PORT,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=8,
        read_timeout=15,
        write_timeout=15,
    )


def get_threshold(cfg: AppConfig, device_id: int) -> Dict[str, int]:
    """
    Ambil threshold NPK dari JSON versi BARU:
    $.device_configuration.threshold.{n,p,k}
    """
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
                raise RuntimeError(
                    "Konfigurasi tidak ditemukan. Pastikan configurations.device_id benar, "
                    "is_active=1, dan deleted_at NULL."
                )

            # Validasi: JSON harus punya path baru. Kalau NULL -> dianggap salah format.
            missing = [k for k in ("tn", "tp", "tk") if row.get(k) is None]
            if missing:
                raise RuntimeError(
                    "JSON format tidak sesuai (wajib versi baru). "
                    "Pastikan data_configuration memiliki path: "
                    "$.device_configuration.threshold.{n,p,k} "
                    f"(kolom NULL: {', '.join(missing)})."
                )

            return {
                "n": int(row["tn"]),
                "p": int(row["tp"]),
                "k": int(row["tk"]),
            }
    finally:
        conn.close()


def set_current(cfg: AppConfig, device_id: int, n: int, p: int, k: int) -> int:
    """
    Set current NPK ke JSON versi BARU:
    $.device_configuration.current.{n,p,k}
    """
    sql = """
    UPDATE configurations
    SET data_configuration =
      JSON_SET(
        data_configuration,
        '$.device_configuration.current.n', CAST(%s AS UNSIGNED),
        '$.device_configuration.current.p', CAST(%s AS UNSIGNED),
        '$.device_configuration.current.k', CAST(%s AS UNSIGNED)
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
            if cur.rowcount == 0:
                raise RuntimeError(
                    "Update gagal (0 rows). Pastikan device_id benar, is_active=1, dan deleted_at NULL."
                )
            return cur.rowcount
    finally:
        conn.close()


def ensure_new_json_schema(cfg: AppConfig, device_id: int) -> None:
    """
    Opsional: validasi cepat bahwa JSON sudah versi BARU.
    Akan raise error kalau path baru tidak ada.
    """
    sql = """
    SELECT
      JSON_EXTRACT(data_configuration, '$.device_configuration') AS dc,
      JSON_EXTRACT(data_configuration, '$.device_configuration.threshold') AS th,
      JSON_EXTRACT(data_configuration, '$.device_configuration.current') AS cu
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
                raise RuntimeError("Konfigurasi tidak ditemukan untuk validasi schema.")
            if row["dc"] is None or row["th"] is None or row["cu"] is None:
                raise RuntimeError(
                    "Schema JSON belum versi baru. Wajib ada: "
                    "$.device_configuration, $.device_configuration.threshold, $.device_configuration.current"
                )
    finally:
        conn.close()
