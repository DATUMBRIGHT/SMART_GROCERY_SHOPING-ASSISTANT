import sys
import os


current_dir = os.path.dirname(os.path.abspath(__file__))


if current_dir not in sys.path:
    sys.path.insert(0, current_dir)


from agents.grocery_agent import ReceiptProcessorAgent
from agents.stock_agent import StockProcessorAgent
from agents.grocery_analyzer import GroceryAnalyzer
from loggers.custom_logger import logger
from db_managers.db_manager import DBManager
from db_managers.email_sender import EmailSender
from db_managers.scheduler import Scheduler
import csv
from io import StringIO

from flask import Flask, render_template, url_for, redirect, flash, request, jsonify, send_from_directory, make_response, Response
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import FileField, SubmitField, StringField, PasswordField, BooleanField, IntegerField
from wtforms.validators import DataRequired, NumberRange, Optional, Email, Length, EqualTo
from wtforms import validators
from flask import session
import mysql.connector
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import uuid
import yaml
import arrow
from threading import Lock
from collections import defaultdict
from mysql.connector import pooling
from datetime import datetime, timedelta
from markdown import markdown
import torch
torch.set_num_threads(1)
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

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
        ALLOWED_EXTENSIONS = set(config['upload']['allowed_extensions'])
        MAX_CONTENT_LENGTH = config['upload']['max_content_length']
        DB_CONFIG = {
            "host": os.getenv("MYSQL_HOST", "flaskapp-mysql-server.mysql.database.azure.com"),
            "port": 3306,
            "user": os.getenv("MYSQL_HOST","flaskappadmin"),
            "password": os.getenv("MYSQL_PASSWORD", "fuckshit_1Z"),  # ⚠️ replace in production
            "database": os.getenv("MYSQL_DB", "grocery_db"),
            "ssl_ca":  os.getenv('DB_SSL_CA', '/app/certs/BaltimoreCyberTrustRoot.crt.pem'),
     }

except FileNotFoundError:
    raise Exception("Configuration file not found at: " + CONFIG_PATH)
except KeyError as e:
    raise Exception(f"Missing configuration key: {str(e)}")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY")
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_URL, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.permanent_session_lifetime = 3600
app.config['SESSION_COOKIE_SECURE'] = True  # Only send over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
chat_lock = Lock()
app_context = app.app_context()
scheduler = Scheduler(app = app)
# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize database connection pool
db_pool = pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **DB_CONFIG)



#email sender
email_sender = EmailSender()


db_manager = DBManager()
# Initialize agents and analyzer
stock_agent = StockProcessorAgent(api_key=GEMINI_API_KEY)
receipt_agent = ReceiptProcessorAgent(api_key=GEMINI_API_KEY)

analyzer = GroceryAnalyzer(stock_agent=stock_agent, receipt_agent=receipt_agent,db_manager = db_manager)


# Form for receipt upload
class ReceiptUploadForm(FlaskForm):
    receipt_image = FileField('Receipt Image', validators=[DataRequired()])
    submit = SubmitField('Upload Receipt')

class StockUploadForm(FlaskForm):
    stock_image = FileField('Stock Image', validators=[DataRequired()])
    submit = SubmitField('Upload Stock')

class DeleteStockForm(FlaskForm):
    submit = SubmitField('Delete Stock')

class DeleteReceiptForm(FlaskForm):
    submit = SubmitField('Delete Receipt')

class ChatForm(FlaskForm):
    query = StringField('Query', validators=[DataRequired()])
    submit = SubmitField('Submit')

class DeleteChatForm(FlaskForm):
    submit = SubmitField('Delete Chat')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class SignupForm(FlaskForm):
    username = StringField('Username', [
        validators.DataRequired(),
        validators.Length(min=4, max=25)
    ])
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email(),
        validators.Length(max=50)
    ])
    password = PasswordField('Password', [
        validators.DataRequired(),
        validators.Length(min=8),
        validators.EqualTo('confirm_password', message='Passwords must match')
    ])
    confirm_password = PasswordField('Confirm Password')
    vegetarian = BooleanField('Vegetarian')
    vegan = BooleanField('Vegan')
    gluten_free = BooleanField('Gluten Free')
    allergies = StringField('Allergies')
    extra_info = StringField('Health Information')



@app.route('/', methods=['GET', 'POST'])
def login_page():
    login_form = LoginForm()
    
    return render_template('login.html', login_form=login_form)



