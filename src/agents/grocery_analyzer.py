import numpy as np
import requests
from sentence_transformers import SentenceTransformer
import faiss
import yaml
import os
from dotenv import load_dotenv
from loggers.custom_logger import logger
# Load environment variables
load_dotenv()


BASE_URL = os.path.join(os.path.dirname(__file__),'..')
print(f'BASE_URL : {BASE_URL}')
CONFIG_PATH = os.path.join(BASE_URL,'constants','config.yaml')

# Load configuration
with open(CONFIG_PATH, 'r') as file:
    config = yaml.safe_load(file)
    DEEPSEEK_API_URL = config['deepseek']['api_url']
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

class SmartGroceryAnalyzer:
    def __init__(self, stock_agent, receipt_agent):
        self.stock_agent = stock_agent
        self.receipt_agent = receipt_agent
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')  # Efficient embedding model
        self.index = None
        self.knowledge_base = []
        self._init_vector_index()
        logger.info("SmartGroceryAnalyzer initialized successfully")

    def _init_vector_index(self):
        """Initialize the FAISS index with the embedding dimension."""
        dimension = self.embedder.get_sentence_embedding_dimension()
        self.index = faiss.IndexFlatL2(dimension)
        logger.info("FAISS index initialized successfully")

    def _update_vector_index(self, embeddings):
        """Update the FAISS index with new embeddings."""
        if self.index is None:
            self._init_vector_index()
        self.index.add(np.array(embeddings).astype('float32'))
        logger.info("FAISS index updated successfully")

    def fetch_knowledge_base(self):
        """Fetch and combine data from stock and receipt agents."""
        stock_items = self.stock_agent.fetch_all_items()
        receipt_items = self.receipt_agent.fetch_all_items()
        logger.info("Fetched stock and receipt items successfully")
        
        # Format knowledge base entries
        self.knowledge_base = [
            f"Fridge item: {item['name']}, quantity: {item['quantity']}, weight: {item['weight']}, "
            f"category: {item['category']}, shelf_life: {item['shelf_life']} days"
            for item in stock_items
        ] + [
            f"Grocery item: {item['name']}, quantity: {item['quantity']}, weight: {item['weight']}, "
            f"category: {item['category']}, purchase_date: {item['purchase_date']}, "
            f"expiration_date: {item['expiration_date']}"
            for item in receipt_items
        ]

        # Generate embeddings and update index
        if self.knowledge_base:
            embeddings = self.embedder.encode(self.knowledge_base, convert_to_tensor=False)
            self._update_vector_index(embeddings)
        
        return self.knowledge_base

    def retrieve_context(self, query, max_docs=10):
        """Retrieve relevant context from the knowledge base using vector search."""
        if not self.knowledge_base or self.index is None:
            return []

        # Encode query and search index
        query_embedding = self.embedder.encode([query], convert_to_tensor=False)
        distances, indices = self.index.search(np.array(query_embedding).astype('float32'), max_docs)
        
        # Return relevant context documents
        return [self.knowledge_base[i] for i in indices[0] if i >= 0 and i < len(self.knowledge_base)]

    def generate_response(self, query, context):
        """Generate a response using the DeepSeek API."""
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        prompt =f"""
            "You are a smart grocery assistant helping reduce food waste and manage groceries. "
            "Use this context to answer the question:"
            f"Context: {(context)}"
            f"Question: {query}"
            "Consider these factors in your response:"
            "1. Expiration dates and remaining shelf life"
            "2. Current stock levels and recent purchases"
            "3. Food categories and typical usage patterns"
            "4. Seasonal availability and storage constraints"
            "Provide practical, specific advice in a friendly tone."
        """
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a helpful grocery assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }
        
        try:
            response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            response  = response.json()["choices"][0]["message"]["content"]
            logger.info("Response generated successfully")
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Error generating response: {str(e)}")
            return f"Sorry, I encountered an error: {str(e)}"
        

    def query(self, question):
        """Process a user query and return a response."""
        self.fetch_knowledge_base()  # Refresh data and embeddings
        if not self.knowledge_base:
            return "I don't have any grocery data yet. Please add items to your fridge or receipts!"
            
        context = self.retrieve_context(question)
        if not context:
            return "I couldn't find relevant information. Could you provide more details?"
            
        return self.generate_response(question, context)

    def run_chatbot(self):
        """Run an interactive chatbot session."""
        print("🍎 Smart Grocery Assistant: Ready to help manage your groceries and reduce waste!")
        print("Ask me about expiration dates, meal suggestions, or shopping list recommendations.")
        print("Type 'exit' to end the session.\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                if user_input.lower() in ['exit', 'quit']:
                    print("Assistant: Happy cooking! 🧑‍🍳")
                    break
                if not user_input:
                    print("Assistant: Please ask me something!")
                    continue
                
                response = self.query(user_input)
                print(f"Question: {user_input}")
                print(f"Assistant: {response}\n")
            except KeyboardInterrupt:
                print("\nAssistant: Session ended. Have a great day!")
                break
            except Exception as e:
                print(f"Assistant: Oops, something went wrong: {str(e)}")
                continue

