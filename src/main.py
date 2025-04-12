from flask import Flask, render_template, url_for, redirect, flash, request, jsonify
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import FileField, SubmitField,StringField
from wtforms.validators import DataRequired, NumberRange
from flask import session
import mysql.connector
import os
from pathlib import Path
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import random
import yaml
from mysql.connector import pooling
from datetime import datetime
from markdown import markdown
from agents.grocery_agent import ReceiptProcessorAgent
from agents.stock_agent import StockProcessorAgent
from agents.grocery_analyzer import SmartGroceryAnalyzer

from loggers.custom_logger import logger
# Load environment variables
load_dotenv()

# Define paths
BASE_URL = os.path.abspath(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_URL, 'constants', 'config.yaml')

# Load configuration
try:
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
        DEEPSEEK_API_URL = config['deepseek']['api_url']
        ALLOWED_EXTENSIONS = set(config['upload']['allowed_extensions'])  # e.g., ['png', 'jpeg', 'jpg']
        MAX_CONTENT_LENGTH = config['upload']['max_content_length']  # e.g., 16 * 1024 * 1024 (16MB)
        DB_CONFIG = {
            "host": config['database']['host'],
            "user": config['database']['user'],
            "password": os.getenv('DB_PASSWORD'),
            "database": config['database']['name'],
            "port": config['database']['port']
        }
except FileNotFoundError:
    raise Exception("Configuration file not found at: " + CONFIG_PATH)
except KeyError as e:
    raise Exception(f"Missing configuration key: {str(e)}")

# Set random seed for reproducibility
random.seed(42)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY")  # Required for flash messages and CSRF
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_URL, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH  # Limit file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize database connection pool
db_pool = pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **DB_CONFIG)

# Initialize agents and analyzer
stock_agent = StockProcessorAgent(api_key=GEMINI_API_KEY)
receipt_agent = ReceiptProcessorAgent(api_key=GEMINI_API_KEY)
analyzer = SmartGroceryAnalyzer(stock_agent=stock_agent, receipt_agent=receipt_agent)

# Form for receipt upload
class ReceiptUploadForm(FlaskForm):
    receipt_image = FileField('Receipt Image', validators=[DataRequired()])
    submit = SubmitField('Upload Receipt')

class StockUploadForm(FlaskForm):
    stock_image = FileField('Stock Image', validators=[DataRequired()])
    submit = SubmitField('Upload Stock')

class DeleteStockForm(FlaskForm):
    submit = SubmitField('Delete Stock')

class ChatForm(FlaskForm):
    query = StringField('Query', validators=[DataRequired()])
    submit = SubmitField('Submit')

class DeleteChatForm(FlaskForm):
    submit = SubmitField('Delete Chat')

@app.route('/')
def index():
    receipt_items = receipt_agent.fetch_all_items()
    form = ReceiptUploadForm()
    return render_template('receipt.html', receipt_items=receipt_items, form=form)


@app.route('/stock')    
def stock():
    stock_items = stock_agent.fetch_all_items()
    stock_form = StockUploadForm()
    dsf = DeleteStockForm()
    return render_template('stock.html', stock_items=stock_items, stock_form=stock_form,dsf = dsf)

