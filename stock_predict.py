import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

def predict_stock_needs():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:mahesh.123@localhost:5433/inventory_db")
    try:
        conn = psycopg2.connect(db_url)
    except psycopg2.Error as e:
        print(f"Failed to connect in predict_stock_needs: {e}")
        return {}, {}
    
    try:
        # Fetch sales history and current stock
        query = """
        SELECT sh.item_id, sh.quantity, sh.timestamp, i.name, i.remaining_stock, i.category
        FROM stock_history sh
        JOIN items i ON sh.item_id = i.id
        WHERE sh.action = 'sell'
        """
        df = pd.read_sql(query, conn)
        
        # Fetch all items for items with no sales
        items_query = "SELECT id, name, remaining_stock, category FROM items"
        items_df = pd.read_sql(items_query, conn)
    except Exception as e:
        print(f"Error fetching data in predict_stock_needs: {e}")
        conn.close()
        return {}, {}
    
    conn.close()

    predictions = {}
    trends = {}
    
    if not df.empty:
        # Calculate category averages for fallback
        category_trends = df.groupby('category')['quantity'].sum() / df.groupby('category')['timestamp'].apply(lambda x: (x.max() - x.min()).days or 1)
        
        for item_id in items_df['id'].unique():
            item_data = df[df['item_id'] == item_id]
            current_stock = items_df[items_df['id'] == item_id]['remaining_stock'].iloc[0]
            category = items_df[items_df['id'] == item_id]['category'].iloc[0]
            
            # Default trend from category if no sales
            trend = category_trends.get(category, 1.0)  # Default to 1 unit/day if category data missing
            
            if not item_data.empty:
                days = max((item_data['timestamp'].max() - item_data['timestamp'].min()).days, 1)
                total_sold = item_data['quantity'].sum()
                trend = total_sold / days
                
                if len(item_data) >= 2:
                    X = pd.DataFrame({
                        'days_since_first': pd.to_numeric((item_data['timestamp'] - item_data['timestamp'].min()) / pd.Timedelta(days=1)),
                        'category_encoded': pd.factorize(item_data['category'])[0]  # Simple encoding
                    })
                    y = item_data['quantity']
                    model = HistGradientBoostingRegressor()
                    model.fit(X, y)
                    future_X = pd.DataFrame({'days_since_first': [7], 'category_encoded': [pd.factorize([category])[0][0]]})
                    predicted = model.predict(future_X)[0]
                    restock = max(5, int(predicted * 1.2 + trend * 7 - current_stock))  # Adjust for current stock
                else:
                    restock = max(5, int(total_sold * 3 - current_stock))
            else:
                # No sales: suggest based on trend and current stock
                restock = max(5, int(trend * 7 - current_stock))
            
            if restock > 0:  # Only suggest restocking if needed
                predictions[item_id] = restock
                trends[item_id] = round(trend, 2)
    
    return predictions, trends