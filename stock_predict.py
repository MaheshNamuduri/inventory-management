import pandas as pd
from sklearn.linear_model import LinearRegression
import psycopg2

def predict_stock_needs():
    conn = psycopg2.connect(dbname="inventory_db", user="postgres", password="mahesh.123", host="localhost", port="5432")
    df = pd.read_sql("SELECT item_id, quantity, timestamp FROM stock_history WHERE action = 'sell'", conn)
    conn.close()

    predictions = {}
    trends = {}
    if not df.empty:
        for item_id in df['item_id'].unique():
            item_data = df[df['item_id'] == item_id]
            days = max((item_data['timestamp'].max() - item_data['timestamp'].min()).days, 1)  # Avoid division by 0
            total_sold = item_data['quantity'].sum()
            trends[item_id] = round(total_sold / days, 2)  # Daily sales rate
            if len(item_data) > 1:
                X = pd.to_numeric((item_data['timestamp'] - item_data['timestamp'].min()) / pd.Timedelta(days=1)).values.reshape(-1, 1)
                y = item_data['quantity'].values
                model = LinearRegression()
                model.fit(X, y)
                predicted = model.predict([[7]])
                predictions[item_id] = max(5, int(predicted[0] * 1.5 + trends[item_id] * 7))  # Blend prediction and trend
            else:
                predictions[item_id] = max(5, int(total_sold * 3))
    return predictions, trends