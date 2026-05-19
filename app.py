from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from pymongo import MongoClient
import requests
import json
from bson import ObjectId
from datetime import datetime

app = Flask(__name__)

# MongoDB URI from previous app.py
MONGO_URI = "mongodb+srv://admin123:admin123@cluster0.slklrau.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)

# Nvidia API Configuration
INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
API_KEY = "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"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "text/event-stream"
}

# Custom JSON encoder to handle ObjectId and datetime
class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return json.JSONEncoder.default(self, o)

def get_database_context():
    context = []
    try:
        databases = client.list_database_names()
        # Filter out system databases to avoid huge context
        databases = [db for db in databases if db not in ['admin', 'local', 'config']]
        
        for db_name in databases:
            db = client[db_name]
            collections = db.list_collection_names()
            db_info = {"database": db_name, "collections": {}}
            
            for coll_name in collections:
                collection = db[coll_name]
                # Limit to 50 documents per collection to avoid prompt length limit
                docs = list(collection.find().limit(50))
                db_info["collections"][coll_name] = docs
            
            context.append(db_info)
    except Exception as e:
        print(f"Error fetching DB context: {e}")
        
    return json.dumps(context, cls=JSONEncoder)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    chat_history = data.get("history", [])

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    db_context = get_database_context()
    
    system_instruction = (
        "You are a helpful AI Database Assistant. "
        "Your task is to answer user questions based ONLY on the provided MongoDB database context. "
        "Here is the database content in JSON format:\n\n"
        f"{db_context}\n\n"
        "If the user asks about something not in the database, politely inform them that you can only answer questions related to the database."
    )

    raw_history = chat_history + [{"role": "user", "content": user_message}]
    messages = []
    
    for msg in raw_history:
        role = msg["role"]
        content = msg["content"]
        
        if not messages:
            if role != "user":
                continue # Skip if the first message in history is not user
            messages.append({"role": "user", "content": system_instruction + "\n\n" + content})
        else:
            if messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + content
            else:
                messages.append({"role": role, "content": content})

    payload = {
        "model": "google/gemma-3n-e4b-it", # A standard NVIDIA model, you can change if needed
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.5,
        "top_p": 0.9,
        "stream": True,
    }

    def generate():
        response = requests.post(INVOKE_URL, headers=headers, json=payload, stream=True)
        if response.status_code != 200:
            print(f"Error from Nvidia API: {response.status_code}")
            print(response.text)
            yield f"data: {json.dumps({'choices': [{'delta': {'content': 'Error: Failed to reach Nvidia API. ' + response.text}}]})}\n\n"
            return
            
        for line in response.iter_lines():
            if line:
                yield line.decode("utf-8") + "\n\n"

    return Response(stream_with_context(generate()), content_type="text/event-stream")

if __name__ == "__main__":
    app.run(debug=True, port=5000)