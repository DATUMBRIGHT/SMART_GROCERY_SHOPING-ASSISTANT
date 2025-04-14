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
        self.create_image_db()

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
                    price REAL NOT NULL,
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
                    "Each item should include the following fields: name, quantity, weight, category, purchase_date, and expiration_date. "
                    "Details about each field are as follows: "
                    "1. name: The name of the grocery item. "
                    "2. quantity: If no quantity is provided on the receipt, default to 1. "
                    "3. weight: If no weight is provided on the receipt, default to 1.0. "
                    "4. category: Categorize each item (e.g., fruit, vegetable, confectionery,bakery,dairy). "
                    "5. price : Extract the price from the receipt and store it as a float. if price unknown make it 0.0 "
                    "6. purchase_date: Extract the date from the receipt and store it as a string in YYYY-MM-DD format. "
                    "7. expiration_date: Estimate the expiration date based on the purchase_date and store it as a string in YYYY-MM-DD format. "
                    "Exclude price information. "
                    "Return the extracted data in a well-structured JSON format, ready for database insertion."
                )

            
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content([
                {"mime_type": "image/jpeg", "data": image_data},
                prompt,
            ])

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

    
    #save items to db
    def save_data(self, data):
        """Save data to the database."""
        if not data or not isinstance(data, list):
            logger.error("Data must be a non-empty list of dictionaries.")
            raise ValueError("Data must be a non-empty list of dictionaries.")

        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO receipts (name, quantity, weight, category, price, purchase_date, expiration_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, [(item["name"], item["quantity"], item["weight"], item["category"], item["price"],
                   item["purchase_date"], item["expiration_date"]) for item in data])
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Saved {len(data)} items to the database.")
        except mysql.connector.Error as e:
            logger.error(f"Error saving data: {e}")
            raise RuntimeError(f"Error saving data: {e}")

   
    #fetch all items from db
    def fetch_all_items(self):
        """Fetch all items."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, quantity, weight, category, price, purchase_date, expiration_date FROM receipts")
            result = [
                {
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "weight": row[3],
                    "category": row[4],
                    "price": row[5],
                    "purchase_date": row[6].strftime("%Y-%m-%d") if row[5] else None,
                    "expiration_date": row[7].strftime("%Y-%m-%d") if row[6] else None
                }
                for row in cursor.fetchall()
            ]
            cursor.close()
            conn.close()
            return result
        except mysql.connector.Error as e:
            logger.error(f"Error fetching items: {e}")
            raise RuntimeError(f"Error fetching items: {e}")

    #delete all items form db
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
        
    #create image db
    def create_image_db(self):
        """Creates the database schema for image data if it doesn't already exist."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receiptimages (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    image_path TEXT NOT NULL
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
    def save_image(self, image_path):
        """Save image path to the database."""
        if not image_path or not isinstance(image_path, str):
            logger.error("Image file name must be a non-empty string")
            raise ValueError("Image file name must be a non-empty string")
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO receiptimages (image_path) VALUES (%s)", (image_path,))
            conn.commit()
            logger.info(f"Saved image path to database: {image_path}")
        except mysql.connector.Error as e:
            logger.error(f"Error saving image: {e}")
            raise RuntimeError(f"Error saving image: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    #get latest image
    def get_latest_filename(self):
        """Query database for most recent filename."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT image_path FROM receiptimages ORDER BY id DESC LIMIT 1")
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
    
    #delete image froim db
    def clear_image_db(self):
        """Clear all entries from receiptimages table."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM receiptimages")
            conn.commit()
            logger.info("Image database cleared successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error clearing image database: {e}")
            raise RuntimeError(f"Error clearing image database: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

                
        