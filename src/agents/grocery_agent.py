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
base_dir = os.path.dirname(os.path.abspath(__file__))
config_file = os.path.join(base_dir, 'src', 'constants', 'config.yaml')

with open(config_file, 'r') as file:
    config = yaml.safe_load(file)
    DB_NAME = config['database']['name']
    HOST = config['database']['host']
    USER = config['database']['user']
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    PORT = config['database']['port']
    GEMINI_MODEL = config['gemini']['model']

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
    purchase_date: str = Field(..., description="Purchase date of the item (YYYY-MM-DD format)")
    expiration_date: str = Field(..., description="Expiration date of the item (YYYY-MM-DD format)")

    @validator("purchase_date", "expiration_date")
    def validate_and_format_date(cls, value):
        try:
            date_obj = datetime.strptime(value, "%Y-%m-%d")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {value}. Expected format: YYYY-MM-DD.")

# Receipt Processor Agent
class ReceiptProcessorAgent:
    def __init__(self, api_key):
        self.api_key = api_key
        self.model_name = GEMINI_MODEL  # Use config value instead of hardcoding
        genai.configure(api_key=self.api_key)
        self.db_config = DB_CONFIG
        # Initialize database schema on startup
        self.create_db_schema()

    def create_db_schema(self):
        """Creates the database schema if it doesn't already exist."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    weight REAL DEFAULT 0.0,
                    category TEXT NOT NULL,
                    purchase_date DATE NOT NULL,
                    expiration_date DATE NOT NULL
                )
            """)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating database schema: {e}")
            raise RuntimeError(f"Error creating database schema: {e}")

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
                "Extract all grocery items from the receipt image in the exact format (name, quantity, weight, "
                "purchase_date, expiration_date, category) (e.g., category: fruit, vegetable, confectionery). "
                "Do not include price. If a grocery item doesn't have a quantity, set its quantity to 1. "
                "If a grocery item doesn't have a weight, set its weight to 1.0. "
                "Extract the date on the receipt as the purchase_date and estimate the expiration_date from the purchase_date. "
                "Return the data in well-structured JSON format with dates in YYYY-MM-DD, ready for database insertion."
            )

            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content([
                {"mime_type": "image/jpeg", "data": image_data},
                prompt,
            ])

            raw_data = response.text.strip()
            if raw_data.startswith("```json") and raw_data.endswith("```"):
                raw_data = raw_data[7:-3].strip()

            parsed_data = json.loads(raw_data)
            if not isinstance(parsed_data, list):
                logger.error("Expected a list of items in the JSON response.")
                raise ValueError("Expected a list of items in the JSON response.")

            processed_data = []
            for item in parsed_data:
                if not all(key in item for key in ["name", "quantity", "weight", "category", "purchase_date", "expiration_date"]):
                    logger.error(f"Missing keys in item: {item}")
                    raise ValueError(f"Missing keys in item: {item}")

                mapped_item = GroceryItem(
                    name=item["name"],
                    quantity=int(item.get("quantity", 1)),
                    weight=float(item.get("weight", 1.0)),
                    category=item["category"],
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
            logger.error(f"Failed to decode JSON from response: {e}")
            raise RuntimeError(f"Failed to decode JSON from response: {e}")
        except mysql.connector.Error as e:
            logger.error(f"Database error during processing: {e}")
            raise RuntimeError(f"Database error during processing: {e}")
        except Exception as e:
            logger.error(f"Error processing the image: {e}")
            raise RuntimeError(f"Error processing the image: {e}")

    def save_data(self, data):
        """Save data to the database."""
        if not data or not isinstance(data, list):
            logger.error("Data must be a non-empty list of dictionaries.")
            raise ValueError("Data must be a non-empty list of dictionaries.")

        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO receipts (name, quantity, weight, category, purchase_date, expiration_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, [(item["name"], item["quantity"], item["weight"], item["category"],
                   item["purchase_date"], item["expiration_date"]) for item in data])
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Saved {len(data)} items to the database.")
        except mysql.connector.Error as e:
            logger.error(f"Error saving data: {e}")
            raise RuntimeError(f"Error saving data: {e}")

    def update_quantity(self, item_id, new_quantity):
        """Update item quantity."""
        if not isinstance(new_quantity, int) or new_quantity < 0:
            logger.error("New quantity must be a non-negative integer.")
            raise ValueError("New quantity must be a non-negative integer.")

        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("UPDATE receipts SET quantity = %s WHERE id = %s", (new_quantity, item_id))
            conn.commit()
            if cursor.rowcount == 0:
                logger.warning(f"No item found with ID {item_id}.")
                print(f"No item found with ID {item_id}.")
            else:
                logger.info(f"Updated item ID {item_id} to quantity {new_quantity}.")
                print(f"Updated item ID {item_id} to quantity {new_quantity}.")
            cursor.close()
            conn.close()
        except mysql.connector.Error as e:
            logger.error(f"Error updating item: {e}")
            raise RuntimeError(f"Error updating item: {e}")

    def delete_item(self, item_id):
        """Delete an item."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM receipts WHERE id = %s", (item_id,))
            conn.commit()
            if cursor.rowcount == 0:
                logger.warning(f"No item found with ID {item_id}.")
                print(f"No item found with ID {item_id}.")
            else:
                logger.info(f"Deleted item with ID {item_id}.")
                print(f"Deleted item with ID {item_id}.")
            cursor.close()
            conn.close()
        except mysql.connector.Error as e:
            logger.error(f"Error deleting item: {e}")
            raise RuntimeError(f"Error deleting item: {e}")

    def fetch_all_items(self):
        """Fetch all items."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, quantity, weight, category, purchase_date, expiration_date FROM receipts")
            result = [
                {
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "weight": row[3],
                    "category": row[4],
                    "purchase_date": row[5].strftime("%Y-%m-%d") if row[5] else None,
                    "expiration_date": row[6].strftime("%Y-%m-%d") if row[6] else None
                }
                for row in cursor.fetchall()
            ]
            cursor.close()
            conn.close()
            return result
        except mysql.connector.Error as e:
            logger.error(f"Error fetching items: {e}")
            raise RuntimeError(f"Error fetching items: {e}")

    def delete_all_items(self):
        """Delete all items."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM receipts")
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("All items deleted.")
        except mysql.connector.Error as e:
            logger.error(f"Error deleting all items: {e}")
            raise RuntimeError(f"Error deleting all items: {e}")