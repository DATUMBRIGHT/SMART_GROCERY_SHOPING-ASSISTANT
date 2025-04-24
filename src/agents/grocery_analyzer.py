import numpy as np
import requests
import aiohttp
import asyncio
import faiss
import yaml
import os
import torch
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from functools import lru_cache
from loggers.custom_logger import logger

# Load environment variables
load_dotenv()

BASE_URL = os.path.join(os.path.dirname(__file__), '..')
CONFIG_PATH = os.path.join(BASE_URL, 'constants', 'config.yaml')

# Load configuration
with open(CONFIG_PATH, 'r') as file:
    config = yaml.safe_load(file)
    DEEPSEEK_API_URL = config['deepseek']['api_url']
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

class SmartGroceryAnalyzer:
    def __init__(self, stock_agent, receipt_agent, db_manager):
        self.stock_agent = stock_agent
        self.receipt_agent = receipt_agent
        self.db_manager = db_manager
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2', device='cuda' if torch.cuda.is_available() else 'cpu')
        self.index = None
        self.knowledge_base = []
        self.embeddings = None
        self.last_data_hash = None  # For checking data changes
        self._init_vector_index()
        logger.info("SmartGroceryAnalyzer initialized successfully")

    def _init_vector_index(self):
        """Initialize FAISS IndexIVFFlat for faster vector search."""
        dimension = self.embedder.get_sentence_embedding_dimension()
        nlist = 100  # Number of clusters
        quantizer = faiss.IndexFlatL2(dimension)
        self.index = faiss.IndexIVFFlat(quantizer, dimension, nlist)
        # Load from disk if exists
        index_path = os.path.join(BASE_URL, 'faiss_index.bin')
        if os.path.exists(index_path):
            self.index = faiss.read_index(index_path)
        logger.info("FAISS IndexIVFFlat initialized successfully")

    def _update_vector_index(self, embeddings):
        """Update FAISS index with new embeddings and save to disk."""
        self.index.reset()
        if embeddings.size > 0:
            self.index.train(embeddings)  # Train the index
            self.index.add(embeddings)
            # Save index to disk
            index_path = os.path.join(BASE_URL, 'faiss_index.bin')
            faiss.write_index(self.index, index_path)
        logger.info("FAISS index updated successfully")

    def _hash_data(self, stock_items, receipt_items, user_info):
        """Create a hash to detect data changes."""
        import hashlib
        data_str = f"{stock_items}{receipt_items}{user_info}"
        return hashlib.md5(data_str.encode()).hexdigest()

    async def fetch_knowledge_base(self, user_id, stock_id):
        """Fetch and combine data from stock and receipt agents asynchronously."""
        try:
            # Fetch data concurrently
            stock_task = asyncio.create_task(self.stock_agent.fetch_stock(user_id, stock_id))
            receipt_task = asyncio.create_task(self.receipt_agent.fetch_all_receipts_items(user_id))
            user_task = asyncio.create_task(self.db_manager.get_user_relevant_info(user_id))
            stock_items, receipt_items, user_info = await asyncio.gather(stock_task, receipt_task, user_task)

            # Check if data has changed
            current_hash = self._hash_data(stock_items, receipt_items, user_info)
            if self.last_data_hash == current_hash and self.knowledge_base:
                logger.info("No data changes detected, using cached knowledge base")
                return self.knowledge_base

            # Format knowledge base entries
            self.knowledge_base = [
                f"Current Fridge stock or groceries: {item['name']}, quantity: {item['quantity']}, weight: {item['weight']}, "
                f"category: {item['category']}, shelf_life: {item['shelf_life']} days"
                for item in stock_items
            ] + [
                f"ALL receipts items: {item['name']}, quantity: {item['quantity']}, weight: {item['weight']}, "
                f"category: {item['category']}, purchase_date: {item['purchase_date']}, "
                f"expiration_date: {item['expiration_date']}"
                for item in receipt_items
            ] + user_info

            # Generate embeddings
            if self.knowledge_base:
                self.embeddings = self.embedder.encode(
                    self.knowledge_base, batch_size=128, convert_to_tensor=False
                )
                self._update_vector_index(np.array(self.embeddings).astype('float32'))
                self.last_data_hash = current_hash
            logger.info("Fetched and embedded stock, receipt items, and user info successfully")
            return self.knowledge_base
        except Exception as e:
            logger.error(f"Error fetching knowledge base: {str(e)}")
            return []

    def retrieve_context(self, query, max_docs=5):
        """Retrieve relevant context from the knowledge base using vector search."""
        if not self.knowledge_base or self.index is None or self.index.ntotal == 0:
            logger.warning("Knowledge base or index is empty")
            return []

        # Encode query and search index
        query_embedding = self.embedder.encode([query], convert_to_tensor=False)
        self.index.nprobe = 10  # Tune for speed vs. accuracy
        distances, indices = self.index.search(np.array(query_embedding).astype('float32'), max_docs)
        
        # Return relevant context documents
        context = [self.knowledge_base[i] for i in indices[0] if i >= 0 and i < len(self.knowledge_base)]
        logger.info(f"Retrieved {len(context)} context items for query")
        return context

    async def generate_response(self, query, context):
        """Generate a response using the DeepSeek API asynchronously."""
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        prompt = (
            f"You are a smart grocery assistant helping reduce food waste. "
            f"Context: {context}\n"
            f"Question: {query}\n"
            f"Provide practical advice considering expiration dates, stock levels, food categories, and user info."
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
            async with aiohttp.ClientSession() as session:
                async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    result = await response.json()
                    response_text = result["choices"][0]["message"]["content"]
                    logger.info("Response generated successfully")
                    return response_text
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            return f"Sorry, I encountered an error: {str(e)}"

    @lru_cache(maxsize=1000)
    async def query(self, question, user_id, stock_id):
        """Process a user query and return a response."""
        await self.fetch_knowledge_base(user_id, stock_id)
        if not self.knowledge_base:
            return "I don't have any grocery data yet. Please add items to your fridge or receipts!"
            
        context = self.retrieve_context(question)
        if not context:
            return "I couldn't find relevant information. Could you provide more details?"
            
        return await self.generate_response(question, context)

    async def run_chatbot(self, user_id, stock_id):
        """Run the chatbot interactively."""
        print("Assistant: Hello! I'm your grocery assistant. Ask me anything about your groceries (type 'exit' to quit).")
        while True:
            try:
                user_input = input("You: ").strip()
                if user_input.lower() in ['exit', 'quit']:
                    print("Assistant: Happy cooking! 🧑‍🍳")
                    break
                if not user_input:
                    print("Assistant: Please ask me something!")
                    continue
                
                response = await self.query(user_input, user_id, stock_id)
                print(f"Question: {user_input}")
                print(f"Assistant: {response}\n")
            except KeyboardInterrupt:
                print("\nAssistant: Session ended. Have a great day!")
                break
            except Exception as e:
                print(f"Assistant: Oops, something went wrong: {str(e)}")
                continue