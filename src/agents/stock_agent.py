import sqlite3
from pydantic import BaseModel, Field
import google.generativeai as genai
import os
import json

from loggers.custom_logger import logger

# Database setup
db_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database')
STOCK_DB_NAME = os.path.join(db_folder, 'stock.db')

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
        self.model_name = "gemini-1.5-flash"
        genai.configure(api_key=self.api_key)
        self.db_name = STOCK_DB_NAME
        # Create the table schema on initialization
        self.create_db_schema()
        logger.info("Database schema initialized.")

    def create_db_schema(self):
        """Create the database schema if it doesn't exist."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS stock (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        quantity INTEGER,
                        weight TEXT,
                        category TEXT,
                        shelf_life INTEGER
                    )
                ''')
            conn.close()
            logger.info("Database schema created successfully.")
        except sqlite3.Error as e:
            logger.error(f"Error creating database schema: {e}")
            raise RuntimeError(f"Error creating database schema: {e}")

    def process_stock_image(self, image_path):
        """
        Processes a groceries image to extract grocery items, quantities, 
        weights, and categories, and returns the data in a structured JSON format.

        Args:
            image_path (str): Path to the grocery receipt image.

        Returns:
            list: Validated and structured grocery data ready for database insertion.
        """
        if not isinstance(image_path, str) or not image_path.endswith(('.png', '.jpeg', '.jpg')):
            logger.error("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")
            raise ValueError("Invalid image path. Provide a valid image file (.png, .jpeg, .jpg).")

        try:
            with open(image_path, "rb") as img_file:
                image_data = img_file.read()
                logger.info("Image read successfully.")

            prompt = (
                "Extract all grocery items from the image, in exact format  (name, quantity, weight, "
                "shelf_life, category) category e.g., fruit, vegetable, confectionery). Do not include price. "
                "Shelf life is an estimate in days example 3, 2, 1, 375."
                "If a grocery item doesn't have a quantity, set its quantity to 1. "
                "If a grocery item doesn't have a weight, set its weight to 1.0. "
                "Return the data in a well-structured JSON format, ready for DB insertion."
            )

            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content([
                {"mime_type": "image/jpeg", "data": image_data},
                prompt
            ])

            raw_data = response.text.strip()
            logger.info("Raw data received from generative model.")

            # Handle code block formatting if present
            if raw_data.startswith('```json') and raw_data.endswith('```'):
                raw_data = raw_data[7:-3].strip()

            # Parse JSON
            parsed_data = json.loads(raw_data)
            logger.info("Parsed data successfully.")

            # Process and validate the data
            processed_data = []
            for item in parsed_data:
                weight = float(item.get("weight", 1.0))
                quantity = int(item.get("quantity", 1))
                mapped_item = {
                    "name": item["name"],
                    "quantity": quantity,
                    "weight": weight,
                    "category": item["category"],
                    "shelf_life": item["shelf_life"],
                }

                # Validate with Pydantic and convert to dict
                validated_item = StockData(**mapped_item).model_dump()
                processed_data.append(validated_item)
                logger.info(f"Processed item: {validated_item}")

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

    def save_to_db(self, data):
        """
        Saves the processed grocery data to the database.

        Args:
            data (list): Processed grocery data to be saved.
        """
        if not data:
            logger.warning("No data provided to save.")
            raise ValueError("No data provided to save.")

        if not isinstance(data, list):
            logger.error("Data must be a list of dictionaries.")
            raise ValueError("Data must be a list of dictionaries.")

        try:
            # Create a new connection for this method
            conn = sqlite3.connect(self.db_name)
            
            # Insert data into the table within a transaction
            with conn:
                for item in data:
                    conn.execute('''
                        INSERT INTO stock (name, quantity, weight, category, shelf_life)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (item['name'], item['quantity'], item['weight'], item['category'], item['shelf_life']))
            
            # Close the connection when done
            conn.close()
            logger.info("Data saved to database successfully.")

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise RuntimeError(f"Database error: {e}")
    
    # Additional methods
    def fetch_all_items(self):
        """Fetch all items from the stock database."""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.execute("SELECT id, name, quantity, weight, category, shelf_life FROM stock")
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
            conn.close()
            return result
        except sqlite3.Error as e:
            logger.error(f"Error fetching items: {e}")
            raise RuntimeError(f"Error fetching items: {e}")
    
    def update_item(self, item_id, **kwargs):
        """Update a stock item with new values."""
        if not kwargs:
            logger.warning("No update data provided.")
            return
            
        try:
            # Build the update SQL statement dynamically
            set_parts = []
            values = []
            
            for key, value in kwargs.items():
                if key in ["name", "quantity", "weight", "category", "shelf_life"]:
                    set_parts.append(f"{key} = ?")
                    values.append(value)
            
            if not set_parts:
                logger.warning("No valid fields to update.")
                return
                
            values.append(item_id)  # Add the ID as the last parameter
            
            conn = sqlite3.connect(self.db_name)
            with conn:
                sql = f"UPDATE stock SET {', '.join(set_parts)} WHERE id = ?"
                cursor = conn.execute(sql, values)
                
                if cursor.rowcount == 0:
                    logger.warning(f"No item found with ID {item_id}.")
                else:
                    logger.info(f"Updated item ID {item_id}.")
            
            conn.close()
            
        except sqlite3.Error as e:
            logger.error(f"Error updating item: {e}")
            raise RuntimeError(f"Error updating item: {e}")
    
    def delete_item(self, item_id):
        """Delete an item from the stock database."""
        try:
            conn = sqlite3.connect(self.db_name)
            with conn:
                cursor = conn.execute("DELETE FROM stock WHERE id = ?", (item_id,))
                if cursor.rowcount == 0:
                    logger.warning(f"No item found with ID {item_id}.")
                else:
                    logger.info(f"Deleted item with ID {item_id}.")
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"Error deleting item: {e}")
            raise RuntimeError(f"Error deleting item: {e}")