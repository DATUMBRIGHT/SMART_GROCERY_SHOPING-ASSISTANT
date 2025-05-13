import google.generativeai as genai
import json
import mysql.connector
from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional
import yaml
import os
from dotenv import load_dotenv
from mysql.connector import pooling


from loggers.custom_logger import logger

# Load environment variables and configuration
load_dotenv()
BASE_URL = os.path.join(os.path.dirname(__file__),'..')
CONFIG_PATH = os.path.join(BASE_URL,'constants','config.yaml')

with open(CONFIG_PATH, 'r') as file:
    config = yaml.safe_load(file)
    DB_NAME = config['database']['name']
    HOST = config['database']['host']
    USER = config['database']['user']
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    PORT = config['database']['port']
    GEMINI_MODEL = config['gemini']['model']
    RECEIPTS_TABLE = config['database']['tables']['receipts']

DB_CONFIG = {
    "host": HOST,
    "user": USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
    "port": PORT
}

# Pydantic Model for Grocery Item
class GroceryItem(BaseModel):
    name: str = Field(..., description="Name of the grocery item")
    quantity: int = Field(..., ge=0, description="Quantity of the item (must be non-negative)")
    weight: float = Field(default=0.0, ge=0.0, description="Weight of the item")
    category: str = Field(..., description="Category of the item (e.g., 'fruit', 'vegetable', etc.)")
    price: float = Field(..., description="Price of the item")
    purchase_date: Optional[str]  = Field(..., description="Purchase date of the item (YYYY-MM-DD format)")
    expiration_date: Optional[str]  = Field(..., description="Expiration date of the item (YYYY-MM-DD format)")

    @validator("purchase_date", "expiration_date")
    def validate_and_format_date(cls, value):
        """ data validation"""
        try:
            date_obj = datetime.strptime(value, "%Y-%m-%d")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {value}. Expected format: YYYY-MM-DD.")

