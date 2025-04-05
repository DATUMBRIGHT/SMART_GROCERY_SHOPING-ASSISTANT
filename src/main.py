from flask import Flask,render_template,url_for,redirect,flash,request
import requests
import sqlite3
import os
from pathlib import Path
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import random

from agents.grocery_agent import ReceiptProcessorAgent
from agents.stock_agent import StockProcessorAgent
from agents.grocery_analyzer import SmartGroceryAnalyzer

load_dotenv()

GEMINI_API_KEY = "AIzaSyDfSDWlscLwWRSShL_vhETx_mAP66BHito"
DEEPSEEK_API_KEY = "sk-5d891e91ae9a4450bcc4c5fb18274a9c"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

random.seed(42)
RECEIPT_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),'data','receipts_images')
STOCK_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),'data','fridge_images')
RECEIPT_IMAGE = os.path.join(RECEIPT_IMAGE_DIR, random.choice(os.listdir(RECEIPT_IMAGE_DIR)))
STOCK_IMAGE = os.path.join(STOCK_IMAGE_DIR, random.choice(os.listdir(STOCK_IMAGE_DIR)))



app = Flask(__name__)
app.secret_key = "bright_tenkorang"  # Required for flash messages
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Initialize agents and analyzer
  # Replace with your key
stock_agent = StockProcessorAgent(api_key=GEMINI_API_KEY)
receipt_agent = ReceiptProcessorAgent(api_key=GEMINI_API_KEY)
analyzer = SmartGroceryAnalyzer(stock_agent=stock_agent, receipt_agent=receipt_agent)

@app.route('/')
def index():
    return render_template('receipt.html')

@app.route('/upload/receipt', methods=['POST'])
def upload_receipt():
    if 'receipt_image' not in request.files:
        flash('No receipt image provided')
        return redirect(url_for('index'))
    
    file = request.files['receipt_image']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('index'))
    
    # Check if the file has a valid extension
    if not file.filename.lower().endswith(('.png', '.jpeg', '.jpg')):
        flash('Invalid file type. Please upload a .png, .jpeg, or .jpg file.')
        return redirect(url_for('index'))
    
    # Save the file temporarily
    upload_folder = 'uploads'  # Ensure this folder exists
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    
    filename = secure_filename(file.filename)  # Sanitize the filename
    temp_path = os.path.join(upload_folder, filename)
    file.save(temp_path)  # Save the uploaded file to disk
    
    try:
        receipt_items = receipt_agent.process_receipt(temp_path)
        receipt_agent.save_data(receipt_items)
        flash(f"Processed and saved {len(receipt_items)} receipt items")
    except Exception as e:
        flash(f"Error processing receipt: {str(e)}")
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    return redirect(url_for('index'))

@app.route('/upload/stock', methods=['POST'])
def upload_stock():
    if 'stock_image' not in request.files:
        flash('No stock image provided')
        return redirect(url_for('stock'))
    
    file = request.files['stock_image']
    filename = secure_filename(file.filename) 
    if filename == '':
        flash('No file selected')
        return redirect(url_for('stock'))
    
    if not filename.lower().endswith(('.png', '.jpeg', '.jpg')):
        flash('Invalid file type. Please upload a .png, .jpeg, or .jpg file.')
        return redirect(url_for('index'))
    
    # Save the file temporarily
    upload_folder = 'uploads'  # Ensure this folder exists
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    
      # Sanitize the filename
    temp_path = os.path.join(upload_folder, filename)
    file.save(temp_path)  # Save the uploaded file to disk
    
    try:
        data = stock_agent.process_stock_image(filename)
        stock_agent.save_to_db(data)
        flash(f"Processed and saved {len(data)} stock items")
        return redirect(url_for('stock'))
    except Exception as e:
        flash(f"Error processing stock: {str(e)}")
        return redirect(url_for('stock'))

@app.route('/edit_receipt/<int:item_id>', methods=['POST'])
def edit_receipt(item_id):
    name = request.form.get('name')
    quantity = request.form.get('quantity')
    weight = request.form.get('weight')
    category = request.form.get('category')
    purchase_date = request.form.get('purchase_date')
    expiration_date = request.form.get('expiration_date')
    
    try:
        conn = sqlite3.connect('receipts.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE receipts SET name=?, quantity=?, weight=?, category=?, purchase_date=?, expiration_date=?
            WHERE id=?
        ''', (name, quantity, weight, category, purchase_date, expiration_date, item_id))
        conn.commit()
        conn.close()
        flash('Receipt item updated successfully')
    except sqlite3.Error as e:
        flash(f"Error updating receipt: {str(e)}")
    return redirect(url_for('index'))

@app.route('/stock')
def stock():
    stock_items = stock_agent.fetch_all_items()
    return render_template('stock.html', stock_items=stock_items)

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        question = request.form.get('question')
        if not question:
            flash('Please ask a question!')
            return redirect(url_for('chat'))
        response = analyzer.query(question)
        return render_template('chat.html', question=question, response=response)
    return render_template('chat.html')

if __name__ == '__main__':
    app.run(debug=True)

   

    

    


