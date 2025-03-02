from flask import Flask, render_template, request, redirect, url_for, Response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import psycopg2
from psycopg2 import Error
import io
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import logging
import csv

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),  # Log to file
        logging.StreamHandler()          # Log to console
    ]
)
logger = logging.getLogger(__name__)

# Placeholder for stock_predict
try:
    from stock_predict import predict_stock_needs
except ImportError:
    def predict_stock_needs():
        return {}, {}

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    logger.debug(f"Loading user with ID: {user_id}")
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to load user: Database connection error")
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        return User(user[0], user[1], user[2]) if user else None
    except Error as e:
        logger.error(f"Error loading user: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

def get_db_connection():
    try:
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:mahesh.123@localhost:5433/inventory_db")
        logger.debug(f"Attempting to connect with URL: {db_url}")
        conn = psycopg2.connect(db_url)
        logger.debug("Connection successful")
        return conn
    except Error as e:
        logger.error(f"Database connection failed: {e}")
        return None

def send_low_stock_email(low_items):
    sender = os.getenv("EMAIL_SENDER", "your_actual_email@gmail.com")
    receiver = sender
    password = os.getenv("EMAIL_PASSWORD", "your_app_password")
    
    if not sender or not password:
        logger.error("Email credentials missing in environment variables")
        return
    
    msg = MIMEText(f"Low stock items detected:\n{', '.join([f'{item[1]} ({item[3]} units)' for item in low_items])}")
    msg['Subject'] = 'Low Stock Alert - Inventory Manager'
    msg['From'] = sender
    msg['To'] = receiver
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
            logger.info("Low stock email sent")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        if not conn:
            return "Database connection failed", 500
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, role FROM users WHERE username = %s AND password = %s", (username, password))
            user = cursor.fetchone()
            if user:
                login_user(User(user[0], user[1], user[2]))
                return redirect(url_for('index'))
            return "Invalid credentials", 401
        except Error as e:
            logger.error(f"Login error: {e}")
            return "Database error during login", 500
        finally:
            cursor.close()
            conn.close()
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    conn = get_db_connection()
    if not conn:
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()

        search = request.form.get('search', '')
        category_filter = request.form.get('category', '')
        low_stock = request.form.get('low_stock')

        query = "SELECT id, name, initial_stock, remaining_stock, price, category FROM items WHERE 1=1"
        params = []
        if search:
            query += " AND name ILIKE %s"
            params.append(f"%{search}%")
        if category_filter:
            query += " AND category = %s"
            params.append(category_filter)
        if low_stock:
            query += " AND remaining_stock < 5"

        cursor.execute(query, params)
        items = cursor.fetchall()

        low_stock_items = [item for item in items if item[3] < 5]
        if low_stock_items:
            send_low_stock_email(low_stock_items)

        cursor.execute("SELECT name, remaining_stock FROM items")
        stock_data = cursor.fetchall() or [('No Data', 0)]
        cursor.execute("SELECT i.name, SUM(sh.quantity) AS sold FROM items i JOIN stock_history sh ON i.id = sh.item_id WHERE sh.action = 'sell' GROUP BY i.name ORDER BY sold DESC LIMIT 5")
        top_sold = cursor.fetchall() or [('No Sales', 0)]

        cursor.execute("SELECT name FROM categories")
        categories = [row[0] for row in cursor.fetchall()]

        return render_template('index.html', items=items, stock_data=stock_data, top_sold=top_sold, role=current_user.role, categories=categories)
    except Error as e:
        logger.error(f"Index route database error: {e}")
        return "Database error after login", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_item():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    conn = get_db_connection()
    if not conn:
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories")
        categories = [row[0] for row in cursor.fetchall()]
        if request.method == 'POST':
            name = request.form['name']
            initial_stock = int(request.form['initial_stock'])
            remaining_stock = initial_stock
            price = float(request.form['price'])
            category = request.form['category']
            cursor.execute("INSERT INTO items (name, initial_stock, remaining_stock, price, category) VALUES (%s, %s, %s, %s, %s) RETURNING id", 
                           (name, initial_stock, remaining_stock, price, category))
            conn.commit()
            return redirect(url_for('index'))
        return render_template('add.html', categories=categories)
    except Error as e:
        logger.error(f"Add item error: {e}")
        return "Database error", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_item(id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
    conn = get_db_connection()
    if not conn:
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories")
        categories = [row[0] for row in cursor.fetchall()]
        if request.method == 'POST':
            if 'delete' in request.form:
                cursor.execute("DELETE FROM items WHERE id = %s", (id,))
                conn.commit()
                return redirect(url_for('index'))
            cursor.execute("SELECT initial_stock, remaining_stock FROM items WHERE id = %s", (id,))
            current = cursor.fetchone()
            current_initial = current[0]
            current_remaining = current[1]
            name = request.form['name']
            new_initial = int(request.form['initial_stock'])
            new_remaining = request.form.get('remaining_stock')
            price = float(request.form['price'])
            category = request.form['category']
            if new_remaining is not None:
                remaining_stock = int(new_remaining)
            else:
                diff = new_initial - current_initial
                remaining_stock = max(0, current_remaining + diff)
            cursor.execute("UPDATE items SET name = %s, initial_stock = %s, remaining_stock = %s, price = %s, category = %s WHERE id = %s",
                           (name, new_initial, remaining_stock, price, category, id))
            conn.commit()
            return redirect(url_for('index'))
        cursor.execute("SELECT * FROM items WHERE id = %s", (id,))
        item = cursor.fetchone()
        return render_template('edit.html', item=item, categories=categories)
    except Error as e:
        logger.error(f"Edit item error: {e}")
        return "Database error", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/sell/<int:id>')
@login_required
def sell_item(id):
    conn = get_db_connection()
    if not conn:
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT remaining_stock FROM items WHERE id = %s", (id,))
        current_stock = cursor.fetchone()
        if current_stock and current_stock[0] > 0:
            cursor.execute("UPDATE items SET remaining_stock = remaining_stock - 1 WHERE id = %s", (id,))
            cursor.execute("INSERT INTO stock_history (item_id, action, quantity) VALUES (%s, 'sell', 1)", (id,))
            conn.commit()
        return redirect(url_for('index'))
    except Error as e:
        logger.error(f"Sell item error: {e}")
        return "Database error", 500
    finally:
        cursor.close()
        conn.close()
@app.route('/suggestions')
@login_required
def suggestions():
    logger.debug("Starting /suggestions route")
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database in /suggestions")
        return "Database connection failed", 500
    
    cursor = None
    try:
        logger.debug("Creating database cursor")
        cursor = conn.cursor()
        logger.debug("Executing query: SELECT id, name, remaining_stock FROM items WHERE remaining_stock < 10")
        cursor.execute("SELECT id, name, remaining_stock FROM items WHERE remaining_stock < 10")
        low_items = cursor.fetchall()
        logger.debug(f"Low items fetched: {low_items}")
        
        logger.debug("Calling predict_stock_needs")
        predictions, trends = predict_stock_needs()
        logger.debug(f"Predictions: {predictions}, Trends: {trends}")
        
        suggestions = [(item[1], predictions.get(item[0], max(20 - item[2], 0)), trends.get(item[0], 0)) for item in low_items]
        logger.debug(f"Suggestions generated: {suggestions}")
        
        logger.debug("Rendering suggestions.html")
        return render_template('suggestions.html', suggestions=suggestions)
    except Error as e:
        logger.error(f"Database error in /suggestions: {e}")
        return "Database error", 500
    except Exception as e:
        logger.error(f"Unexpected error in /suggestions: {type(e).__name__}: {str(e)}")
        # Fallback to basic suggestions without predictions
        suggestions = [(item[1], max(20 - item[2], 0), 0) for item in low_items] if 'low_items' in locals() else []
        return render_template('suggestions.html', suggestions=suggestions)
    finally:
        if 'cursor' in locals() and cursor is not None:
            cursor.close()
            logger.debug("Cursor closed")
        if conn is not None:
            conn.close()
            logger.debug("Connection closed")
        else:
            logger.debug("No connection to close")

@app.route('/export')
@login_required
def export():
    conn = get_db_connection()
    if not conn:
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, initial_stock, remaining_stock, price, category FROM items")
        items = cursor.fetchall()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []

        styles = getSampleStyleSheet()
        title = Paragraph("Inventory Report", styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 12))

        data = [['ID', 'Name', 'Initial Stock', 'Remaining Stock', 'Price (₹)', 'Category']]
        for item in items:
            data.append([str(item[0]), item[1], str(item[2]), str(item[3]), f"{item[4]:.2f}", item[5]])

        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)

        doc.build(elements)
        buffer.seek(0)

        return Response(
            buffer.getvalue(),
            mimetype='application/pdf',
            headers={"Content-Disposition": "attachment;filename=inventory_report.pdf"}
        )
    except Error as e:
        logger.error(f"Export error: {e}")
        return "Database error", 500
    finally:
        cursor.close()
        conn.close()
