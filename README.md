# 🚗 Honda AI Service Advisor (RAG Agent)

An intelligent SMS-based Service Advisor that automates customer support for Honda Service Centers. It uses Retrieval-Augmented Generation (RAG) to answer technical questions accurately by referencing official Owner's Manuals, preventing hallucinations.

## 🌟 Features

* **Multi-Vehicle Routing:** Intelligent semantic router distinguishes between different car contexts (e.g., *2025 Ridgeline* vs. *2024 Civic*) and queries the correct database namespace.
* **RAG Pipeline:** Ingests, chunks, and embeds PDF manuals into a Pinecone Vector Database for semantic search.
* **Session Memory:** "Remembers" the user's vehicle across the conversation, eliminating the need to ask "Which car?" repeatedly.
* **Human Handoff (Escalation):** Uses an LLM Supervisor to detect negative sentiment or requests for a human agent, bypassing the AI to flag a manager.
* **SMS Interface:** Fully accessible via text message using Twilio and FastAPI.

## 🏗️ Tech Stack

* **Language:** Python 3.12
* **Framework:** FastAPI
* **LLM:** OpenAI GPT-4o
* **Vector DB:** Pinecone
* **Orchestration:** LangChain
* **Interface:** Twilio (SMS)
* **Deployment:** Render (Dockerized Python environment)

## 🧩 Architecture Flow

1.  **Input:** User sends SMS via Twilio.
2.  **Guard:** "Supervisor" LLM checks for anger/escalation intent.
    * *If Angry:* Returns canned response + Alerts Human.
    * *If Normal:* Passes to Router.
3.  **Router:** Analyzes intent to identify Vehicle Model (Civic/Ridgeline/Passport).
4.  **Memory:** Checks/Updates session state (Redis/Dict) for user context.
5.  **Retrieval:** Queries Pinecone (`top_k=15`) for relevant manual pages.
6.  **Generation:** GPT-4o synthesizes an answer using *only* the retrieved context.
7.  **Output:** Sends SMS reply via Twilio.

## 🚀 Local Setup

1.  **Clone the repo**
    ```bash
    git clone [https://github.com/YOUR_USERNAME/honda-service-agent.git](https://github.com/YOUR_USERNAME/honda-service-agent.git)
    cd honda-service-agent
    ```

2.  **Install Dependencies**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Environment Variables**
    Create a `.env` file:
    ```ini
    OPENAI_API_KEY="sk-..."
    PINECONE_API_KEY="pc-..."
    TWILIO_ACCOUNT_SID="..."
    TWILIO_AUTH_TOKEN="..."
    TWILIO_PHONE_NUMBER="+1..."
    ```

4.  **Run Local Server**
    ```bash
    uvicorn main:app --reload
    ```

## 📂 Project Structure

* `main.py`: The FastAPI application, Router logic, and Memory management.
* `ingest.py`: ETL pipeline to load PDF manuals into Pinecone vectors.
* `requirements.txt`: Production dependencies.