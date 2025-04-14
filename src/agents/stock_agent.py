import mysql.connector
from pydantic import BaseModel, Field
import google.generativeai as genai
import os
import json
import yaml
from dotenv import load_dotenv
from datetime import datetime

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
        self.create_db_schema()
        self.create_image_db()
        logger.info("Database schema initialized.")


    #create schema for images db
    def create_image_db(self):
        """Create the database schema for image data if it doesn't exist."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stockimages (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    image_path TEXT
                )
            ''')
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database schema created successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Error creating database schema: {e}")
            raise RuntimeError(f"Error creating database schema: {e}")

    def create_db_schema(self):
        """Create the database schema if it doesn't exist."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    name TEXT,
                    quantity INTEGER,
                    weight TEXT,
                    category TEXT,
                    shelf_life INTEGER
                )
            ''')
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Database schema created successfully.")
        except mysql.connector.Error as e:
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
                    "Extract all grocery items from the receipt image and format the information as structured data. "
                    "Each item should include the following fields: name, quantity, weight, category, shelf_life. "
                    "Details about each field are as follows: "
                    "1. name: The name of the grocery item. "
                    "2. quantity: If no quantity is provided on the receipt, default to 1. "
                    "3. weight: If no weight is provided on the receipt, default to 1.0. "
                    "4. category: Categorize each item (e.g., fruit, vegetable, confectionery). "
                    "5. shelf_life: Estimate the shelf_life of the item in days as an integer. "
                    
                    "Return the extracted data in a well-structured JSON format, ready for database insertion."
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
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            for item in data:
                cursor.execute('''
                    INSERT INTO stock (name, quantity, weight, category, shelf_life)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (item['name'], item['quantity'], item['weight'], item['category'], item['shelf_life']))
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Data saved to database successfully.")
        except mysql.connector.Error as e:
            logger.error(f"Database error: {e}")
            raise RuntimeError(f"Database error: {e}")
    

    #fetch all stock item form db 
    def fetch_all_items(self):
        """Fetch all items from the stock database."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, quantity, weight, category, shelf_life FROM stock")
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
            return result
        except mysql.connector.Error as e:
            logger.error(f"Error fetching items: {e}")
            raise RuntimeError(f"Error fetching items: {e}")
    

    #save image to db
    def save_image(self, filename):
        """Save image path to the database."""
        if not filename or not isinstance(filename, str):
            logger.error("Image file name must be a non-empty string")
            raise ValueError("Image file name must be a non-empty string")
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO stockimages (image_path) VALUES (%s)", (filename,))
            conn.commit()
            logger.info(f"Saved image path to database: {filename}")
        except mysql.connector.Error as e:
            logger.error(f"Error saving image: {e}")
            raise RuntimeError(f"Error saving image: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        
    def get_latest_filename(self):
        # Query database for most recent filename
        conn = mysql.connector.connect(**self.db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM stockimages ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
        cursor.close()
        return result[0] if result else None

    def delete_stocks(self):
        """Delete an item from the stock database."""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stock")
            if cursor.rowcount == 0:
                logger.warning(f"No item founds to delete.")
            else:
                logger.info(f"Deleted stocks succesfully")
            conn.commit()
            cursor.close()
            conn.close()
        except mysql.connector.Error as e:
            logger.error(f"Error deleting item: {e}")
            raise RuntimeError(f"Error deleting item: {e}")
        

    def clear_image_db(self):
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stockimages")
            conn.commit()
            cursor.close()
            conn.close()
            logger.info("Image database cleared successfully.")
        