#Receipt Processor Agent
class ReceiptProcessorAgent:
    def __init__(self, api_key):
        self.api_key = api_key
        self.model_name = GEMINI_MODEL  # Use config value instead of hardcoding
        genai.configure(api_key=self.api_key)
        self.db_config = DB_CONFIG
        # Initialize database schema on startup
        self.verify_users_table()
        self.create_all_receipts_db()
        self.create_db_schema()
        self.create_image_db()
        
        

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

    def create_all_receipts_db(self):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = """CREATE TABLE IF NOT EXISTS all_receipts (
                        id INT NOT NULL AUTO_INCREMENT,
                        total_items INT NOT NULL,
                        total_amount DECIMAL(10,2) NOT NULL,
                        user_id INT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    );"""
            cursor.execute(query)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating database schema: {e}")
            raise RuntimeError(f"Error creating database schema: {e}")

    def create_db_schema(self):
        """Creates the database schema if it doesn't already exist."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = f"""CREATE TABLE IF NOT EXISTS {RECEIPTS_TABLE} (
                        id INT NOT NULL AUTO_INCREMENT,
                        name TEXT NOT NULL,
                        quantity INT NOT NULL,
                        weight DOUBLE DEFAULT 0,
                        category TEXT NOT NULL,
                        price DOUBLE NOT NULL,
                        purchase_date DATE NOT NULL,
                        expiration_date DATE NOT NULL,
                        user_id INT NOT NULL,
                        receipt_id INT NOT NULL,
                        PRIMARY KEY (id),
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (receipt_id) REFERENCES all_receipts(id)
                    );
            """
            cursor.execute(query)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating database schema: {e}")
            raise RuntimeError(f"Error creating database schema: {e}")
        

    #process and get data from receipt image
    def process_receipt(self, image_path):
        """Process a receipt image and extract grocery items."""
        if not isinstance(image_path, str) or not image_path.endswith((".png", ".jpeg", ".jpg")):
            logger.error("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")
            raise ValueError("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")

        try:
            with open(image_path, "rb") as img_file:
                image_data = img_file.read()
                logger.info("Receipt image read successfully.")

            prompt = (
                    "Extract all grocery items from the receipt image and format the information as structured data. "
                    "Each item should include: name, quantity, weight, category, price, purchase_date, expiration_date. "
                    "Details: "
                    "1. name: The name of the grocery item. "
                    "2. quantity: Default to 1 if not provided. "
                    "3. weight: Default to 1.0 if not provided. "
                    "4. category: Categorize (e.g., fruit, vegetable, confectionery, bakery, dairy). "
                    "5. price: Extract as float; default to 0.0 if unknown. "
                    "6. purchase_date: Extract as YYYY-MM-DD string. "
                    "7. expiration_date: Estimate based on purchase_date as YYYY-MM-DD. as string "
                    "Return the data in JSON format."
                )

            
            model = genai.GenerativeModel(self.model_name)
            mime_type = "image/png" if image_path.endswith(".png") else "image/jpeg"
            response = model.generate_content([{"mime_type": mime_type, "data": image_data},prompt])

           
            raw_data = response.text.strip()
            print(raw_data)
            if raw_data.startswith("```json") and raw_data.endswith("```"):
                raw_data = raw_data[7:-3].strip()

            parsed_data = json.loads(raw_data)
            if not isinstance(parsed_data, list):
                logger.error("Expected a list of items in the JSON response.")
                raise ValueError("Expected a list of items in the JSON response.")

            processed_data = []
            for item in parsed_data:
                if not all(key in item for key in ["name", "quantity", "weight", "category","price", "purchase_date", "expiration_date"]):
                    logger.error(f"Missing keys in item: {item}")
                    raise ValueError(f"Missing keys in item: {item}")

                mapped_item = GroceryItem(
                    name=item["name"],
                    quantity=int(item.get("quantity", 1)),
                    weight=float(item.get("weight", 1.0)),
                    category=item["category"],
                    price=float(item.get("price",1.0)),
                    purchase_date=item["purchase_date"],
                    expiration_date=item["expiration_date"]
                )
                processed_data.append(mapped_item.model_dump())
                logger.info(f"Processed item: {mapped_item}")
            return processed_data

        except FileNotFoundError as e:
            logger.error(f"Image file not found: {image_path}")
            raise RuntimeError(f"Image file not found: {image_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Couldnt Process Image. {e}")
            raise RuntimeError(f"Couldnt Process Image. Make sure you have a real receipt!")
        except mysql.connector.Error as e:
            logger.error(f"Database error during processing: {e}")
            raise RuntimeError(f"Database error during processing: {e}")
        except Exception as e:
            logger.error(f"Error processing the image: {e}")
            raise RuntimeError(f"Error processing the image. Check if the image is a valid receipt and try again")

    
    def save_data(self, data, user_id):
        if not data or not isinstance(data, list):
            logger.error("Data must be a non-empty list of dictionaries.")
            raise ValueError("Data must be a non-empty list of dictionaries.")
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            total_amount = sum(float(item['price']) for item in data)
            total_items = len(data)
            cursor.execute("""
                INSERT INTO all_receipts (total_amount, total_items, user_id)
                VALUES (%s, %s, %s)""",
                (total_amount, total_items, user_id))
            all_receipts_id = cursor.lastrowid
            items_data_to_insert = [
                (item["name"], item["quantity"], item["weight"], item["category"], item["price"],
                item["purchase_date"], item["expiration_date"], user_id, all_receipts_id)
                for item in data
            ]
            cursor.executemany(f"""
                INSERT INTO {RECEIPTS_TABLE} (name, quantity, weight, category, price, purchase_date, expiration_date, user_id, receipt_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                items_data_to_insert)
            conn.commit()
            logger.info(f"Saved {len(data)} items to {RECEIPTS_TABLE} linked to receipt ID: {all_receipts_id}")
            return all_receipts_id
        except mysql.connector.Error as e:
            logger.error(f"Error saving data: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error saving data: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    
    #fetch all individual receipt_items from db
    def fetch_all_receipts_items(self, user_id):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = f"""SELECT id, name, quantity, weight, category, price, purchase_date, expiration_date
                        FROM {RECEIPTS_TABLE}
                        WHERE user_id = %s """
            cursor.execute(query, (user_id,))
            result = [
                {
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "weight": row[3],
                    "category": row[4],
                    "price": row[5],
                    "purchase_date": row[6].strftime("%Y-%m-%d") if row[6] else None,
                    "expiration_date": row[7].strftime("%Y-%m-%d") if row[7] else None
                }
                for row in cursor.fetchall()
            ]
            cursor.close()
            conn.close()
            return result
        except mysql.connector.Error as e:
            logger.error(f"Error fetching items: {e}")
            raise RuntimeError(f"Error fetching items: {e}")

    def delete_all_receipt_items(self, user_id):
        """Delete all receipt items, images, and receipts for a user."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {RECEIPTS_TABLE} WHERE user_id = %s", (user_id,))
            logger.info(f"All receipt items deleted for user_id {user_id}.")
            cursor.execute("DELETE FROM receiptimages WHERE user_id = %s", (user_id,))
            logger.info(f"All receipt images deleted for user_id {user_id}.")
            cursor.execute("DELETE FROM all_receipts WHERE user_id = %s", (user_id,))
            logger.info(f"All receipts deleted for user_id {user_id}.")
            conn.commit()
        except mysql.connector.Error as e:
            logger.error(f"Error deleting data for user_id {user_id}: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error deleting data: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    
    
    #create image db
    def create_image_db(self):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receiptimages (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    image_path TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    receipt_id INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (receipt_id) REFERENCES all_receipts(id)
                )
            """)
            conn.commit()
            logger.info("Image database schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating image database schema: {e}")
            raise RuntimeError(f"Error creating image database schema: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()



    #save image to db
    def save_image(self, image_path, user_id, receipt_id):
        if not image_path or not isinstance(image_path, str):
            logger.error("Image file name must be a non-empty string")
            raise ValueError("Image file name must be a non-empty string")
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = "INSERT INTO receiptimages (image_path, user_id, receipt_id) VALUES (%s, %s, %s)"
            cursor.execute(query, (image_path, user_id, receipt_id))
            conn.commit()
            logger.info(f"Saved image path to database: {image_path} linked to receipt ID: {receipt_id}")
        except mysql.connector.Error as e:
            logger.error(f"Error saving image: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error saving image: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        return receipt_id
    
    #get latest image
    def get_latest_filename(self, user_id, last_receipt_id):
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = "SELECT image_path FROM receiptimages WHERE user_id = %s AND receipt_id = %s"
            cursor.execute(query, (user_id, last_receipt_id))
            result = cursor.fetchone()
            logger.debug(f"Latest filename: {result[0] if result else None}")
            return result[0] if result else None
        except mysql.connector.Error as e:
            logger.error(f"Error fetching latest filename: {e}")
            raise RuntimeError(f"Error fetching latest filename: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        

                
    def get_all_receipts(self,user_id):
        """Fetch all receipts."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = f"""
                SELECT id, total_amount, total_items, created_at 
                FROM all_receipts 
                WHERE user_id = %s
                ORDER BY created_at DESC
            """
            cursor.execute(query, (user_id,))
            result = cursor.fetchall()
            cursor.close()
            conn.close()
            return result if result else []
        except mysql.connector.Error as e:
            logger.error(f"Error fetching receipts: {e}")
            raise RuntimeError(f"Error fetching receipts: {e}")
        

    def delete_receipt(self, receipt_id, user_id):
        """Delete a specific receipt and its items/images."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {RECEIPTS_TABLE} WHERE receipt_id = %s AND user_id = %s", (receipt_id, user_id))
            items_deleted = cursor.rowcount
            cursor.execute("DELETE FROM receiptimages WHERE receipt_id = %s AND user_id = %s", (receipt_id, user_id))
            images_deleted = cursor.rowcount
            cursor.execute("DELETE FROM all_receipts WHERE id = %s AND user_id = %s", (receipt_id, user_id))
            receipts_deleted = cursor.rowcount
            conn.commit()
            if receipts_deleted == 0:
                logger.info(f"No receipt found with id {receipt_id} for user_id {user_id}.")
            else:
                logger.info(f"Receipt {receipt_id} deleted successfully for user_id {user_id} (items: {items_deleted}, images: {images_deleted}).")
        except mysql.connector.Error as e:
            logger.error(f"Error deleting receipt {receipt_id} for user_id {user_id}: {e}")
            if conn:
                conn.rollback()
            raise RuntimeError(f"Error deleting receipt {receipt_id}: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def fetch_receipt_items_by_id(self, receipt_id, user_id):
        """Fetch all items for a specific receipt."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            query = f"""
                SELECT id, name, quantity, weight, category, price, purchase_date, expiration_date
                FROM {RECEIPTS_TABLE}
                WHERE receipt_id = %s AND user_id = %s
            """
            cursor.execute(query, (receipt_id, user_id))
            result = [
                {
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "weight": row[3],
                    "category": row[4],
                    "price": row[5],
                    "purchase_date": row[6].strftime("%Y-%m-%d") if row[6] else None,
                    "expiration_date": row[7].strftime("%Y-%m-%d") if row[7] else None
                }
                for row in cursor.fetchall()
            ]
            cursor.close()
            conn.close()
            return result
        except mysql.connector.Error as e:
            logger.error(f"Error fetching items: {e}")
            raise RuntimeError(f"Error fetching items: {e}")
        

   