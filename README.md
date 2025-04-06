# Smart Grocery Assistant

## About 
<p>Term: Spring 2025    
<p>Student: Bright Ofori

#️⃣ **Keywords**: Section 0010, MLOps, Python, Flask, MySQL, Google Gemini API, DeepSeek API, Web Application

## 💻 Project Abstract:  
<p>The Smart Grocery Assistant is a web-based application designed to streamline grocery management and reduce food waste. Leveraging machine learning and API integrations, it processes receipt and fridge stock images to track grocery items, their quantities, weights, categories, purchase dates, expiration dates, and shelf lives. Users can upload images, edit records, and interact with an AI-powered chatbot for personalized meal planning and shopping advice. Built with Flask, MySQL, and advanced AI models, this project aims to enhance household efficiency and sustainability.</p>
<p>The system integrates Google Gemini for image processing, DeepSeek for natural language responses, and a MySQL database for persistent storage. It features a user-friendly interface styled with Bootstrap, enabling seamless navigation between receipt management, stock tracking, and conversational assistance. This project addresses the challenge of food waste by providing actionable insights based on real-time inventory data.</p>

### 🫧 Background

The idea for the Smart Grocery Assistant stemmed from the common struggle of managing groceries effectively in busy households. Inspired by the need to minimize food waste—a global issue costing billions annually—and the potential of AI to simplify daily tasks, our team set out to create an intuitive tool. The challenge was to integrate image recognition, database management, and natural language processing into a cohesive web application, overcoming hurdles like accurate data extraction from varied receipt formats and ensuring a responsive user experience.

## High Level Requirement
<p>The Smart Grocery Assistant must provide a web platform where users can upload images of grocery receipts and fridge contents, manage their inventory, and receive AI-driven recommendations. It should accurately extract item details from images, store them in a database, allow manual edits, and offer a chatbot interface for querying stock and planning meals. The system needs to be accessible, reliable, and visually appealing, with a focus on reducing food waste through timely expiration alerts and usage suggestions.</p>
<p>The application should support scalability for future enhancements, such as mobile app integration or cloud deployment, and ensure data persistence and security using MySQL. It must handle diverse image inputs and provide meaningful responses via the DeepSeek API, making grocery management effortless and insightful.</p>

### 📋 Functional Requirements

This project will produce a web application that:

<p>Enables users to upload receipt and stock images, process them using Google Gemini API, and store extracted data (name, quantity, weight, category, purchase/expiration dates, shelf life) in a MySQL database. It will provide an editable table view for receipt and stock items, and a chatbot interface powered by DeepSeek API for querying inventory and generating meal or shopping suggestions.</p>

- Upload and process receipt images to populate the receipts database.
- Upload and process fridge stock images to track current inventory.
- Allow users to edit receipt and stock entries via a web interface.
- Provide a chatbot for natural language queries about stock, expiration dates, and meal ideas.

### ✅ Non-functional Requirements

- Cloud-deployable solution for scalability.
- Responsive design compatible with desktop and mobile browsers.
- Secure handling of API keys and database credentials via environment variables.
- Fast image processing and database queries (under 5 seconds per operation).
- User-friendly interface with Bootstrap styling.

### ✍🏼 Conceptual Design

<p>The Smart Grocery Assistant operates as a three-tier web application: a front-end interface (Flask templates with Bootstrap), a back-end logic layer (Flask routes and agents), and a data layer (MySQL). Users interact via a navbar linking to Receipts, Stock, and Chat pages. Image uploads trigger API calls to Google Gemini for data extraction, which is then stored in MySQL. The chatbot uses vector embeddings (SentenceTransformer) and FAISS for context retrieval, feeding into DeepSeek for responses.</p>
<p>The design prioritizes modularity, with separate agents for receipt processing, stock management, and analysis. This allows for easy updates, such as swapping APIs or adding features like user authentication. The focus is on usability, with clear feedback via flash messages and a visually appealing layout.</p>

### 🛠️ Technical Design

