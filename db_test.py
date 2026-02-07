from config import AppConfig
from db_client import log_malnutrisi
import traceback

def main():
    cfg = AppConfig()
    print(f"Using DB host={cfg.DB_HOST} name={cfg.DB_NAME} user={cfg.DB_USER} port={cfg.DB_PORT} device={cfg.DEVICE_ID}")
    try:
        # Ensure we write to the intended database (override if env/config points elsewhere)
        rowid = log_malnutrisi(cfg, cfg.DEVICE_ID, database="inosakti_logaeronutrien")
        print("Inserted pump_nutrisi_log id:", rowid)
    except Exception as e:
        print("ERROR during DB insert:")
        traceback.print_exc()
        print("Attempting direct pymysql connection using provided credentials...")
        try:
            import pymysql
            conn = pymysql.connect(
                host="inosakti.com",
                user="inosakti_aeronutrienuser",
                password="aeronutrienuser2026",
                database="inosakti_logaeronutrien",
                port=3306,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
            with conn.cursor() as cur:
                cur.execute("INSERT INTO pump_nutrisi_log (event_time, device) VALUES (NOW(), %s)", (cfg.DEVICE_ID,))
                print("Direct insert id:", cur.lastrowid)
        except Exception:
            print("Direct connection attempt failed:")
            traceback.print_exc()

if __name__ == '__main__':
    main()
