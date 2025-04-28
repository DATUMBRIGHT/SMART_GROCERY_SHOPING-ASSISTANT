import numpy as np
import faiss
import yaml
import os
import arrow
from sentence_transformers import SentenceTransformer
from functools import lru_cache
from dotenv import load_dotenv
from loggers.custom_logger import logger
import requests
from flask import Flask, session, request, render_template, redirect, url_for, flash
from wtforms import Form, StringField, validators
from threading import Lock
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import List, Dict, Any, Optional, Union
import markdown



# Load environment variables
load_dotenv()

# Configuration paths
BASE_URL = os.path.join(os.path.dirname(__file__), '..')
CONFIG_PATH = os.path.join(BASE_URL, 'constants', 'config.yaml')

# Load DeepSeek API configuration
try:
    with open(CONFIG_PATH, 'r') as file:
        config = yaml.safe_load(file)
        DEEPSEEK_API_URL = config['deepseek']['api_url']
        DEEPSEEK_MODEL = config['deepseek']['model']
        DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set in environment variables")
        raise ValueError("DEEPSEEK_API_KEY is required")
except (FileNotFoundError, yaml.YAMLError) as e:
    logger.error(f"Failed to load config: {e}")
    raise

# Flask App Initialization
app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')
chat_lock = Lock()

# Forms
class ChatForm(Form):
    query = StringField('Query', [validators.DataRequired()])

class DeleteChatForm(Form):
    pass

# Type aliases
Embedding = np.ndarray
KnowledgeItem = str
StockItem = Dict[str, Union[str, int, float]]
ReceiptItem = Dict[str, Union[str, int, float]]
UserInfo = Dict[str, Union[str, int, bool, None]]


