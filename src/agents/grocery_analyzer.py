import numpy as np
import requests
from sentence_transformers import SentenceTransformer
import faiss

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = "sk-5d891e91ae9a4450bcc4c5fb18274a9c"
class SmartGroceryAnalyzer:
    def __init__(self, stock_agent, receipt_agent):
        self.stock_agent = stock_agent
        self.receipt_agent = receipt_agent
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')  # Efficient embedding model
        self.index = None
        self.knowledge_base = []
        self._init_vector_index()

    def _init_vector_index(self):
        self.index = faiss.IndexFlatL2(self.embedder.get_sentence_embedding_dimension())

    def _update_vector_index(self, embeddings):
        if self.index is None:
            self._init_vector_index()
        self.index.add(np.array(embeddings).astype('float32'))

    def fetch_knowledge_base(self):
        stock_items = self.stock_agent.fetch_all_items()
        receipt_items = self.receipt_agent.fetch_all_items()
        
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

    def retrieve_context(self, query, max_docs=3):
        if not self.knowledge_base or self.index is None:
            return []

        # Encode query and search index
        query_embedding = self.embedder.encode([query], convert_to_tensor=False)
        distances, indices = self.index.search(np.array(query_embedding).astype('float32'), max_docs)
        
        # Return relevant context documents
        return [self.knowledge_base[i] for i in indices[0] if i < len(self.knowledge_base)]

    def generate_response(self, query, context):
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        prompt = (
            "You are a smart grocery assistant helping reduce food waste and manage groceries. "
            "Use this context to answer the question:\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            "Consider these factors in your response:\n"
            "1. Expiration dates and remaining shelf life\n"
            "2. Current stock levels and recent purchases\n"
            "3. Food categories and typical usage patterns\n"
            "4. Seasonal availability and storage constraints\n"
            "Provide practical, specific advice in a friendly tone."
)
        
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
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Sorry, I encountered an error: {str(e)}"

    def query(self, question):
        self.fetch_knowledge_base()  # Refresh data and embeddings
        if not self.knowledge_base:
            return "I don't have any grocery data yet. Please add items to your fridge or receipts!"
            
        context = self.retrieve_context(question)
        if not context:
            return "I couldn't find relevant information. Could you provide more details?"
            
        return self.generate_response(question, context)

    def run_chatbot(self):
        print("🍎 Smart Grocery Assistant: Ready to help manage your groceries and reduce waste!")
        print("Ask me about expiration dates, meal suggestions, or shopping list recommendations.")
        print("Type 'exit' to end the session.\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                if user_input.lower() in ['exit', 'quit']:
                    print("Assistant: Happy cooking! 🧑🍳")
                    break
                if not user_input:
                    continue
                
                response = self.query(user_input)
                print(f"Question: {user_input}")
                print(f"\nAssistant: {response}\n")
            except KeyboardInterrupt:
                print("\nAssistant: Session ended. Have a great day!")
                break