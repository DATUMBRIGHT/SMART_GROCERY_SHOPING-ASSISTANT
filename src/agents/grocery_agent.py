import google.generativeai as genai
import json
from pydantic import BaseModel, Field, validator
from datetime import datetime
import sqlite3
import os

from loggers.custom_logger import logger

# Database setup
db_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database')
RECEIPT_DB_NAME = os.path.join(db_folder, 'receipts.db')
STOCK_DB_NAME = os.path.join(db_folder, 'stock.db')

if not os.path.exists(db_folder):
    os.makedirs(db_folder)

# Pydantic Model for Grocery Item
class GroceryItem(BaseModel):
    name: str = Field(..., description="Name of the grocery item")
    quantity: int = Field(..., ge=0, description="Quantity of the item (must be non-negative)")
    weight: float = Field(default=0.0, ge=0.0, description="Weight of the item")
    category: str = Field(..., description="Category of the item (e.g., 'fruit', 'vegetable', etc.)")
    purchase_date: str = Field(..., description="Purchase date of the item (YYYY-MM-DD format)")
    expiration_date: str = Field(..., description="Expiration date of the item (YYYY-MM-DD format)")

    @validator("purchase_date", "expiration_date", pre=True)
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
        self.model_name = "gemini-1.5-flash"
        genai.configure(api_key=self.api_key)
        self.db_name = RECEIPT_DB_NAME
        # Initialize database schema on startup
        self.create_db_schema()
        
    def create_db_schema(self):
        """Creates the database schema if it doesn't already exist."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS receipts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        quantity INTEGER NOT NULL,
                        weight REAL DEFAULT 0.0,
                        category TEXT NOT NULL,
                        purchase_date DATE NOT NULL,
                        expiration_date DATE NOT NULL
                    )
                    """
                )
            conn.close()
            logger.info("Database schema created successfully.")
        except sqlite3.Error as e:
            logger.error(f"Error creating database schema: {e}")
            raise RuntimeError(f"Error creating database schema: {e}")

    def process_receipt(self, image_path):
        if not isinstance(image_path, str) or not image_path.endswith((".png", ".jpeg", ".jpg")):
            logger.error("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")
            raise ValueError("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")

        try:
            with open(image_path, "rb") as img_file:
                image_data = img_file.read()
                logger.info("Receipt image read successfully.")

            prompt = (
                "Extract all grocery items from the receipt image, in exact format  (name, quantity, weight, "
                "purchase_date, expiration_date, and category) (e.g., fruit, vegetable, confectionery). Do not include price. "
                "If a grocery item doesn't have a quantity, set its quantity to 1. "
                "If a grocery item doesn't have a weight, set its weight to 1.0. "
                "Extract date on receipt as purchase date and estimate expiration date from purchase date. "
                "Return the data in well-structured JSON format YYYY-MM-DD, ready for database insertion."
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
                raise RuntimeError("Expected a list of items in the JSON response.")

            processed_data = []
            for item in parsed_data:
                if not all(key in item for key in ["name", "quantity", "weight", "category", "purchase_date", "expiration_date"]):
                    logger.error(f"Missing keys in item: {item}")
                    raise ValueError(f"Missing keys in item: {item}")

                mapped_item = GroceryItem(
                    name=item.get("name", "Unknown"),
                    quantity=int(item.get("quantity", 1)),
                    weight=float(item.get("weight", 1.0)),
                    category=item.get("category", "Uncategorized"),
                    purchase_date=item["purchase_date"],
                    expiration_date=item.get["expiration_date"])
                
                processed_data.append(mapped_item.model_dump())
                logger.info(f"Processed item: {mapped_item}")
            return processed_data

        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error processing the image: {e}")
            raise RuntimeError(f"Error processing the image: {e}")

    def save_data(self, data):
        """Save data to the database using a new connection."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:  
                conn.executemany(
                    """
                    INSERT INTO receipts (name, quantity, weight, category, purchase_date, expiration_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [(item["name"], item["quantity"], item["weight"], item["category"], 
                      item["purchase_date"], item["expiration_date"]) for item in data]
                )
            conn.close()
            logger.info(f"Saved {len(data)} items to the database.")
        except sqlite3.Error as e:
            logger.error(f"Error saving data: {e}")
            raise RuntimeError(f"Error saving data: {e}")
    
    def update_quantity(self, item_id, new_quantity):
        """Update item quantity using a new connection."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:
                cursor = conn.execute("UPDATE receipts SET quantity = ? WHERE id = ?", 
                                     (new_quantity, item_id))
                if cursor.rowcount == 0:
                    print(f"No item found with ID {item_id}.")
                else:
                    print(f"Updated item ID {item_id} to quantity {new_quantity}.")
            conn.close()
        except sqlite3.Error as e:
            raise RuntimeError(f"Error updating item: {e}")

    def delete_item(self, item_id):
        """Delete an item using a new connection."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:
                cursor = conn.execute("DELETE FROM receipts WHERE id = ?", (item_id,))
                if cursor.rowcount == 0:
                    print(f"No item found with ID {item_id}.")
                else:
                    print(f"Deleted item with ID {item_id}.")
            conn.close()
        except sqlite3.Error as e:
            raise RuntimeError(f"Error deleting item: {e}")

    def fetch_all_items(self):
        """Fetch all items using a new connection."""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.execute("SELECT name, quantity, weight, category, purchase_date, expiration_date FROM receipts")
            result = [
                {"name": row[0], "quantity": row[1], "weight": row[2], 
                 "category": row[3], "purchase_date": row[4], "expiration_date": row[5]}
                for row in cursor.fetchall()
            ]
            conn.close()
            return result
        except sqlite3.Error as e:
            raise RuntimeError(f"Error fetching items: {e}")
    
    def delete_all_items(self):
        """Delete all items using a new connection."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:
                conn.execute("DELETE FROM receipts")
            conn.close()
            logger.info("All items deleted.")
        except sqlite3.Error as e:
            logger.error(f"Error deleting all items: {e}")
            raise RuntimeError(f"Error deleting all items: {e}")