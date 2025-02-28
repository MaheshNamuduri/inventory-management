import psycopg2
from psycopg2 import Error

try:
    conn = psycopg2.connect(dbname="postgres", user="postgres", password="mahesh.123", host="localhost", port="5432")
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("DROP DATABASE IF EXISTS inventory_db")
    cursor.execute("CREATE DATABASE inventory_db")
    print("Database created successfully")
    conn.close()

    conn = psycopg2.connect(dbname="inventory_db", user="postgres", password="mahesh.123", host="localhost", port="5432")
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL
        )
    """)
    cursor.execute("INSERT INTO users (username, password, role) VALUES ('admin', 'admin123', 'admin'), ('staff1', 'staff123', 'staff')")

    # Categories table
    cursor.execute("""
        CREATE TABLE categories (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL
        )
    """)
    cursor.execute("INSERT INTO categories (name) VALUES ('Electronics'), ('Furniture'), ('Stationery')")

    # Items table
    cursor.execute("""
        CREATE TABLE items (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            initial_stock INTEGER NOT NULL,
            remaining_stock INTEGER NOT NULL,
            price DECIMAL(10, 2),
            category VARCHAR(50)
        )
    """)
    cursor.execute("""
        INSERT INTO items (name, initial_stock, remaining_stock, price, category) VALUES
        ('Laptop', 10, 8, 50000.00, 'Electronics'),
        ('Chair', 20, 15, 1500.00, 'Furniture'),
        ('Pen', 5, 3, 10.00, 'Stationery')
    """)

    # History table
    cursor.execute("""
        CREATE TABLE stock_history (
            id SERIAL PRIMARY KEY,
            item_id INTEGER REFERENCES items(id),
            action VARCHAR(20),
            quantity INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT INTO stock_history (item_id, action, quantity, timestamp) VALUES
        (1, 'sell', 1, CURRENT_TIMESTAMP - INTERVAL '1 day'),
        (1, 'sell', 2, CURRENT_TIMESTAMP - INTERVAL '2 days'),
        (2, 'sell', 3, CURRENT_TIMESTAMP - INTERVAL '3 days'),
        (3, 'sell', 1, CURRENT_TIMESTAMP - INTERVAL '4 days')
    """)

    conn.commit()
    print("Table and sample data created successfully")
except Error as e:
    print(f"Error: {e}")
finally:
    if conn:
        cursor.close()
        conn.close()