@app.route('/signup', methods=['GET', 'POST'])
def signup():
    form = SignupForm(request.form)
    
    if request.method == 'POST' and form.validate_on_submit():
        try:
            # Check existing email
            if db_manager.check_if_email_already_exists(form.email.data):
                form.email.errors.append('This email is already registered')
                if request.headers.get('HX-Request'):
                    return render_template('auth/partials/signup_form.html', 
                                        form=form), 400
                return render_template('auth/signup.html', form=form)

            # Check existing username
            if db_manager.check_if_username_already_exists(form.username.data):
                form.username.errors.append('Username is already taken')
                if request.headers.get('HX-Request'):
                    return render_template('auth/partials/signup_form.html', 
                                        form=form), 400
                return render_template('auth/signup.html', form=form)

            # Create user
            user_id = db_manager.create_user(
                username=form.username.data,
                email=form.email.data,
                password=form.password.data,
                vegetarian=form.vegetarian.data,
                vegan=form.vegan.data,
                gluten_free=form.gluten_free.data,
                allergies=form.allergies.data,
                extra_info=form.extra_info.data
            )

            # Set session
            session['user_id'] = user_id
            session['username'] = form.username.data
            session['email'] = form.email.data
            email_sender.send_welcome_email(recipient_email=session['email'],
                                            username = session['username'] or 'user',
                                            email = session['email'])

            # HTMX response
            if request.headers.get('HX-Request'):
                response = make_response()
                response.headers['HX-Redirect'] = url_for('dashboard')
                return response

            flash('Account created successfully!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            app.logger.error(f"Signup error: {str(e)}")
            error = "An error occurred during signup. Please try again."
            if request.headers.get('HX-Request'):
                return render_template('auth/partials/signup_form.html', form=form, form_error=error), 500
            flash(error, 'danger')
            return redirect(url_for('signup'))

    # Handle validation errors
    if form.errors:
        if request.headers.get('HX-Request'):
            return render_template('auth/partials/signup_form.html', form=form), 400
        flash('Please correct the form errors', 'danger')

    return render_template('auth/signup.html', form=form)

@app.route('/check-username', methods=['POST'])
def check_username():
    username = request.form.get('username')
    exists = db_manager.check_if_username_already_exists(username)
    return 'Username already taken' if exists else ''

@app.route('/check-email', methods=['POST'])
def check_email():
    email = request.form.get('email')
    if not email:
        return ""
        
    # Validate email format first
    form = SignupForm(email=email)
    form.validate()
    if form.email.errors:
        return render_template('auth/partials/email_errors.html', 
                            errors=form.email.errors)
    
    # Check database
    exists = db_manager.check_if_email_already_exists(email)
    if exists:
        return render_template('auth/partials/email_errors.html',
                            errors=['Email already registered'])
    
    return ""


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        try:
            user_id = db_manager.auth_user(email, password)
            if user_id:
                user_details = db_manager.fetch_user_by_email(email)
                session['user_id'] = user_id
                session['email'] = user_details['email']
                session['first_name'] = user_details['first_name']
                session['last_name'] = user_details['last_name']  # Fixed typo
                session['age'] = user_details['age']
                session['gluten'] = user_details['gluten_free']
                session['vegan'] = user_details['vegan']
                session['extra_info'] = user_details['extra_info']
                session['username'] = user_details['username']
                session['allergies'] = user_details['allergies']
                
                logger.info("User logged in successfully")
                email_sender.send_email(recipient_email=session['email'],
                                        subject="Login Notification",
                                        body=f"User {session['username']} logged in at {arrow.now().format('YYYY-MM-DD HH:mm:ss')}")
                if request.headers.get('HX-Request'):
                    response = make_response('<div class="text-green-500 font-semibold">Login successful! Redirecting...</div>')
                    response.headers['HX-Redirect'] = url_for('dashboard')
                    return response
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            else:
                logger.info("Login failed due to invalid credentials")
                if request.headers.get('HX-Request'):
                    return '<div class="text-red-500 font-semibold">Invalid email or password. Please try again.</div>', 401
                flash('Invalid email or password. Please try again.', 'danger')
                return render_template('login.html', login_form=form)
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            if request.headers.get('HX-Request'):
                return '<div class="text-red-500 font-semibold">An error occurred. Please try again later.</div>', 500
            flash('An error occurred. Please try again later.', 'danger')
            return render_template('login.html', login_form=form)
    else:
        # Handle form validation errors
        errors = form.errors
        if errors:
            logger.info("Invalid form submission")
            if request.headers.get('HX-Request'):
                error_msg = '<div class="text-red-500 font-semibold">' + '<br>'.join([f"{field}: {error[0]}" for field, error in errors.items()]) + '</div>'
                return error_msg, 400
            flash('Invalid form submission. Please check your inputs.', 'danger')
        return render_template('login.html', login_form=form)


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please log in.', 'danger')
        return redirect(url_for('login_page'))
    
    user_id = session['user_id']
    form = DeleteReceiptForm()
    user = db_manager.fetch_user_id(user_id)
    
    # Fetch data
    all_receipt_items = receipt_agent.fetch_all_receipts_items(user_id)
    uploaded_receipts = receipt_agent.get_all_receipts(user_id)
    
    # Basic metrics
    total_spent = sum(float(item['price']) for item in all_receipt_items)
    total_receipts = len(uploaded_receipts)
    total_items = sum(row[2] for row in uploaded_receipts)
    avg_items_per_receipt = round(total_items / total_receipts, 1) if total_receipts else 0
    recent_receipt = uploaded_receipts[0] if uploaded_receipts else None
    avg_receipt_value = sum(float(row[1]) for row in uploaded_receipts) / total_receipts if total_receipts else 0
    
    # Categories
    categories = defaultdict(float)
    for item in all_receipt_items:
        categories[item['category']] += float(item['price'])
    top_category = max(categories.items(), key=lambda x: x[1], default=('None', 0))[0] if categories else 'None'
    
    # Expiring and low stock
    expiring_soon = []
    low_stock = []
    seven_days_from_now = (datetime.now() + timedelta(days=7)).date()
    for item in all_receipt_items:
        if item['expiration_date']:
            try:
                exp_date = datetime.strptime(item['expiration_date'], '%Y-%m-%d').date()
                if exp_date < seven_days_from_now:
                    expiring_soon.append({
                        'name': item['name'],
                        'quantity': item['quantity'],
                        'expiration_date': item['expiration_date']
                    })
            except ValueError:
                pass
        if item['quantity'] <= 2:
            low_stock.append({
                'name': item['name'],
                'quantity': item['quantity']
            })
    
    # Advanced analytics
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Monthly spending
        cursor.execute("""
            SELECT DATE_FORMAT(purchase_date, '%Y-%m') as month, SUM(price) as total
            FROM receipts
            WHERE user_id = %s
            GROUP BY month
            ORDER BY month
        """, (user_id,))
        monthly_spending = [{'month': r['month'], 'total': round(float(r['total']), 2)} for r in cursor.fetchall()]
        
        # Receipts by month
        cursor.execute("""
            SELECT DATE_FORMAT(created_at, '%Y-%m') as month, COUNT(*) as count
            FROM all_receipts
            WHERE user_id = %s
            GROUP BY month
            ORDER BY month
        """, (user_id,))
        receipts_by_month = [{'month': r['month'], 'count': r['count']} for r in cursor.fetchall()]
        
        # Category diversity and most purchased
        cursor.execute("""
            SELECT COUNT(DISTINCT category) as diversity,
                   name, COUNT(*) as count
            FROM receipts
            WHERE user_id = %s
            GROUP BY name
            ORDER BY count DESC
            LIMIT 1
        """, (user_id,))
        category_info = cursor.fetchone()
        category_diversity = category_info['diversity'] if category_info else 0
        most_purchased = category_info['name'] if category_info else 'None'
        
        # Vegetarian items
        vegetarian_count = 0
        if user and user.get('vegetarian'):
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM receipts
                WHERE user_id = %s AND category IN ('Fruit', 'Vegetables')
            """, (user_id,))
            vegetarian_count = cursor.fetchone()['count']
        
        # Receipt frequency
        cursor.execute("""
            SELECT COUNT(*) / GREATEST(DATEDIFF(MAX(created_at), MIN(created_at)), 1) as frequency
            FROM all_receipts
            WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        receipt_frequency = round(float(result['frequency']), 1) if result and result['frequency'] is not None else 0
        
        cursor.close()
        conn.close()

        #send grocery summary
        if not scheduler:
            logger.info('scheduler doeesnt exist reinitializing')
            scheduler.start(func = lambda :email_sender.send_grocery_summary(app_context, session['email'], 
                                                                             low_stock, 
                                                                             expiring_soon),
                                                                             id ='grocery_summary',
                                                                             replace_existing = False,
                                                                              misfire_grace_time=60,  # Grace period before marking a missed execution
                                                                            max_instances=1,  
                                                                            next_run_time=None)
        
    except mysql.connector.Error as e:
        logger.error(f"Database error: {e}")
        monthly_spending = []
        receipts_by_month = []  # Ensure defined
        category_diversity = 0
        most_purchased = 'None'
        vegetarian_count = 0
        receipt_frequency = 0
        
    return render_template(
        'dashboard.html',
        all_receipt_items=all_receipt_items,
        uploaded_receipts=[{
            'id': row[0],
            'total_amount': float(row[1]),
            'total_items': row[2],
            'created_at': row[3].strftime('%Y-%m-%d') if row[3] else None
        } for row in uploaded_receipts],
        total_spent=round(total_spent, 2),
        total_receipts=total_receipts,
        total_items=total_items,
        avg_items_per_receipt=avg_items_per_receipt,
        recent_receipt=recent_receipt,
        avg_receipt_value=round(avg_receipt_value, 2),
        categories=dict(categories),
        top_category=top_category,
        expiring_soon=expiring_soon,
        low_stock=low_stock,
        monthly_spending=monthly_spending,
        receipts_by_month=receipts_by_month,  # Added
        category_diversity=category_diversity,
        most_purchased=most_purchased,
        vegetarian_count=vegetarian_count,
        receipt_frequency=receipt_frequency,
        user=user,
        form=form
    )

    

@app.route('/upload/receipt', methods=['GET', 'POST'])
def upload_receipt():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to access the receipts page.', 'danger')
        return redirect(url_for('login_page'))
    
    form = ReceiptUploadForm()
    drf = DeleteReceiptForm()
    receipt_id = session.get('last_receipt_id')
    # Fetch filename and receipt items, with fallbacks
    display_filename = receipt_agent.get_latest_filename(user_id, receipt_id) if receipt_id else None
    print(display_filename)
    receipt_items = session.get('receipt_items') or receipt_agent.fetch_receipt_items_by_id(receipt_id, user_id) or []

    if request.method == 'POST':
        if not form.validate_on_submit():
            flash('Invalid form submission.', 'danger')
            return render_template('receipt.html', filename=display_filename, receipt_items=receipt_items, form=form,delete_form = drf)

        file = form.receipt_image.data
        print(f"file : {file}")
        if not file:
            flash('No file uploaded.', 'danger')
            return render_template('receipt.html', filename=display_filename, receipt_items=receipt_items,form=form,delete_form = drf)

        original_filename = secure_filename(file.filename)
        print(f"original_filename : {original_filename}")
        file_ext = os.path.splitext(original_filename)[1].lower()
        print(f"file_ext : {file_ext}")
        if file_ext not in ALLOWED_EXTENSIONS:
            flash(f"Invalid file type. Allowed types: {', '.join(ext.lstrip('.') for ext in ALLOWED_EXTENSIONS)}", 'danger')
            logger.warning(f"Invalid file type: {original_filename}")
            return render_template('receipt.html', filename=display_filename, receipt_items=receipt_items, form=form)

        # Generate unique filename and save file
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        print(f"unique_filename : {unique_filename}")
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        print(f"temp_path : {temp_path} ")
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(temp_path)
        logger.debug(f"Saved file: {temp_path}, exists: {os.path.exists(temp_path)}")
        
        try:
            # Process receipt and save data
            receipt_items = receipt_agent.process_receipt(temp_path)
            receipt_id = receipt_agent.save_data(receipt_items, user_id)
            receipt_agent.save_image(unique_filename, user_id, receipt_id)
            
            # Update session
            session['last_receipt_id'] = receipt_id
            session['last_receipt_file'] = unique_filename 
            session['receipt_items'] = receipt_items
            
            
            logger.info(f"Processed {len(receipt_items)} receipt items")
            flash(f"Processed {len(receipt_items)} receipt items successfully.", 'success')
            return render_template('receipt.html', filename=unique_filename or receipt_agent.get_latest_filename(user_id, receipt_id), receipt_items=receipt_items,form=form,delete_form = drf)

        except (ValueError, IOError,Exception) as e:
            flash(f"Error processing receipt. Check if receipt is not empty or valid groceries. Please try again!", 'danger')
            logger.error(f"Error processing receipt: {str(e)}")
            if os.path.exists(temp_path):
                os.remove(temp_path)  # Clean up temporary file
            return render_template('receipt.html', filename=display_filename, receipt_items=receipt_items,form=form,delete_form = drf)
        
    return render_template('receipt.html', form=form, filename=display_filename, receipt_items=receipt_items,delete_form = drf)

# HTMX endpoint for receipts table
@app.route('/dashboard/receipts-table')
def receipts_table():
    if 'user_id' not in session:
        return '<p>Please log in.</p>'
    
    user_id = session['user_id']
    uploaded_receipts = receipt_agent.get_all_receipts(user_id)
    
    # Filter by date range
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if start_date and end_date:
        try:
            uploaded_receipts = [
                r for r in uploaded_receipts
                if start_date <= r[3].strftime('%Y-%m-%d') <= end_date
            ]
        except ValueError:
            pass
    
    # Sort
    sort_by = request.args.get('sort_by', 'created_at')
    reverse = request.args.get('sort_order', 'desc') == 'desc'
    sort_key = {
        'total_amount': 1,
        'total_items': 2,
        'created_at': 3
    }.get(sort_by, 3)
    uploaded_receipts.sort(
        key=lambda x: x[sort_key] if sort_key != 3 else x[sort_key].timestamp(),
        reverse=reverse
    )
    
    return render_template(
        'receipts_table.html',
        uploaded_receipts=[{
            'id': row[0],
            'total_amount': float(row[1]),
            'total_items': row[2],
            'created_at': row[3].strftime('%Y-%m-%d') if row[3] else None
        } for row in uploaded_receipts]
    )

# HTMX endpoint for receipt items sub-table
@app.route('/dashboard/receipt-items/<int:receipt_id>')
def receipt_items(receipt_id):
    if 'user_id' not in session:
        return '<p>Please log in.</p>'
    
    user_id = session['user_id']
    items = receipt_agent.fetch_receipt_items_by_id(receipt_id, user_id)
    return render_template(
        'receipt_items.html',
        items=items,
        receipt_id=receipt_id
    )

# Delete specific receipt
@app.route('/dashboard/delete-receipt/<int:receipt_id>', methods=['POST'])
def delete_receipt(receipt_id):
    form = DeleteReceiptForm()
    if 'user_id' not in session:
        flash('Please log in.', 'danger')
        return redirect(url_for('login_page'))
    
    user_id = session['user_id']
    try:
        receipt_agent.delete_receipt(receipt_id, user_id)
        flash('Receipt deleted successfully.', 'success')
        if request.headers.get('HX-Request'):
            return '<div hx-swap-oob="true" id="receipts-table"></div>'
    except Exception as e:
        logger.error(f"Error deleting receipt: {e}")
        flash('Error deleting receipt.', 'danger')
    return render_template('dashboard.html', form=form)


@app.route('/receipt/delete-receipt', methods=['POST'])
def delete_receipt_page():
    user_id = session.get('user_id')
    receipt_id = session.get('last_receipt_id')
    if not user_id:
        flash('Please log in to access the receipts page.', 'danger')
        return redirect(url_for('login_page'))

    form = DeleteReceiptForm()
    if not form.validate_on_submit():
        flash('Invalid form submission.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        receipt_agent.delete_receipt(receipt_id, user_id)
        session.pop('last_receipt_id', None)
        session.pop('receipt_items', None)
        session.pop('last_receipt_file', None)
        flash('Receipt deleted successfully.', 'success')
    except (ValueError, IOError) as e:
        flash(f"Error deleting receipt: {str(e)}", 'danger')
        logger.error(f"Error deleting receipt: {str(e)}")

    return redirect(url_for('dashboard'))


# Reset all receipts
@app.route('/reset_receipts', methods=['POST'])
def reset_receipts():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to access the receipts page.', 'danger')
        return redirect(url_for('login_page'))
    
    form = DeleteReceiptForm()
    if not form.validate_on_submit():
        flash('Invalid form submission.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        receipt_agent.delete_all_receipt_items(user_id)
        session.pop('all_receipt_items', None)
        session.pop('last_receipt_id', None)
        session.pop('receipt_items', None)
        session.pop('last_receipt_file', None)
        flash('All receipts deleted successfully.', 'success')
    except (ValueError, IOError) as e:
        flash(f"Error deleting receipts: {str(e)}", 'danger')
        logger.error(f"Error deleting receipts: {str(e)}")
    
    return redirect(url_for('dashboard'))

# Analytics data for charts
@app.route('/dashboard/analytics-data')
def analytics_data():
    if 'user_id' not in session:
        return jsonify({'error': 'Please log in.'})
    
    user_id = session['user_id']
    time_period = request.args.get('time_period', 'all')
    category = request.args.get('category')
    
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Category spending
        query = """
            SELECT category, SUM(price) as total
            FROM receipts
            WHERE user_id = %s
        """
        params = [user_id]
        
        if time_period != 'all':
            if time_period == '30_days':
                query += " AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
            elif time_period == 'this_year':
                query += " AND YEAR(purchase_date) = YEAR(CURDATE())"
        
        if category:
            query += " AND category = %s"
            params.append(category)
        
        query += " GROUP BY category"
        
        cursor.execute(query, params)
        categories = {r['category']: round(float(r['total']), 2) for r in cursor.fetchall()}
        
        # Monthly spending
        query = """
            SELECT DATE_FORMAT(purchase_date, '%Y-%m') as month, SUM(price) as total
            FROM receipts
            WHERE user_id = %s
        """
        params = [user_id]
        
        if time_period != 'all':
            if time_period == '30_days':
                query += " AND purchase_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
            elif time_period == 'this_year':
                query += " AND YEAR(purchase_date) = YEAR(CURDATE())"
        
        query += " GROUP BY month ORDER BY month"
        
        cursor.execute(query, params)
        monthly_spending = [{'month': r['month'], 'total': round(float(r['total']), 2)} for r in cursor.fetchall()]
        
        # Receipts by month
        query = """
            SELECT DATE_FORMAT(created_at, '%Y-%m') as month, COUNT(*) as count
            FROM all_receipts
            WHERE user_id = %s
        """
        params = [user_id]
        
        if time_period != 'all':
            if time_period == '30_days':
                query += " AND created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
            elif time_period == 'this_year':
                query += " AND YEAR(created_at) = YEAR(CURDATE())"
        
        query += " GROUP BY month ORDER BY month"
        
        cursor.execute(query, params)
        receipts_by_month = [{'month': r['month'], 'count': r['count']} for r in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'categories': categories,
            'monthly_spending': monthly_spending,
            'receipts_by_month': receipts_by_month
        })
    except mysql.connector.Error as e:
        logger.error(f"Database error: {e}")
        return jsonify({'error': 'Error fetching data.'})

# CSV export
@app.route('/dashboard/export')
def export_analytics():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    user_id = session['user_id']
    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Category spending
        cursor.execute("""
            SELECT category, SUM(price) as total
            FROM receipts
            WHERE user_id = %s
            GROUP BY category
        """, (user_id,))
        category_data = cursor.fetchall()
        
        # Monthly spending
        cursor.execute("""
            SELECT DATE_FORMAT(purchase_date, '%Y-%m') as month, SUM(price) as total
            FROM receipts
            WHERE user_id = %s
            GROUP BY month
        """, (user_id,))
        monthly_data = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Generate CSV
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Type', 'Key', 'Value'])
        for row in category_data:
            writer.writerow(['Category Spending', row['category'], round(float(row['total']), 2)])
        for row in monthly_data:
            writer.writerow(['Monthly Spending', row['month'], round(float(row['total']), 2)])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=analytics.csv'}
        )
    except mysql.connector.Error as e:
        logger.error(f"Database error: {e}")
        flash('Error exporting data.', 'danger')
        return redirect(url_for('dashboard'))


@app.route('/receipts')
def index():
    if 'user_id' not in session:
        flash('Please log in to access the receipts page.', 'danger')
        return redirect(url_for('login_page'))
    
    user_id = session['user_id']
    form = ReceiptUploadForm()
    delete_form = DeleteReceiptForm()
    
    try:
        # Fetch the latest receipt ID if not in session
        receipt_id = session.get('last_receipt_id') 
        if not receipt_id:
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id
                FROM all_receipts
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            result = cursor.fetchone()
            receipt_id = result[0] if result else None
            cursor.close()
            conn.close()
        
        # Fetch receipt items, default to empty list if none found
        receipt_items = receipt_agent.fetch_receipt_items_by_id(receipt_id, user_id) if receipt_id else []
        
        # Fetch filename for the receipt image
        filename = session.get('last_receipt_file') or  receipt_agent.get_latest_filename(user_id,receipt_id) 
        
        # Fetch user data for consistency with dashboard
        user = db_manager.fetch_user_id(user_id)
        
        return render_template(
            'receipt.html',
            receipt_items=receipt_items,
            form=form,
            delete_form=delete_form,
            filename=filename,
            user=user,
            receipt_id=receipt_id
        )
    except mysql.connector.Error as e:
        logger.error(f"Error fetching receipt data: {e}")
        flash('Error loading receipt data.', 'danger')
        return redirect(url_for('index'))

# Chatbot for receipt queries
@app.route('/dashboard/chat', methods=['POST'])
def dashboard_chat():
    if 'user_id' not in session:
        return jsonify({'response': 'Please log in.'})
    
    user_id = session['user_id']
    query = request.form.get('query')
    if not query:
        return jsonify({'response': 'Please enter a query.'})
    
    try:
        raw_response = analyzer.query(query)
        html_response = markdown(raw_response, extensions=['extra'])
        styled_response = f'''
        <div class="prose prose-sm max-w-none">
            {html_response}
        </div>
        '''
        timestamp = arrow.now().format('MMM D, HH:mm')
        
        # Append to chat history
        if 'chat_history' not in session:
            session['chat_history'] = []
        session['chat_history'].append({
            'text': query,
            'is_user': True,
            'timestamp': timestamp
        })
        session['chat_history'].append({
            'text': styled_response,
            'is_user': False,
            'timestamp': timestamp
        })
        session.modified = True
        
        return jsonify({'response': styled_response, 'timestamp': timestamp})
    except Exception as e:
        logger.error(f"Error processing query: {e}")
        return jsonify({'response': 'Error processing query.'})

#general route for image serving
@app.route('/uploads/<filename>')
def serve_image(filename):
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to access the receipts page.', 'danger')
        return redirect(url_for('login_page'))
    logger.info(f"Serving image: {filename}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login_page'))


@app.route('/stock',)
def stock():
    user_id = session.get('user_id')
    if 'user_id' not in session:
        flash('Please log in to access the stock page.', 'danger')
        return redirect(url_for('login_page'))
    stock_id = session.get('last_stock_id') 
    print(f"Stock ID: {stock_id}")
    stock_items = stock_agent.fetch_stock(user_id,stock_id)
    form = StockUploadForm()
    dsf = DeleteStockForm()
    filename = stock_agent.get_latest_filename(user_id)  # Add for image display
    print(f"Filename: {filename}")
    logger.debug(f"Stock: Rendering stock.html with filename={filename}")
    return render_template('stock.html', stock_items=stock_items, form=form, dsf=dsf, filename=filename)

@app.route('/upload/stock', methods=['GET', 'POST'])
def upload_stock():
    user_id = session.get('user_id')
    logger.debug(f"Stock: Received request for upload_stock, user_id={user_id}")
    stock_id = session.get('last_stock_id')
    print(f"Stock ID: {stock_id}")

    if 'user_id' not in session:
        flash('Please log in to access the stock page.', 'danger')
        return redirect(url_for('login_page'))
    form = StockUploadForm()
    dsf = DeleteStockForm()  # Add for consistency
    latest_filename = stock_agent.get_latest_filename(user_id) or session.get('lastest_stock_file')
    print(f"Latest Filename: {latest_filename}")
    stock_items = stock_agent.fetch_stock(user_id,stock_id)  # Prefer DB over session

    if request.method == 'POST':
        if form.validate_on_submit():
            file = form.stock_image.data
            print(f"File: {file}")
            filename = secure_filename(file.filename)
            print(f"Filename: {filename}")
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in ALLOWED_EXTENSIONS:
                flash(f"Invalid file type. Allowed types: {', '.join(ext.lstrip('.') for ext in ALLOWED_EXTENSIONS)}")
                logger.warning(f"Invalid file type: {filename}")
                return render_template('stock.html', form=form, dsf=dsf, stock_items=stock_items, filename=latest_filename)

            # Generate unique filename
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            print(f"unique_filename : {unique_filename}")
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            print(f"temp_path : {temp_path}")
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(temp_path)
            
            
            logger.debug(f"Saved file: {temp_path}, exists: {os.path.exists(temp_path)}")

            try:
                 
                stock_items = stock_agent.process_stock_image(temp_path) # process with long path
                logger.info(f"processed {unique_filename} stock successfully")
                stock_id = stock_agent.save_to_db(stock_items,user_id,unique_filename) #save to db with unique_filenmame
                
                session['last_stock_id'] = stock_id
                session['lastest_stock_file'] = unique_filename #save unique file name to session
                print(f"session_latest_stocK: {session['latest_stock_file']}")
                logger.info(f"Processed {len(stock_items)} stock items")
                flash(f"Processed stock items")
                filename = session['lastest_stock_file'] or stock_agent.get_latest_filename(user_id)   # Update
                return render_template('stock.html', form=form, dsf=dsf, stock_items=stock_items, filename=filename )
            except Exception as e:
                flash(f"Error processing stock: {str(e)}")
                logger.error(f"Error processing stock: {str(e)}")
                
                
                return render_template('stock.html', form=form, dsf=dsf, stock_items=stock_items, filename=unique_filename or session['lastest_stock_file'] )

       

        else:
            flash('Invalid form submission')
    
    filename = session['lastest_stock_file'] or stock_agent.get_latest_filename(user_id)
    logger.debug(f"GET: Rendering stock.html with filename={filename}")
    return render_template('stock.html', form=form, dsf=dsf, stock_items=stock_items, filename=unique_filename)

#delete stock
@app.route('/delete_stock', methods=['POST'])
def delete_stock():
        user_id = session.get('user_id')
        if 'user_id' not in session:
            flash('Please log in to access the stock page.', 'danger')
            return redirect(url_for('login_page'))
        dsf = DeleteStockForm()
        try:
            if dsf.validate_on_submit():
                    # Perform stock deletion logic
                    stock_agent.delete_all_stock(user_id)
                   
                    flash('All stock items deleted successfully!', 'success')
            else:
                    flash('Invalid form submission.', 'danger')
                    logger.warning("Invalid form submission detected.")
        except Exception as e:
            logger.error(f"Error deleting stock items: {str(e)}")
            flash('An error occurred while deleting stock items. Please try again.', 'danger')
        
        # Redirect back to the stock management page
        return redirect(url_for('stock',dsf = dsf))


#chat_lock = Lock()
@app.route('/chat', methods=['GET', 'POST'])
def chat_page():
    logger.debug("Entering /chat route")
    try:
        if 'user_id' not in session:
            logger.debug("No user_id, redirecting to login")
            flash('Please login first', 'danger')
            return redirect(url_for('login_page'))
        
        logger.debug(f"Session data: {session}")
        form = ChatForm(request.form)
        chat_history = session.get('chat_history', [])
        logger.debug(f"Chat history: {len(chat_history)} messages")
        
        if request.method == 'GET':
            logger.debug("Handling GET request")
            return render_template('chat.html', form=form, messages=chat_history)
        
        logger.debug("Handling POST request")
        if not form.validate():
            logger.debug(f"Form validation failed: {form.errors}")
            if request.headers.get('HX-Request'):
                return render_template('chat_errors.html', errors=form.errors)
            flash('Invalid message format', 'danger')
            return redirect(url_for('chat_page'))
        
        user_id = session['user_id']
        query = form.query.data.strip()
        logger.debug(f"User ID: {user_id}, Query: {query}")
        
        if not query or len(query) > 500:
            logger.debug("Query length validation failed")
            flash('Message must be 1-500 characters', 'warning')
            return redirect(url_for('chat_page'))
        
        try:
            logger.debug("Appending user message")
            user_msg = {
                'text': query,
                'is_user': True,
                'timestamp': arrow.now().format('MMM D, HH:mm'),
                'status': 'delivered'
            }
            chat_history.append(user_msg)
            if len(str(chat_history)) > 4000:
                logger.warning("Chat history too large, truncating to 10 messages")
                chat_history = chat_history[-10:]
            else:
                chat_history = chat_history[-20:]
            session['chat_history'] = chat_history
            session.modified = True
            logger.debug("User message stored")
        except Exception as e:
            logger.error(f"Failed to store user message: {e}", exc_info=True)
            flash('Error saving your message', 'danger')
            return redirect(url_for('chat_page'))
        
        try:
            logger.debug(f"Processing AI response for user {user_id}")
            logger.debug("Fetching knowledge base")
            try:
                analyzer.fetch_knowledge_base(user_id)
            except Exception as e:
                logger.error(f"Failed to fetch knowledge base: {e}", exc_info=True)
                flash("Error accessing knowledge base", 'danger')
                return redirect(url_for('chat_page'))
            
            logger.debug("Retrieving context")
            try:
                context = analyzer.retrieve_context(user_id, query)
                logger.debug(f"Context: {context}")
            except Exception as e:
                logger.error(f"Failed to retrieve context: {e}", exc_info=True)
                context = []
            
            logger.debug("Generating AI response")
            try:
                ai_response = analyzer.generate_response(user_id, query, context)
                logger.debug(f"AI response: {ai_response}")
            except Exception as e:
                logger.error(f"Failed to generate AI response: {e}", exc_info=True)
                flash("Error generating AI response", 'danger')
                return redirect(url_for('chat_page'))
            
            ai_msg = {
                'text': ai_response,
                'is_user': False,
                'timestamp': arrow.now().format('MMM D, HH:mm'),
                'status': 'delivered'
            }
            chat_history.append(ai_msg)
            session['chat_history'] = chat_history[-20:]
            session.modified = True
            logger.debug("AI message stored")
            
            if request.headers.get('HX-Request'):
                logger.debug("Rendering HTMX response")
                new_messages = [user_msg, ai_msg]
                return render_template('chat_messages.html', messages=new_messages)
            
            logger.debug("Redirecting to chat page")
            return redirect(url_for('chat_page'))
            
        except Exception as e:
            logger.error(f"Error in AI processing: {e}", exc_info=True)
            chat_history[-1]['status'] = 'error'
            session['chat_history'] = chat_history[-20:]
            session.modified = True
            if request.headers.get('HX-Request'):
                return render_template('chat_errors.html', error=str(e))
            flash("An error occurred while processing your request", 'danger')
            return redirect(url_for('chat_page'))
            
    except Exception as e:
        logger.error(f"Critical error in chat_page: {e}", exc_info=True)
        flash("Server error occurred", 'danger')
        return redirect(url_for('chat_page'))

@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    logger.debug("Clearing chat history")
    try:
        form = DeleteChatForm(request.form)
        if form.validate():
            session['chat_history'] = []
            session.modified = True
            logger.debug("Chat history cleared")
            if request.headers.get('HX-Request'):
                return render_template('chat_messages.html', messages=[])
            flash("Chat history cleared", "success")
            return redirect(url_for('chat_page'))
        logger.warning("Invalid clear chat form submission")
        flash("Error clearing chat history", "danger")
        return redirect(url_for('chat_page'))
    except Exception as e:
        logger.error(f"Failed to clear chat history: {e}", exc_info=True)
        flash("Error clearing chat history", "danger")
        return redirect(url_for('chat_page'))


@app.route('/chat/history')
def chat_history():
    """Render chat history."""
    try:
        return render_template('chat_messages.html', messages=session.get('chat_history', []))
    except Exception as e:
        logger.error(f"Error in chat_history for user {session.get('user_id', 'unknown')}: {e}", exc_info=True)
        flash("Error loading chat history.", 'danger')
        return redirect(url_for('chat_page'))
    
@app.route('/chat/messages')
def chat_messages():
    return render_template('chat_messages.html',
                         messages=session.get('chat_history', []))

@app.route('/chat/update')
def chat_update():
    return '', 204, {
        'HX-Trigger': 'chatUpdate'
    }

if __name__ == '__main__':
    app.run(debug=True,port=5000)