@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.csv'):
            conn = get_db_connection()
            if not conn:
                return "Database connection failed", 500
            try:
                cursor = conn.cursor()
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_reader = csv.reader(stream)
                header = next(csv_reader)  # Skip header row
                logger.debug(f"CSV header: {header}")
                for row in csv_reader:
                    if len(row) != 6:  # Ensure row has all columns
                        logger.warning(f"Skipping invalid row: {row}")
                        continue
                    cursor.execute("INSERT INTO items (id, name, initial_stock, remaining_stock, price, category) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                                   (int(row[0]), row[1], int(row[2]), int(row[3]), float(row[4]), row[5]))
                conn.commit()
                return redirect(url_for('index'))
            except Error as e:
                logger.error(f"Import error: {e}")
                return "Database error", 500
            except ValueError as e:
                logger.error(f"CSV parsing error: {e}")
                return "Invalid CSV format", 400
            finally:
                cursor.close()
                conn.close()
        return "Invalid file format", 400
    return render_template('import.html')

@app.route('/change_credentials', methods=['GET', 'POST'])
@login_required
def change_credentials():
    if request.method == 'POST':
        new_username = request.form['new_username']
        new_password = request.form['new_password']
        conn = get_db_connection()
        if not conn:
            return "Database connection failed", 500
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET username = %s, password = %s WHERE id = %s",
                           (new_username, new_password, current_user.id))
            conn.commit()
            logout_user()
            return redirect(url_for('login'))
        except Error as e:
            logger.error(f"Change credentials error: {e}")
            return "Database error", 500
        finally:
            cursor.close()
            conn.close()
    return render_template('change_credentials.html')


