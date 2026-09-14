from flask import Flask, request, jsonify
import os
import json
import uuid
from datetime import datetime
import requests

app = Flask(__name__)

# Enable CORS for all routes
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

# In-memory storage for comments and ratings
food_data = {}

# Load existing data if available
def load_data():
    global food_data
    if os.path.exists('food_data.json'):
        try:
            with open('food_data.json', 'r') as f:
                food_data = json.load(f)
        except:
            food_data = {}

# Save data to file
def save_data():
    with open('food_data.json', 'w') as f:
        json.dump(food_data, f, indent=2)

# Initialize data structure for all food items
def init_food_items():
    food_items = [
        # Breakfast
        "Buttermilk Pancakes",
        "Smoothie Bowl", 
        "Full English Breakfast",
        # Lunch
        "Creamy Baked Mac and Cheese",
        "Vegetarian Bean and Rice Burrito",
        "Air Fryer Grilled Cheese",
        # Dinner
        "Delicious Pizza",
        "Bacon Cheese Burgers and Chili Cheese Fries",
        "Hot Dogs on Colored Plates"
    ]
    
    for item in food_items:
        if item not in food_data:
            food_data[item] = {
                "comments": [],
                "ratings": [],
                "community_note": "No reviews yet. Be the first to rate and comment!"
            }
    save_data()

# Get Groq API key from Replit secrets
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')

def generate_summary_with_groq(food_name):
    """Use Groq API to generate a community note summary"""
    if not GROQ_API_KEY:
        return f"Community feedback for {food_name}: No AI summary available (missing API key)"
    
    comments = food_data.get(food_name, {}).get("comments", [])
    ratings = food_data.get(food_name, {}).get("ratings", [])
    
    if not comments and not ratings:
        return f"No reviews yet for {food_name}. Be the first to rate and comment!"
    
    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    
    # Prepare prompt for Groq
    prompt = f"""Summarize the community feedback for this food item. Include the average rating and key themes from comments.
    
Food: {food_name}
Average Rating: {avg_rating:.1f}/5

Comments:
{chr(10).join([f'- {c[\"text\"]}' for c in comments[-10:]])}

Provide a concise summary (1-2 sentences) that captures the overall sentiment and key points."""
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 200
            },
            timeout=30
        )
        result = response.json()
        summary = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        return summary if summary else f"Community rating: {avg_rating:.1f}/5 - {len(comments)} reviews"
    except Exception as e:
        print(f"Groq API error: {e}")
        avg = sum(ratings) / len(ratings) if ratings else 0
        return f"Community rating: {avg:.1f}/5 from {len(ratings)} ratings"

@app.route('/api/foods', methods=['GET'])
def get_foods():
    """Get all food items with their data"""
    return jsonify(food_data)

@app.route('/api/food/<food_name>', methods=['GET'])
def get_food_data(food_name):
    """Get data for a specific food item"""
    # Decode URL-encoded food name
    food_name = food_name.replace('%20', ' ')
    
    if food_name not in food_data:
        init_food_items()
    
    data = food_data.get(food_name, {
        "comments": [],
        "ratings": [],
        "community_note": "No reviews yet. Be the first to rate and comment!"
    })
    
    # Regenerate community note
    if data.get("comments") or data.get("ratings"):
        data["community_note"] = generate_summary_with_groq(food_name)
        food_data[food_name] = data
        save_data()
    
    return jsonify(data)

@app.route('/api/food/<food_name>/rate', methods=['POST'])
def rate_food(food_name):
    """Submit a rating for a food item"""
    food_name = food_name.replace('%20', ' ')
    
    if food_name not in food_data:
        init_food_items()
    
    data = request.json
    rating = data.get('rating')
    user_id = data.get('user_id', str(uuid.uuid4()))
    
    if rating is None or rating < 1 or rating > 5:
        return jsonify({"error": "Rating must be between 1 and 5"}), 400
    
    # Add rating
    food_data[food_name]["ratings"].append(rating)
    
    # Regenerate community note
    food_data[food_name]["community_note"] = generate_summary_with_groq(food_name)
    
    save_data()
    
    return jsonify({
        "message": "Rating submitted",
        "rating": rating,
        "avg_rating": sum(food_data[food_name]["ratings"]) / len(food_data[food_name]["ratings"]),
        "community_note": food_data[food_name]["community_note"]
    })

@app.route('/api/food/<food_name>/comment', methods=['POST'])
def comment_food(food_name):
    """Submit a comment for a food item"""
    food_name = food_name.replace('%20', ' ')
    
    if food_name not in food_data:
        init_food_items()
    
    data = request.json
    text = data.get('text', '').strip()
    user_id = data.get('user_id', str(uuid.uuid4()))
    user_name = data.get('user_name', 'Anonymous')
    
    if not text:
        return jsonify({"error": "Comment cannot be empty"}), 400
    
    # Add comment
    comment = {
        "id": str(uuid.uuid4()),
        "text": text,
        "user_id": user_id,
        "user_name": user_name,
        "timestamp": datetime.now().isoformat()
    }
    food_data[food_name]["comments"].append(comment)
    
    # Regenerate community note
    food_data[food_name]["community_note"] = generate_summary_with_groq(food_name)
    
    save_data()
    
    return jsonify({
        "message": "Comment submitted",
        "comment": comment,
        "community_note": food_data[food_name]["community_note"]
    })

@app.route('/api/food/<food_name>/refresh', methods=['POST'])
def refresh_summary(food_name):
    """Refresh the community note summary"""
    food_name = food_name.replace('%20', ' ')
    
    if food_name not in food_data:
        init_food_items()
    
    food_data[food_name]["community_note"] = generate_summary_with_groq(food_name)
    save_data()
    
    return jsonify({
        "community_note": food_data[food_name]["community_note"]
    })

# Initialize data on startup
load_data()
init_food_items()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