@app.route('/upload/receipt', methods=['POST'])
def upload_receipt():
    form = ReceiptUploadForm()
    if not form.validate_on_submit():
        flash('Invalid form submission')
        return redirect(url_for('index'))
    
    file = form.receipt_image.data
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
        flash(f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}")
        return redirect(url_for('index'))
    
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(temp_path)
    
    try:
        receipt_items = receipt_agent.process_receipt(temp_path)
        receipt_agent.save_data(receipt_items)
        flash(f"Processed and saved {len(receipt_items)} receipt items")
    except Exception as e:
        flash(f"Error processing receipt: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    return redirect(url_for('index'))

@app.route('/upload/stock', methods=['POST'])
def upload_stock():
    form = StockUploadForm()
    
    if not form.validate_on_submit():
        flash('Invalid form submission. Please ensure you’ve selected a valid file.', 'danger')
        logger.warning("Invalid form submission")
        return redirect(url_for('stock'))

    file = form.stock_image.data
    if not file:
        flash('No file selected', 'danger')
        logger.error("No file selected")
        return redirect(url_for('stock'))

    filename = secure_filename(file.filename)
    if not filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
        flash(f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}", 'danger')
        return redirect(url_for('stock'))
    
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        file.save(temp_path)
        stock_items = stock_agent.process_stock_image(temp_path)
        stock_agent.save_to_db(stock_items)
        flash(f"Processed and saved {len(stock_items)} stock items", 'success')
    except ValueError as e:
        logger.error(f"ValueError processing stock: {str(e)}")
        flash(f"Error processing stock: Make sure you have a valid groceries picture", 'danger')
    except Exception as e:
        logger.error(f"Unexpected error processing stock: {str(e)}")
        flash(f"Unexpected error: {str(e)}", 'danger')
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    return redirect(url_for('stock'))





@app.route('/chat', methods=['GET', 'POST'])
def chat():
    chat_form = ChatForm()
    response = None
    query = None

    if 'chat_history' not in session:
        session['chat_history'] = []

    if chat_form.validate_on_submit():
        query = chat_form.query.data
        try:
            # Get raw response from the analyzer
            raw_response = analyzer.query(query)
            
            # Convert markdown to HTML
            html_response = markdown(raw_response, extensions=['extra'])
            
            # Wrap the HTML in a styled container with Tailwind classes
            styled_response = f'''
            <div class="prose prose-sm max-w-none">
                {html_response}
            </div>
            <style>
                .prose h3 {{
                    @apply text-lg font-semibold text-green-600 flex items-center gap-2 mb-2;
                }}
                .prose p {{
                    @apply text-sm text-gray-700 mb-2;
                }}
                .prose ul {{
                    @apply list-disc list-inside text-sm text-gray-700 mb-2;
                }}
                .prose li {{
                    @apply mb-1;
                }}
                .prose strong {{
                    @apply font-semibold text-gray-800;
                }}
                /* Highlight Pro Tip section */
                .prose p:has(strong:contains("Pro Tip:")) {{
                    @apply mt-4 p-3 bg-yellow-50 rounded-lg shadow;
                }}
                .prose p:has(strong:contains("Pro Tip:")) strong {{
                    @apply text-yellow-600;
                }}
            </style>
            '''

            response = styled_response
            timestamp = datetime.now().strftime('%b %d, %H:%M')
            session['chat_history'].append({
                'text': query,
                'is_user': True,
                'timestamp': timestamp
            })
            session['chat_history'].append({
                'text': response,
                'is_user': False,
                'timestamp': timestamp
            })
            session.modified = True
            
            if request.headers.get('HX-Request'):
                return f'''
                <div class="animate-fade-in ml-auto bg-green-500 text-white max-w-[70%] rounded-lg p-3 shadow">
                    <p class="text-sm">{query}</p>
                    <span class="text-xs opacity-60 block mt-1">{timestamp}</span>
                </div>
                <div class="animate-fade-in mr-auto bg-gray-100 text-gray-800 max-w-[70%] rounded-lg p-3 shadow">
                    {response}
                    <span class="text-xs opacity-60 block mt-1">{timestamp}</span>
                </div>
                '''
            flash("Query processed successfully", "success")
        except ValueError as e:
            logger.error(f"ValueError processing query: {str(e)}")
            flash(f"Invalid query: {str(e)}", "danger")
        except Exception as e:
            logger.error(f"Unexpected error processing query: {str(e)}")
            flash(f"Error processing query: {str(e)}", "danger")
    elif request.method == 'POST':
        flash("Please enter a valid query", "danger")
        logger.warning("Invalid form submission on /chat")

    return render_template('chat.html', chat_form=chat_form, response=response, query=query, messages=session.get('chat_history', []))

@app.route('/delete_receipts', methods=['POST'])
def delete_receipts():
    try:
        receipt_agent.delete_all_items()
        flash('All receipts deleted successfully')
    except Exception as e:
        flash(f"Error deleting receipts: {str(e)}")
        logger.error(f"Error deleting receipts: {str(e)}")
    return redirect(url_for('index'))



@app.route('/delete_stock', methods=['POST'])
def delete_stock():
    
        dsf = DeleteStockForm()
        try:
            if dsf.validate_on_submit():
                    # Perform stock deletion logic
                    stock_agent.delete_stocks()
                    flash('All stock items deleted successfully!', 'success')
            else:
                    flash('Invalid form submission.', 'danger')
                    logger.warning("Invalid form submission detected.")
        except Exception as e:
            logger.error(f"Error deleting stock items: {str(e)}")
            flash('An error occurred while deleting stock items. Please try again.', 'danger')
        
        # Redirect back to the stock management page
        return redirect(url_for('stock'))


if __name__ == '__main__':
    app.run(debug=True,port=5001)