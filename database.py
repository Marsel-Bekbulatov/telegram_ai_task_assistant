# database.py
import sqlite3
from datetime import datetime, timezone 
import logging
import zoneinfo 

DATABASE_NAME = 'tasks.db'

logger = logging.getLogger(__name__)

NOTIFICATION_INTERVAL_KEYS = [
    'notified_24h', 'notified_12h', 'notified_6h',
    'notified_3h', 'notified_1h', 'notified_15m',
    'notified_final_due'
]

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES) 
    conn.row_factory = sqlite3.Row
    
    sqlite3.register_adapter(datetime, lambda dt: dt.astimezone(timezone.utc).isoformat())
  
    return conn

def table_has_column(cursor, table_name, column_name):
    """Checks if a table has a specific column."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row['name'] for row in cursor.fetchall()]
    return column_name in columns

def init_db():
    """Initializes the database and ensures tables have all required columns."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                due_date TEXT, -- Store as ISO formatted UTC string
                status TEXT NOT NULL DEFAULT 'pending',
                added_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

        for col_name in NOTIFICATION_INTERVAL_KEYS:
             if not table_has_column(cursor, 'tasks', col_name):
                 cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} BOOLEAN DEFAULT FALSE")
                 logger.info(f"Added missing column '{col_name}' to tasks table.")
                 conn.commit()

        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                timezone TEXT DEFAULT 'UTC' NOT NULL -- Store IANA timezone name
            )
        ''')
        conn.commit()
        logger.info("Checked/Created 'users' table.")

        
        if table_has_column(cursor, 'tasks', 'notified') and not table_has_column(cursor, 'tasks', 'notified_final_due'):
             try:
                 cursor.execute("ALTER TABLE tasks RENAME COLUMN notified TO notified_final_due")
                 logger.info("Renamed old 'notified' column to 'notified_final_due'.")
                 conn.commit()
             except sqlite3.OperationalError as e:
                 logger.warning(f"Could not rename 'notified' column: {e}")
                 if not table_has_column(cursor, 'tasks', 'notified_final_due'):
                      cursor.execute(f"ALTER TABLE tasks ADD COLUMN notified_final_due BOOLEAN DEFAULT FALSE")
                      conn.commit()
        elif not table_has_column(cursor, 'tasks', 'notified_final_due'):
            cursor.execute(f"ALTER TABLE tasks ADD COLUMN notified_final_due BOOLEAN DEFAULT FALSE")
            logger.info(f"Added missing column 'notified_final_due'.")
            conn.commit()

        logger.info("Database initialization and schema check complete.")

    except sqlite3.Error as e:
        logger.error(f"Database initialization/alteration error: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()



def set_user_timezone(user_id: int, timezone_str: str):
    """Sets or updates the user's timezone preference."""
    
    try:
        zoneinfo.ZoneInfo(timezone_str) 
    except zoneinfo.ZoneInfoNotFoundError:
        logger.error(f"Invalid timezone string '{timezone_str}' provided for user {user_id}.")
        return False

    sql = "INSERT INTO users (user_id, timezone) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (user_id, timezone_str))
        conn.commit()
        logger.info(f"Set timezone for user {user_id} to '{timezone_str}'.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error setting timezone for user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_timezone_str(user_id: int) -> str:
    """Gets the user's timezone string, defaulting to UTC if not set or user not found."""
    sql = "SELECT timezone FROM users WHERE user_id = ?"
    default_tz = 'UTC'
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (user_id,))
        result = cursor.fetchone()
        if result:
            
            try:
                zoneinfo.ZoneInfo(result['timezone'])
                return result['timezone']
            except zoneinfo.ZoneInfoNotFoundError:
                 logger.warning(f"User {user_id} has invalid timezone '{result['timezone']}' stored, defaulting to {default_tz}")
                 return default_tz
        else:
            
            return default_tz
    except sqlite3.Error as e:
        logger.error(f"Error getting timezone for user {user_id}: {e}")
        return default_tz 
    finally:
        if conn:
            conn.close()

def add_task(user_id: int, chat_id: int, description: str, due_date_utc: datetime = None):
    """Adds a new task to the database. Expects due_date_utc to be timezone-aware UTC."""
    
    due_date_str = due_date_utc.isoformat() if due_date_utc else None

    sql = ''' INSERT INTO tasks(user_id, chat_id, description, due_date, status,
                                notified_24h, notified_12h, notified_6h, notified_3h,
                                notified_1h, notified_15m, notified_final_due)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?) '''
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(sql, (user_id, chat_id, description, due_date_str, 'pending',
                              False, False, False, False, False, False, False))
        conn.commit()
        task_id = cursor.lastrowid
        logger.info(f"Task added for user {user_id} with ID {task_id}. Due (UTC): {due_date_str}")
        return task_id
    except sqlite3.Error as e:
        logger.error(f"Error adding task for user {user_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def get_user_tasks(user_id: int, status: str = 'pending'):
    """Retrieves tasks for a specific user based on status."""
    
    sql = "SELECT * FROM tasks WHERE user_id = ? AND status = ? ORDER BY due_date ASC, added_date ASC"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (user_id, status))
        tasks = cursor.fetchall()
        return tasks
    except sqlite3.Error as e:
        logger.error(f"Error fetching tasks for user {user_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_task_by_id(task_id: int, user_id: int):
    """Retrieves a specific task by its ID for a specific user."""
    
    sql = "SELECT * FROM tasks WHERE id = ? AND user_id = ?"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (task_id, user_id))
        task = cursor.fetchone()
        return task
    except sqlite3.Error as e:
        logger.error(f"Error fetching task ID {task_id} for user {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_pending_tasks_with_due_dates():
    """Retrieves all pending tasks that have a due date set, JOINING user's timezone."""
    
    sql = """
        SELECT t.*, COALESCE(u.timezone, 'UTC') as user_timezone
        FROM tasks t
        LEFT JOIN users u ON t.user_id = u.user_id
        WHERE t.status = 'pending'
        AND t.due_date IS NOT NULL
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        tasks = cursor.fetchall()
        return tasks
    except sqlite3.Error as e:
        logger.error(f"Error fetching pending tasks with due dates and timezones: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_task_status(task_id: int, user_id: int, status: str = 'done'):
    """Updates the status of a task ('done' or 'pending')."""
    sql = "UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        rows_affected = cursor.execute(sql, (status, task_id, user_id)).rowcount
        conn.commit()
        if rows_affected > 0:
            logger.info(f"Task ID {task_id} status updated to '{status}' for user {user_id}.")
            return True
        else:
        
            return False 
    except sqlite3.Error as e:
        logger.error(f"Error updating status for task ID {task_id}, user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_task(task_id: int, user_id: int):
    """Deletes a task from the database."""
    sql = "DELETE FROM tasks WHERE id = ? AND user_id = ?"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        rows_affected = cursor.execute(sql, (task_id, user_id)).rowcount
        conn.commit()
        if rows_affected > 0:
            logger.info(f"Task ID {task_id} deleted for user {user_id}.")
            return True
        else:
            
            return False 
    except sqlite3.Error as e:
        logger.error(f"Error deleting task ID {task_id} for user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def mark_specific_notification_sent(task_id: int, interval_key: str):
    """Marks a specific notification interval flag as TRUE for a task."""
    if interval_key not in NOTIFICATION_INTERVAL_KEYS:
        logger.error(f"Invalid interval key '{interval_key}' provided for task {task_id}.")
        return False

    sql = f"UPDATE tasks SET {interval_key} = TRUE WHERE id = ?"
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (task_id,))
        conn.commit()
        rows_affected = cursor.rowcount
        if rows_affected > 0:
             logger.info(f"Marked notification '{interval_key}' as sent for task ID {task_id}.")
             return True
        else:
             
             return False 
    except sqlite3.Error as e:
        logger.error(f"Error marking notification '{interval_key}' for task ID {task_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()