# GroceryAnalyzer
class GroceryAnalyzer:
    def __init__(self, stock_agent, receipt_agent, db_manager):
        try:
            self.stock_agent = stock_agent
            self.receipt_agent = receipt_agent
            self.db_manager = db_manager
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
            self.embedding_dim = self.embedder.get_sentence_embedding_dimension()
            self.user_caches: Dict[int, Dict[str, Any]] = {}
            logger.info("GroceryAnalyzer initialized")
        except Exception as e:
            logger.error(f"GroceryAnalyzer init failed: {e}", exc_info=True)
            raise

    def _initialize_user_cache(self, user_id: int):
        if user_id not in self.user_caches:
            self.user_caches[user_id] = {
                'index': faiss.IndexFlatL2(self.embedding_dim),
                'knowledge': []
            }
            logger.debug(f"Initialized cache for user {user_id}")

    def _safe_fetch_stock(self, user_id: int) -> List[Dict]:
        logger.debug(f"Fetching stock for user {user_id}")
        try:
            items = self.stock_agent.fetch_all_stockitems(user_id) or []
            logger.debug(f"Raw stock items: {items}")
            return [item for item in items if self._validate_stock_item(item)]
        except Exception as e:
            logger.error(f"Stock fetch failed: {e}", exc_info=True)
            return []

    def _safe_fetch_receipts(self, user_id: int) -> List[Dict]:
        logger.debug(f"Fetching receipts for user {user_id}")
        try:
            items = self.receipt_agent.fetch_all_receipts_items(user_id) or []
            logger.debug(f"Raw receipt items: {items}")
            return items
        except Exception as e:
            logger.error(f"Receipt fetch failed: {e}", exc_info=True)
            return []

    def _safe_fetch_user_info(self, user_id: int) -> List[Dict]:
        logger.debug(f"Fetching user info for user {user_id}")
        try:
            info = self.db_manager.fetch_user_relevant_info(user_id) or []
            logger.debug(f"Raw user info: {info}")
            return info
        except Exception as e:
            logger.error(f"User info fetch failed: {e}", exc_info=True)
            return []

    def _validate_stock_item(self, item: Dict) -> bool:
        required = ['name', 'quantity', 'category']
        return all(key in item for key in required) and isinstance(item['quantity'], (int, float))

    def _build_knowledge_items(self, stock_items, receipt_items, user_details) -> List[str]:
        knowledge = []
        for item in stock_items:
            knowledge.append(f"Stock: {item['name']}, Quantity: {item['quantity']}, Category: {item['category']}")
        for item in receipt_items:
            knowledge.append(f"Receipt: {item['name']}, Purchased: {item['purchase_date']}")
        for info in user_details:
            knowledge.append(f"User: {info.get('first_name', 'Unknown')}, Allergies: {info.get('allergies', 'None')}")
        return knowledge

    def _update_index(self, user_id: int, knowledge: List[str]) -> None:
        logger.debug(f"Updating FAISS index for user {user_id}")
        try:
            logger.debug("Encoding knowledge items")
            embeddings = self.embedder.encode(knowledge, batch_size=8, show_progress_bar=False)
            logger.debug(f"Encoded {len(embeddings)} embeddings")
            embeddings = np.array(embeddings, dtype=np.float32)
            self.user_caches[user_id]['index'] = faiss.IndexFlatL2(self.embedding_dim)
            self.user_caches[user_id]['index'].add(embeddings)
            self.user_caches[user_id]['knowledge'] = knowledge
            logger.debug(f"Updated FAISS index with {len(knowledge)} items")
        except Exception as e:
            logger.error(f"Index update failed for user {user_id}: {e}", exc_info=True)
            raise

    @lru_cache(maxsize=100)
    def fetch_knowledge_base(self, user_id: int) -> tuple:
        logger.debug(f"Building knowledge base for user {user_id}")
        try:
            self._initialize_user_cache(user_id)
            stock_items = self._safe_fetch_stock(user_id)
            receipt_items = self._safe_fetch_receipts(user_id)
            user_details = self._safe_fetch_user_info(user_id)
            knowledge = self._build_knowledge_items(stock_items, receipt_items, user_details)
            if not knowledge:
                logger.warning(f"No knowledge items for user {user_id}")
                return tuple()
            self._update_index(user_id, knowledge)
            return tuple(knowledge)
        except Exception as e:
            logger.error(f"Failed to build knowledge base: {e}", exc_info=True)
            raise

    def retrieve_context(self, user_id: int, query: str) -> List[str]:
        logger.debug(f"Retrieving context for user {user_id}, query: {query}")
        try:
            if user_id not in self.user_caches or not self.user_caches[user_id]['knowledge']:
                logger.debug("No knowledge base for user")
                return []
            query_embedding = self.embedder.encode([query], batch_size=1, show_progress_bar=False)[0]
            query_embedding = np.array([query_embedding], dtype=np.float32)
            distances, indices = self.user_caches[user_id]['index'].search(query_embedding, k=3)
            context = [self.user_caches[user_id]['knowledge'][i] for i in indices[0] if i >= 0]
            logger.debug(f"Context: {context}")
            return context
        except Exception as e:
            logger.error(f"Context retrieval failed: {e}", exc_info=True)
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.exceptions.RequestException, requests.exceptions.HTTPError))
    )
    def _call_llm_api(self, prompt: str) -> Dict:
        logger.debug(f"Sending LLM request with prompt: {prompt[:50]}...")
        try:
            response = requests.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}]},
                timeout=30
            )
            response.raise_for_status()
            logger.debug(f"LLM response: {response.json()}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"LLM API request failed: {e}, status_code={getattr(e.response, 'status_code', 'N/A')}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in LLM API request: {e}", exc_info=True)
            raise

    def _process_llm_response(self, response: Dict) -> str:
        logger.debug(f"Processing LLM response: {response}")
        try:
            if 'choices' in response and response['choices']:
                return response['choices'][0]['message']['content'].strip()
            logger.error(f"Unexpected response format: {response}")
            return "Error processing AI response"
        except Exception as e:
            logger.error(f"Failed to process LLM response: {e}", exc_info=True)
            return "Error processing AI response"

    def _build_prompt(self, query: str, context: List[str]) -> str:
        prompt = "You are a grocery assistant. Answer the query based on the context provided.\n"
        if context:
            prompt += "Context:\n" + "\n".join(context) + "\n\n"
        prompt += f"Query: {query}\nAnswer:"
        return prompt

    def generate_response(self, user_id: int, query: str, context: List[str]) -> str:
        logger.debug(f"Generating response for user {user_id}, query: {query}")
        try:
            prompt = self._build_prompt(query, context)
            response = self._call_llm_api(prompt)
            return self._process_llm_response(response)
        except Exception as e:
            logger.error(f"Response generation failed: {e}", exc_info=True)
            return "Sorry, I couldn't process your request."


