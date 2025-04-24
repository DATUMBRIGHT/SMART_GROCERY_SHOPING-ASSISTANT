import os
import yaml
import mysql.connector
from werkzeug.security import check_password_hash,generate_password_hash
from loggers.custom_logger import logger
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.path.join(os.path.dirname(__file__), '..')
CONFIG_PATH = os.path.join(BASE_URL, 'constants', 'config.yaml')
with open(CONFIG_PATH, 'r') as file:
    config = yaml.safe_load(file)
    DB_NAME = config['database']['name']
    HOST = config['database']['host']
    USER = config['database']['user']
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    PORT = config['database']['port']
    USERS_TABLE = config['database']['tables']['users']

DB_CONFIG = {
    'host': HOST,
    'user': USER,
    'password': DB_PASSWORD,
    'database': DB_NAME,
    'port': PORT
}

class DBManager:
    def __init__(self):
        pass  # Initialize connection pool here if you decide to use it
        # self.initialize_users_table() # Call this in your app startup instead

    def initialize_users_table(self):
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        try:
            query = f"""
            CREATE TABLE IF NOT EXISTS {USERS_TABLE} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                age INT,
                first_name VARCHAR(30),
                last_name VARCHAR(30),
                vegetarian BOOLEAN DEFAULT FALSE,
                vegan BOOLEAN DEFAULT FALSE,
                gluten_free BOOLEAN DEFAULT FALSE,
                allergies TEXT,
                extra_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
            cursor.execute(query)
            conn.commit()
            logger.info(f"Table '{USERS_TABLE}' created or already exists.")
        except mysql.connector.Error as err:
            logger.error(f"Error creating table '{USERS_TABLE}': {err}")
        finally:
            conn.close()

    def create_user(self, username, password, email, age=None, first_name=None, last_name=None, vegetarian=False, vegan=False, gluten_free=False, allergies=None,extra_info = None):

        password = generate_password_hash(password)
        if self.check_if_email_already_exists(email):
            logger.info(f"Email '{email}' already exists")
            raise ValueError(f"Email '{email}' already exists")
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        try:
            sql_insert = f"""
                INSERT INTO {USERS_TABLE} (username, password, email, age, first_name, last_name, vegetarian, vegan, gluten_free, allergies,extra_info)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,%s)
            """
            values = (username, password, email, age, first_name, last_name, vegetarian, vegan, gluten_free, allergies,extra_info)
            cursor.execute(sql_insert, values)
            conn.commit()
            user_id = cursor.lastrowid
            cursor.close()
            logger.info(f"User '{username}' created with ID: {user_id}")
            return user_id
        except mysql.connector.Error as err:
            logger.error(f"Error creating user '{username}': {err}")
            conn.rollback()
            raise RuntimeError(f"Error creating user '{username}': {err}")
        finally:
            conn.close()

    def check_if_email_already_exists(self, email):
        """ check if email is in db"""
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        try:
            query = f"SELECT * FROM {USERS_TABLE} WHERE email = %s"
            cursor.execute(query, (email,))
            result = cursor.fetchone()
            cursor.close()
            return bool(result)
        except mysql.connector.Error as err:
            logger.error(f"Error checking user with email '{email}': {err}")
            raise RuntimeError(f"Error checking user with email '{email}': {err}")
        finally:
            conn.close()

    def auth_user(self, email, password):
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        try:
            query = f"SELECT * FROM {USERS_TABLE} WHERE email = %s"
            cursor.execute(query, (email,))
            user = cursor.fetchone()
            cursor.close()

            if user and 'password' in user and check_password_hash(user['password'], password):
                logger.info(f"User with email '{email}' authenticated successfully.")
                return user['id']  
            else:
                logger.info(f"Authentication failed for email '{email}'.")
                return None
        except mysql.connector.Error as err:
            logger.error(f"Error during authentication for email '{email}': {err}")
            raise RuntimeError(f"Error during authentication: {err}")
        finally:
            conn.close()


    def fetch_user_by_email(self, email):
        """Fetch a user's details based on their email address."""
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        try:
            query = f"SELECT * FROM {USERS_TABLE} WHERE email = %s"
            cursor.execute(query, (email,))
            user = cursor.fetchone()
            cursor.close()
            if user:
                logger.info(f"User with email '{email}' fetched successfully.")
                return user
            else:
                logger.info(f"User with email '{email}' not found.")
                return None
        except mysql.connector.Error as err:
            logger.error(f"Error fetching user with email '{email}': {err}")
            raise RuntimeError(f"Error fetching user: {err}")
        finally:
            conn.close()


    def fetch_user_id(self,user_id):
            """Fetch a user's details based on their ID."""
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor(dictionary=True)
            try:
                query = f"SELECT * FROM {USERS_TABLE} WHERE id = %s"
                cursor.execute(query, (user_id, ))
                user = cursor.fetchone()
                cursor.close()
                if user:
                    logger.info(f"User with ID '{user_id}' fetched successfully.")
                    return user
                else:
                    logger.info(f"User with ID '{user_id}' not found.")
                    return None
            except mysql.connector.Error as err:
                logger.error(f"Error fetching user with ID '{user_id}': {err}")
                raise RuntimeError(f"Error fetching user: {err}")
            finally:
                conn.close()
    
    def fetch_user_relevant_info(self, user_id):
        """Fetch a user's details based on their userid."""
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        if user_id is None:
            logger.info(f"User ID is None. Cannot fetch user.")
            return None
        try:
            query = f"SELECT age, first_name, last_name, vegetarian, vegan, gluten_free, allergies,extra_info FROM {USERS_TABLE} WHERE id = %s"
            cursor.execute(query, (user_id, ))
            row = cursor.fetchone()
            result = [
                {"age": row[0],
                "first_name": row[1],
                    "last_name": row[2],
                    "vegetarian": row[3],
                    "vegan": row[4],
                    "gluten_free": row[5],
                    "allergies": row[6],
                    "extra_info": row[7]}
             ] 
            return result if row else None
        except mysql.connector.Error as err:
            logger.error(f"Error fetching user details for user_id '{user_id}': {err}")
            raise RuntimeError(f"Error fetching user details: {err}")
    
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
            