from flask import Flask, render_template, request, redirect, url_for, send_file, Response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import psycopg2
from psycopg2 import Error
import csv
import io
import smtplib
from email.mime.text import MIMEText
from stock_predict import predict_stock_needs
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Change this in production

# Flask-Login setup
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
    conn = get_db_connection()
    if not conn:
        print("Failed to load user: Database connection error")
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        return User(user[0], user[1], user[2]) if user else None
    except Error as e:
        print(f"Error loading user: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

def get_db_connection():
    try:
        return psycopg2.connect(os.getenv("DATABASE_URL"))
    except Error as e:
        print(f"Database connection failed: {e}")
        return None

def send_low_stock_email(low_items):
    sender = 'your_actual_email@gmail.com'  # Replace with your email
    receiver = 'your_actual_email@gmail.com'  # Replace with your email
    password = 'your_app_password'    # Replace with your Gmail App Password
    msg = MIMEText(f"Low stock items detected:\n{', '.join([f'{item[1]} ({item[3]} units)' for item in low_items])}")
    msg['Subject'] = 'Low Stock Alert - Inventory Manager'
    msg['From'] = sender
    msg['To'] = receiver
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
            print("Low stock email sent")
    except Exception as e:
        print(f"Failed to send email: {e}")

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
            return "Invalid credentials"
        except Error as e:
            print(f"Login error: {e}")
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

        # Search and filter logic
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

        # Low stock notification
        low_stock_items = [item for item in items if item[3] < 5]
        if low_stock_items:
            send_low_stock_email(low_stock_items)

        # Chart data
        cursor.execute("SELECT name, remaining_stock FROM items")
        stock_data = cursor.fetchall() or [('No Data', 0)]
        cursor.execute("SELECT i.name, SUM(sh.quantity) as sold FROM items i JOIN stock_history sh ON i.id = sh.item_id WHERE sh.action = 'sell' GROUP BY i.name ORDER BY sold DESC LIMIT 5")
        top_sold = cursor.fetchall() or [('No Sales', 0)]

        cursor.execute("SELECT name FROM categories")
        categories = [row[0] for row in cursor.fetchall()]

        return render_template('index.html', items=items, stock_data=stock_data, top_sold=top_sold, role=current_user.role, categories=categories)
    except Error as e:
        print(f"Index route database error: {e}")
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
        print(f"Add item error: {e}")
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
        print(f"Edit item error: {e}")
        return "Database error", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/sell/<int:id>')
@login_required
def sell_item(id):
    conn = get_db_connection()
    if conn:
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
            print(f"Sell item error: {e}")
            return "Database error", 500
        finally:
            cursor.close()
            conn.close()
    return "Database connection failed", 500

@app.route('/suggestions')
@login_required
def suggestions():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, remaining_stock FROM items WHERE remaining_stock < 10")
            low_items = cursor.fetchall()
            predictions, trends = predict_stock_needs()
            print(f"Low items: {low_items}")
            print(f"AI predictions: {predictions}, Trends: {trends}")
            suggestions = [(item[1], predictions.get(item[0], max(20 - item[2], 0)), trends.get(item[0], 0)) for item in low_items]
            return render_template('suggestions.html', suggestions=suggestions)
        except Error as e:
            print(f"Suggestions error: {e}")
            return "Database error", 500
        finally:
            cursor.close()
            conn.close()
    return "Database connection failed", 500

@app.route('/export')
@login_required
def export():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, initial_stock, remaining_stock, price, category FROM items")
            items = cursor.fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['ID', 'Name', 'Initial Stock', 'Remaining Stock', 'Price', 'Category'])
            writer.writerows(items)
            return Response(output.getvalue(), mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=inventory.csv"})
        except Error as e:
            print(f"Export error: {e}")
            return "Database error", 500
        finally:
            cursor.close()
            conn.close()
    return "Database connection failed", 500

@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.csv'):
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                    csv_reader = csv.reader(stream)
                    next(csv_reader)
                    for row in csv_reader:
                        cursor.execute("INSERT INTO items (id, name, initial_stock, remaining_stock, price, category) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                                       (int(row[0]), row[1], int(row[2]), int(row[3]), float(row[4]), row[5]))
                    conn.commit()
                    return redirect(url_for('index'))
                except Error as e:
                    print(f"Import error: {e}")
                    return "Database error", 500
                finally:
                    cursor.close()
                    conn.close()
            return "Database connection failed", 500
    return render_template('import.html')

@app.route('/change_credentials', methods=['GET', 'POST'])
@login_required
def change_credentials():
    if request.method == 'POST':
        new_username = request.form['new_username']
        new_password = request.form['new_password']
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET username = %s, password = %s WHERE id = %s",
                               (new_username, new_password, current_user.id))
                conn.commit()
                logout_user()
                return redirect(url_for('login'))
            except Error as e:
                print(f"Change credentials error: {e}")
                return "Database error", 500
            finally:
                cursor.close()
                conn.close()
        return "Database connection failed", 500
    return render_template('change_credentials.html')

@app.route('/categories', methods=['GET', 'POST'])
@login_required
def manage_categories():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    conn = get_db_connection()
    if not conn:
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        if request.method == 'POST':
            if 'add' in request.form:
                name = request.form['name']
                cursor.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
            elif 'delete' in request.form:
                name = request.form['delete']
                cursor.execute("DELETE FROM categories WHERE name = %s", (name,))
            conn.commit()
        cursor.execute("SELECT name FROM categories")
        categories = [row[0] for row in cursor.fetchall()]
        return render_template('categories.html', categories=categories)
    except Error as e:
        print(f"Categories error: {e}")
        return "Database error", 500
    finally:
        cursor.close()
        conn.close()

@app.route('/init_db')
def init_db():
    conn = get_db_connection()
    if not conn:
        print("Database connection failed in init_db - DATABASE_URL: " + os.getenv("DATABASE_URL", "Not set"))
        return "Database connection failed", 500
    try:
        cursor = conn.cursor()
        print("Starting database initialization")
        if not os.path.exists('inventory_db.sql'):
            print("File error: inventory_db.sql not found")
            return "File error: inventory_db.sql not found", 500
        with open('inventory_db.sql', 'rb') as f:  # Read as binary
            sql_content = f.read().decode('utf-8-sig')  # Decode with BOM handling
            print(f"Executing SQL: {sql_content[:100]}...")
            cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            cursor.execute(sql_content)
        conn.commit()
        print("Database initialized successfully")
        return "Database initialized successfully", 200
    except Error as e:
        print(f"Init DB error: {e}")
        return f"Error initializing database: {e}", 500
    except UnicodeDecodeError as e:
        print(f"Unicode decode error: {e}")
        return f"Unicode decode error: {e}", 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)