<p>The application is built using Flask as the web framework, with Jinja2 templates extending a base HTML file styled with Bootstrap 5.3. The back-end integrates three Python agents: `ReceiptProcessorAgent` and `StockProcessorAgent` use Google Gemini API for image processing, while `SmartGroceryAnalyzer` employs SentenceTransformer for embeddings, FAISS for vector search, and DeepSeek API for chatbot responses. Data is stored in a MySQL database with tables for receipts (`id`, `name`, `quantity`, `weight`, `category`, `purchase_date`, `expiration_date`) and stock (`id`, `name`, `quantity`, `weight`, `category`, `shelf_life`).</p>
<p>Key technologies include `mysql-connector-python` for database access, `requests` for API calls, and `werkzeug` for secure file uploads. The system runs locally but is designed for potential cloud deployment (e.g., AWS, Heroku). Environment variables manage API keys and secrets, stored in a `.env` file.</p>

### 📦 Required Resources

- Linux/Windows/MacOS Development Machine
- Python 3.9+
- MySQL Database
- IDE/Text Editor (e.g., VS Code, PyCharm)
- Project Management (e.g., Jira, Trello)
- Version Control (GitHub/Git)
- Libraries: Flask, mysql-connector-python, pyyaml, python-dotenv, sentence-transformers, faiss-cpu, requests, werkzeug
- APIs: Google Gemini, DeepSeek

### Project Plan:  
<p>The project will be developed over the Spring 2025 term, starting with requirement gathering and design, followed by iterative development of image processing, database integration, and chatbot functionality. Testing will occur throughout, with a final deployment and demo by the term’s end. Weekly sprints will ensure steady progress, with milestones tied to core feature completion.</p>

## 🏁 Milestones 

| Date/Week      | Milestone             | Deliverables/Features                     |
|----------------|-----------------------|-------------------------------------------|
| Week 1 (Jan 6) | Scope/Spec            | Define project objectives and scope       |
| Week 2 (Jan 13)| Spec                  | Finalize specifications and architecture  |
| Week 4 (Jan 27)| Image Processing      | Receipt and stock image upload/processing |
| Week 6 (Feb 10)| Database Integration  | MySQL setup and CRUD operations           |
| Week 8 (Feb 24)| Chatbot Development   | AI chatbot with context retrieval         |
| Week 10 (Mar 10)| UI/UX Completion     | Finalize responsive design and styling    |
| Week 12 (Mar 24)| Testing/Optimization  | Bug fixes, performance tuning             |
| Week 14 (Apr 7) | Deployment/Demo       | Deploy locally and present demo           |

### 🧪 Test Cases

<p>Testing will ensure each component functions as expected. Unit tests will verify image processing accuracy (e.g., correct extraction of item details), database operations (e.g., successful CRUD), and chatbot responses (e.g., relevance to queries). Integration tests will check end-to-end flows, such as uploading a receipt and querying its contents via chat.</p>
<p>Sample test cases include:  
- Upload a receipt image with 5 items; verify all are stored in MySQL.  
- Edit a stock item’s quantity; confirm the update persists.  
- Ask the chatbot, “What’s expiring soon?”; ensure it lists items nearing expiration.  
- Test with invalid image formats to confirm error handling.</p>

### 👩🏻‍🏫 Installation Instructions

These instructions help build and run the project locally.

#### Minimum Requirements
- OS: Windows, MacOS, or Linux
- Python 3.9+
- MySQL Server 8.0+
- Git for version control

#### Steps
1. Clone the repository:
   ```bash
   git clone <this repo git link>
   ```
2. Navigate to the project directory:
   ```bash
   cd smart-grocery-assistant
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set up environment variables in a `.env` file:
   ```plaintext
   APP_SECRET_KEY=your_secret_key
   GEMINI_API_KEY=your_gemini_key
   DEEPSEEK_API_KEY=your_deepseek_key
   DB_PASSWORD=your_mysql_password
   ```
5. Configure MySQL:
   - Create a database named `grocery_db`.
   - Update `config.yaml` with your MySQL credentials if needed.
6. Run the Flask app:
   ```bash
   python app.py
   ```
7. Access the app at `http://localhost:5000` in a web browser.

### 👩🏻‍💻🧑🏻‍💻 Collaborators

[//]: # ( readme: collaborators -start )
<table>
<tr>
    <td align="center">
        <a href="https://github.com/[your-github-username]">
            <img src="https://avatars.githubusercontent.com/u/[your-user-id]?v=4" width="100;" alt="[Your Name]"/>
            <br />
            <sub><b>[Your Name]</b></sub>
        </a>
    </td>
    <!-- Add more team members here -->
</tr>
</table>


#requirements.txt

  ```
  flask
  mysql-connector-python
  pyyaml
  python-dotenv
  sentence-transformers
  faiss-cpu
  requests
  werkzeug
  ```