@app.route('/categories', methods=['GET', 'POST'])
@login_required
def manage_categories():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    logger.debug("Starting /categories route")
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database in /categories")
        return "Database connection failed", 500
    
    cursor = None
    error = None
    try:
        cursor = conn.cursor()
        if request.method == 'POST':
            if 'add' in request.form:
                name = request.form['name']
                logger.debug(f"Adding category: {name}")
                cursor.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
                conn.commit()
            elif 'delete' in request.form:
                name = request.form['delete']
                logger.debug(f"Checking if category {name} is in use")
                cursor.execute("SELECT COUNT(*) FROM items WHERE category = %s", (name,))
                count = cursor.fetchone()[0]
                if count > 0:
                    error = f"Cannot delete '{name}': it is used by {count} item(s)."
                    logger.warning(error)
                else:
                    logger.debug(f"Deleting category: {name}")
                    cursor.execute("DELETE FROM categories WHERE name = %s", (name,))
                    conn.commit()
        
        cursor.execute("SELECT name FROM categories")
        categories = [row[0] for row in cursor.fetchall()]
        logger.debug(f"Categories fetched: {categories}")
        return render_template('categories.html', categories=categories, error=error)
    except Error as e:
        logger.error(f"Categories error: {e}")
        return "Database error", 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
        logger.debug("Database connection closed")

@app.route('/init_db')
def init_db():
    conn = get_db_connection()
    if not conn:
        logger.error("Database connection failed in init_db - DATABASE_URL: " + os.getenv("DATABASE_URL", "Not set"))
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        logger.info("Starting database initialization")
        if not os.path.exists('inventory_db.sql'):
            logger.error("File error: inventory_db.sql not found")
            return "File error: inventory_db.sql not found", 500
        with open('inventory_db.sql', 'rb') as f:
            sql_content = f.read().decode('utf-8-sig')
            logger.info(f"Executing SQL: {sql_content[:100]}...")
            cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            cursor.execute(sql_content)
        conn.commit()
        logger.info("Database initialized successfully")
        return "Database initialized successfully", 200
    except Error as e:
        logger.error(f"Init DB error: {e}")
        return f"Error initializing database: {e}", 500
    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error: {e}")
        return f"Unicode decode error: {e}", 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    