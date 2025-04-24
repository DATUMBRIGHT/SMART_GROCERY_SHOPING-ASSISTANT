import google.generativeai as genai
import json
import mysql.connector
from pydantic import BaseModel, Field, validator
from datetime import datetime
import yaml
import os
from dotenv import load_dotenv


from loggers.custom_logger import logger

# Load environment variables and configuration
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
    GEMINI_MODEL = config['gemini']['model']
    STOCK_TABLE = config['database']['tables']['stock']
    STOCK_IMAGES_TABLE = config['database']['tables']['stockimages']


# Database configuration
db_config = {
    "host": HOST,
    "user": USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
    "port": PORT
}

# Pydantic model for stock data validation
class StockData(BaseModel):
    name: str = Field(..., description="Name of the grocery item")
    quantity: int = Field(..., description="Quantity of the item")
    weight: float = Field(..., description="Weight of the item")
    category: str = Field(..., description="Category of the item")
    shelf_life: int = Field(..., description="Shelf life of the item in days")

# StockProcessorAgent class
class StockProcessorAgent:
    def __init__(self, api_key):
        self.api_key = api_key
        self.model_name = GEMINI_MODEL
        genai.configure(api_key=self.api_key)
        self.db_config = db_config
        # Create the table schema on initialization
        self.verify_users_table()
        self.create_stock_images_table()
        self.create_stock_table()
        self.create_all_stock_db()
        logger.info("Stock database schema initialized.")

    def verify_users_table(self):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES LIKE 'users'")
            if not cursor.fetchone():
                raise RuntimeError("Users table does not exist")
            logger.info("Users table verified.")
        except mysql.connector.Error as e:
            logger.error(f"Error verifying users table: {e}")
            raise RuntimeError(f"Error verifying users table: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def create_all_stock_db(self):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = """CREATE TABLE IF NOT EXISTS all_stock (
                        id INT NOT NULL AUTO_INCREMENT,
                        total_items INT NOT NULL,
                        user_id INT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    );"""
            cursor.execute(query)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("all_stock table schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating all_stock schema: {e}")
            raise RuntimeError(f"Error creating all_stock schema: {e}")

    def create_stock_table(self):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {STOCK_TABLE} (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    weight DOUBLE NOT NULL,
                    category TEXT NOT NULL,
                    shelf_life INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    stock_id INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (stock_id) REFERENCES all_stock(id)
                )
            ''')
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"{STOCK_TABLE} table schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating {STOCK_TABLE} schema: {e}")
            raise RuntimeError(f"Error creating {STOCK_TABLE} schema: {e}")

    def create_stock_images_table(self):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {STOCK_IMAGES_TABLE} (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    image_path TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    stock_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (stock_id) REFERENCES all_stock(id)
                )
            ''')
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"{STOCK_IMAGES_TABLE} table schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating {STOCK_IMAGES_TABLE} schema: {e}")
            raise RuntimeError(f"Error creating {STOCK_IMAGES_TABLE} schema: {e}")

    def process_stock_image(self, image_path):
        if not isinstance(image_path, str) or not image_path.endswith(('.png', '.jpeg', '.jpg')):
            logger.error("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")
            raise ValueError("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")
        try:
            with open(image_path, "rb") as img_file:
                image_data = img_file.read()
                logger.info("Image read successfully.")
            prompt = (
                "Extract all grocery items from the image and format the information as structured data. "
                "Each item should include the following fields: name, quantity, weight, category, shelf_life. "
                "Details about each field are as follows: "
                "1. name: The name of the grocery item. "
                "2. quantity: If no quantity is provided, default to 1. "
                "3. weight: If no weight is provided, default to 1.0. Extract number only "
                "4. category: Categorize each item (e.g., fruit, vegetable, dairy, bakery, etc.). "
                "5. shelf_life: Estimate the shelf_life of the item in days as an integer. "
                "Return the extracted data in a well-structured JSON format."
            )
            model = genai.GenerativeModel(self.model_name)
            mime_type = "image/png" if image_path.endswith(".png") else "image/jpeg"
            response = model.generate_content([{"mime_type": mime_type, "data": image_data}, prompt])
            raw_data = response.text.strip()
            logger.info("Raw data received from generative model.")
            if raw_data.startswith('```json') and raw_data.endswith('```'):
                raw_data = raw_data[7:-3].strip()
            parsed_data = json.loads(raw_data)
            logger.info("Parsed data successfully.")
            processed_data = []
            for item in parsed_data:
                mapped_item = {
                    "name": item.get("name"),
                    "quantity": int(item.get("quantity", 1)),
                    "weight": float(item.get("weight", 1.0)),
                    "category": item.get("category"),
                    "shelf_life": int(item.get("shelf_life")),
                }
                try:
                    validated_item = StockData(**mapped_item).model_dump()
                    processed_data.append(validated_item)
                    logger.info(f"Processed item: {validated_item}")
                except Exception as e:
                    logger.error(f"Validation error for item {item}: {e}")
            return processed_data
        except FileNotFoundError:
            logger.error(f"Image file not found: {image_path}")
            raise FileNotFoundError(f"Image file not found: {image_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from the response: {str(e)}")
            raise ValueError(f"Failed to decode JSON from the response: {str(e)}")
        except KeyError as e:
            logger.error(f"Missing expected field in response data: {str(e)}")
            raise ValueError(f"Missing expected field in response data: {str(e)}")
        except Exception as e:
            logger.error(f"Error processing the image: {str(e)}")
            raise RuntimeError(f"Error processing the image: {str(e)}")


    def save_to_db(self, data, user_id, image_path):
        if not data:
            logger.warning("No data provided to save.")
            raise ValueError("No data provided to save.")
        if not isinstance(data, list):
            logger.error("Data must be a list of dictionaries.")
            raise ValueError("Data must be a list of dictionaries.")
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f"INSERT INTO {STOCK_IMAGES_TABLE} (image_path, user_id) VALUES (%s, %s)", (image_path, user_id))
            logger.info(f"Saved image path {image_path} for user_id {user_id}.")

            stock_id = cursor.lastrowid #get row id from stockimages table 

            #stock_id not declared but set as null.
            cursor.execute("INSERT INTO all_stock (total_items, user_id,stock_id) VALUES (%s, %s,%s)", (len(data), user_id,stock_id))
            
            logger.info(f"Saved {len(data)} stock items for user_id {user_id}.")
            
            for item in data:
                query = f"INSERT INTO {STOCK_TABLE} (name, quantity, weight, category, shelf_life, user_id, stock_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                cursor.execute(query, (item['name'], item['quantity'], item['weight'], item['category'], item['shelf_life'], user_id, stock_id))
            conn.commit()
            logger.info(f"Saved {len(data)} stock items for user_id {user_id} with stock_id {stock_id}.")
            return stock_id
        except mysql.connector.Error as e:
            logger.error(f"Error saving stock data for user_id {user_id}: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error saving stock data: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    # fetch all stock item form db
    def fetch_all_stockitems(self, user_id):
            """Fetch all items from the stock database for a specific user."""
            try:
                conn = mysql.connector.connect(**self.db_config)
                cursor = conn.cursor()
                query = f"SELECT id, name, quantity, weight, category, shelf_life FROM {STOCK_TABLE} WHERE user_id = %s"
                cursor.execute(query, (user_id,))
                result = [
                    {
                        "id": row[0],
                        "name": row[1],
                        "quantity": row[2],
                        "weight": row[3],
                        "category": row[4],
                        "shelf_life": row[5]
                    }
                    for row in cursor.fetchall()
                ]
                cursor.close()
                conn.close()
                logger.info(f"Fetched {len(result)} items for user {user_id}.")
                return result
            except mysql.connector.Error as e:
                logger.error(f"Error fetching items for user {user_id}: {e}")
                raise RuntimeError(f"Error fetching items for user {user_id}: {e}")
    
    def fetch_stock(self, user_id, stock_id):
        """Fetch a specific stock item and its associated image."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = f"SELECT id, name, quantity, weight, category, shelf_life FROM {STOCK_TABLE} WHERE user_id = %s AND stock_id = %s"
            cursor.execute(query, (user_id, stock_id))
            result = [
                {
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "weight": row[3],
                    "category": row[4],
                    "shelf_life": row[5]
                }
                for row in cursor.fetchall()
            ]
            cursor.close()
            conn.close()
            logger.info(f"Fetched {len(result)} items for user {user_id} with stock_id {stock_id}.")
            return result
        except mysql.connector.Error as e:
            logger.error(f"Error fetching items for user {user_id}: {e}")
            raise RuntimeError(f"Error fetching items for user {user_id}: {e}")
    

    def get_latest_filename(self, user_id):
        """Query database for most recent filename for a specific user."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = f"SELECT image_path FROM {STOCK_IMAGES_TABLE} WHERE user_id = %s ORDER BY id DESC LIMIT 1"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            logger.info(f"Fetched latest filename for user {user_id}: {result[0] if result else None}")
            return result[0] if result else None
        except mysql.connector.Error as e:
            logger.error(f"Error fetching latest filename for user {user_id}: {e}")
            raise RuntimeError(f"Error fetching latest filename for user {user_id}: {e}")


    def delete_stock(self, user_id, item_id):
        """Delete a specific stock item and clean up related records if necessary."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f"SELECT stock_id FROM {STOCK_TABLE} WHERE id = %s AND user_id = %s", (item_id, user_id))
            result = cursor.fetchone()
            if not result:
                logger.info(f"No stock item found with id a{item_id} for user_id {user_id}.")
                return

            stock_id = result[0]
            cursor.execute(f"DELETE FROM {STOCK_TABLE} WHERE id = %s AND user_id = %s", (item_id, user_id))
            items_deleted = cursor.rowcount

            cursor.execute(f"SELECT COUNT(*) FROM {STOCK_TABLE} WHERE stock_id = %s AND user_id = %s", (stock_id, user_id))
            remaining_items = cursor.fetchone()[0]

            images_deleted = 0
            stock_deleted = 0
            if remaining_items == 0:
                cursor.execute(f"DELETE FROM {STOCK_IMAGES_TABLE} WHERE stock_id = %s AND user_id = %s", (stock_id, user_id))
                images_deleted = cursor.rowcount
                cursor.execute("DELETE FROM all_stock WHERE id = %s AND user_id = %s", (stock_id, user_id))
                stock_deleted = cursor.rowcount

            conn.commit()
            if items_deleted == 0:
                logger.info(f"No stock item found with id {item_id} for user_id {user_id}.")
            else:
                logger.info(f"Stock item {item_id} deleted for user_id {user_id}: 1 item, {images_deleted} images, {stock_deleted} stock records.")
                if remaining_items == 0 and stock_deleted == 0:
                    logger.warning(f"Stock item {item_id} deleted, but no all_stock record found for stock_id {stock_id}.")
        except mysql.connector.Error as e:
            logger.error(f"Error deleting stock item {item_id} for user_id {user_id}: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error deleting stock item {item_id}: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def delete_all_stock(self, user_id):
        """Delete all stock items and associated images for a specific user."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {STOCK_TABLE} WHERE user_id = %s", (user_id,))
            items_deleted = cursor.rowcount
            cursor.execute(f"DELETE FROM {STOCK_IMAGES_TABLE} WHERE user_id = %s", (user_id,))
            images_deleted = cursor.rowcount
            cursor.execute("DELETE FROM all_stock WHERE user_id = %s", (user_id,))
            stock_deleted = cursor.rowcount
            conn.commit()
            if stock_deleted == 0:
                logger.info(f"No stock records found for user_id {user_id}.")
            else:
                logger.info(f"Deleted for user_id {user_id}: {items_deleted} stock items, {images_deleted} images, {stock_deleted} stock records.")
        except mysql.connector.Error as e:
            logger.error(f"Error deleting all stock for user_id {user_id}: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error deleting all stock: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_latest_stock_by_user(self, user_id):
        """Fetch the latest stock item for the given user_id."""
        conn, cursor = None, None
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor(dictionary=True)  # Use dictionary cursor for column name access
            cursor.execute(
                f"""
                SELECT * FROM {STOCK_TABLE}
                WHERE user_id = %s AND stock_id = (
                    SELECT MAX(stock_id) FROM {STOCK_TABLE} WHERE user_id = %s
                )
                """,
                (user_id, user_id)
            )
            return cursor.fetchall()  # Fetch a single row (latest stock item)
        except mysql.connector.Error as e:
            error_message = f"Error fetching latest stock item for user_id {user_id}: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message)
        finally:
            # Close resources in one place
            if cursor:
                cursor.close()
            if conn:
                conn.close()