from flask import Flask, render_template, url_for, redirect, flash, request, jsonify,send_from_directory
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
import uuid
import yaml
import arrow
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


#home page
@app.route('/')
def index():
    receipt_items = receipt_agent.fetch_all_items()
    logger.info(f"Fetched {len(receipt_items)} receipt items")
    form = ReceiptUploadForm()
    return render_template('receipt.html', receipt_items=receipt_items, form=form)

#stock page
@app.route('/stock')    
def stock():
    stock_items = stock_agent.fetch_all_items()
    stock_form = StockUploadForm()
    dsf = DeleteStockForm()
    return render_template('stock.html', stock_items=stock_items, stock_form=stock_form,dsf = dsf)


#upload receipt page
@app.route('/upload/receipt', methods=['POST'])
def upload_receipt():
    form = ReceiptUploadForm()
    if not form.validate_on_submit():
        flash('Invalid form submission')
        receipt_items = receipt_agent.fetch_all_items()
        return render_template('receipt.html', form=form, receipt_items=receipt_items)
    
    file = form.receipt_image.data
    filename = secure_filename(file.filename)
    file_ext = os.path.splitext(filename)[1].lower()  # e.g., '.jpg'
    if file_ext not in ALLOWED_EXTENSIONS:
        flash(f"Invalid file type. Allowed types: {', '.join(ext.lstrip('.') for ext in ALLOWED_EXTENSIONS)}")
        logger.warning(f"Invalid file type: {filename}")
        receipt_items = receipt_agent.fetch_all_items()
        return render_template('receipt.html', form=form, receipt_items=receipt_items)
    
    # Generate unique filename
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    session['receipt_filename'] = unique_filename
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(temp_path)
    
    try:
        # Process receipt but don't save to DB
        receipt_items = receipt_agent.process_receipt(temp_path)
        session['receipt_items'] = receipt_items
        receipt_agent.save_data(receipt_items)
        logger.info(f"Processed {len(receipt_items)} receipt items")
        flash(f"Processed {len(receipt_items)} receipt items")
       
        
        # Handle GET request
        filename = session.get('receipt_filename')
        receipt_items = session.get('receipt_items', receipt_agent.fetch_all_items())
        return render_template('receipt.html', form=form, filename=filename,receipt_items=receipt_items)
        
        
    except Exception as e:
        flash(f"Error processing receipt: {str(e)}")
        logger.error(f"Error processing receipt: {str(e)}")
        receipt_items = None
        # Delete image only on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return render_template('receipt.html', form=form, receipt_items=receipt_items)
    
    

@app.route('/uploads/<filename>')
def serve_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    
#upload stock page
@app.route('/upload/stock', methods=['POST'])
def upload_stock():
    form = StockUploadForm()
    dsf = DeleteStockForm()

    #check if form is not submitted render oroginal page
    if not form.validate_on_submit():
        flash('Invalid form submission. Please ensure you’ve selected a valid file.', 'danger')
        logger.warning("Invalid form submission")
        return redirect(url_for('stock'))

    file = form.stock_image.data #get data from form 
    
    #check if form has no data stock image file
    if not file:
        flash('No file selected', 'danger')
        logger.error("No file selected")
        return redirect(url_for('stock'))
    

    #get secure file name
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
        flash(f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}", 'danger')
        return redirect(url_for('stock'))
    
    #generate unique filename
    filename = f"{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}"
    
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        file.save(temp_path) #save image
        logger.info(f"Saved image to {temp_path}")
        stock_items = stock_agent.process_stock_image(temp_path)
        stock_agent.save_to_db(stock_items)
        flash(f"Processed and saved {len(stock_items)} stock items", 'success')
    except ValueError as e:
        logger.error(f"ValueError processing stock: {str(e)}")
        flash(f"Error processing stock: Make sure you have a valid groceries picture", 'danger')
    except Exception as e:
        logger.error(f"Unexpected error processing stock: {str(e)}")
        flash(f"Unexpected error: {str(e)}", 'danger')
    # Handle GET request
    
    return render_template('stock.html', stock_items=stock_items, stock_form=form,filename = filename,dsf = dsf)

#chat page
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    chat_form = ChatForm()
    clear_chat_form = DeleteChatForm() 
    response = None
    query = None

    if 'chat_history' not in session:
        session['chat_history'] = []

    if chat_form.validate_on_submit():
        query = chat_form.query.data
        try:
            raw_response = analyzer.query(query)
            html_response = markdown(raw_response, extensions=['extra'])
            styled_response = f'''
            <div class="prose prose-sm max-w-none">
                {html_response}
            </div>
            '''
            response = styled_response
            timestamp = arrow.now().format('MMM D, HH:mm')

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

    return render_template('chat.html', chat_form=chat_form, clear_chat_form=clear_chat_form, response=response, query=query, messages=session.get('chat_history', []))

#clear chat 
@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    try:
        clear_chat_form = DeleteChatForm()
        logger.debug(f"Clear chat form data: {request.form}, CSRF: {clear_chat_form.csrf_token.data}")
        if clear_chat_form.validate_on_submit():
            session['chat_history'] = []  # Clear chat history (your exact line)
            session.modified = True
            flash('Chat history cleared successfully', 'success')
            logger.info("Chat history cleared successfully")
            if request.headers.get('HX-Request'):
                logger.debug("Returning HTMX response for clear chat")
                return '<div id="chat-window" class="flex-1 overflow-y-auto p-4 space-y-4 animate-fade-in"><div class="text-center text-gray-500 text-sm mt-4">Start the conversation by asking a question!</div></div>'
            return redirect(url_for('chat'))  # Your redirect
        else:
            flash('Failed to clear chat history. Please try again.', 'error')  # Your message
            logger.warning(f"Form validation failed: {clear_chat_form.errors}")
            if request.headers.get('HX-Request'):
                return '<div id="chat-window" class="flex-1 overflow-y-auto p-4 space-y-4 animate-fade-in"><div class="text-center text-gray-500 text-sm mt-4">Start the conversation by asking a question!</div></div>', 400
            return redirect(url_for('chat')), 400  # Your status
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'error')  # Your message
        logger.error(f"Error clearing chat: {str(e)}")
        if request.headers.get('HX-Request'):
            return '<div id="chat-window" class="flex-1 overflow-y-auto p-4 space-y-4 animate-fade-in"><div class="text-center text-gray-500 text-sm mt-4">Start the conversation by asking a question!</div></div>', 500
        return redirect(url_for('chat')), 500


#delete receipts
@app.route('/delete_receipts', methods=['POST'])
def delete_receipts():
    try:
        receipt_agent.delete_all_items()
        flash('All receipts deleted successfully')
    except Exception as e:
        flash(f"Error deleting receipts: {str(e)}")
        logger.error(f"Error deleting receipts: {str(e)}")
    return redirect(url_for('index'))


#delete stock
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
    app.run(debug=True,port=5002)